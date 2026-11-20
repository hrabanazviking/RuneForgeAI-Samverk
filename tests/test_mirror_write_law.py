"""S-334 acceptance battery: mirror write law.

Acceptance (roadmap S-334): mirrors are read-only for local
changes; the UI and transports refuse pushes to a mirror
with the reason stated.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import io, os, subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.git_http import SmartHttpService, TransportError
from samverk.mirror_write_law import (
    REASON_MIRROR_READ_ONLY, MirrorWriteError, MirrorWriteLaw,
    decide_mirror_write, decision_to_dict, mirror_row_for,
    render_mirror_read_only_notice, render_mirror_write_law_page,
    write_refusal_message)
from samverk.mirrors import MirrorService
from samverk.receive_gate import ReceiveGate
from samverk.repositories import RepositoryStore
from test_ssh_upload_routing import FakeRunner, make_world, serve


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def make_source(base: Path, name: str = "src.git") -> tuple[Path, str]:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=b"hi\n")
    tree = git(src, "mktree", input_bytes=f"100644 blob {blob}\tx.txt\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src, commit


class MirrorWriteLawTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.mirrors = MirrorService(self.conn, self.data_root,
                                     self.accounts, self.repos)
        self.law = MirrorWriteLaw(self.conn, self.data_root,
                                  self.accounts, self.repos)
        self.mirrors.create_mirror(self.owner.id, "volmarr", "mir", self.src)
        self.repos.create_repository(self.owner.id, "volmarr", "plain")

    # -- pins ---------------------------------------------------
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 135)
        self.assertEqual(db.MIGRATIONS[-1][0], 135)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- the pure judgement --------------------------------------
    def test_pure_decision_refuses_a_mirror_with_reason(self):
        mirror = self.mirrors.mirror_for("volmarr", "mir")
        decision = decide_mirror_write("volmarr/mir", mirror)
        self.assertFalse(decision.allowed)
        self.assertTrue(decision.is_mirror)
        self.assertEqual(decision.reason, REASON_MIRROR_READ_ONLY)
        self.assertIn("volmarr/mir", decision.message)
        self.assertIn(str(self.src), decision.message)
        self.assertIn("read-only", decision.message)

    def test_pure_decision_allows_a_plain_repository(self):
        decision = decide_mirror_write("volmarr/plain", None)
        self.assertTrue(decision.allowed)
        self.assertFalse(decision.is_mirror)
        self.assertEqual(decision.reason, "ok")

    def test_refusal_sentence_is_the_one_wording(self):
        self.assertEqual(
            write_refusal_message("volmarr/mir", "/x/src.git"),
            "volmarr/mir is a mirror of /x/src.git and mirrors are "
            "read-only for local changes, so this change is refused. "
            "Change the source repository instead and let the mirror "
            "sync.")

    # -- the service ----------------------------------------------
    def test_judge_and_require_writable(self):
        decision = self.law.judge("volmarr", "mir")
        self.assertFalse(decision.allowed)
        with self.assertRaises(MirrorWriteError) as caught:
            self.law.require_writable("volmarr", "mir")
        self.assertEqual(caught.exception.reason, "mirror_read_only")
        self.assertIn("read-only", str(caught.exception))
        ok = self.law.require_writable("volmarr", "plain")
        self.assertTrue(ok.allowed)

    def test_judge_missing_repository_raises(self):
        with self.assertRaises(MirrorWriteError) as caught:
            self.law.judge("volmarr", "ghost")
        self.assertEqual(caught.exception.reason, "no_such_repo")

    def test_mirror_row_for_reads_the_record(self):
        repo = self.repos.get_repository("volmarr", "mir")
        self.assertEqual(mirror_row_for(self.conn, repo.id),
                         (str(self.src), "local"))
        plain = self.repos.get_repository("volmarr", "plain")
        self.assertIsNone(mirror_row_for(self.conn, plain.id))

    def test_judging_writes_and_witnesses_nothing(self):
        before = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.law.judge("volmarr", "mir")
        self.law.judge("volmarr", "plain")
        after = self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(before, after)

    def test_decision_to_dict_carries_the_reason(self):
        d = decision_to_dict(self.law.judge("volmarr", "mir"))
        self.assertEqual(d["reason"], "mirror_read_only")
        self.assertFalse(d["allowed"])
        self.assertEqual(d["source"], str(self.src))

    # -- sync is not a local change --------------------------------
    def test_sync_still_converges_under_the_law(self):
        result = self.mirrors.sync_mirror("volmarr", "mir")
        self.assertEqual(result.status, "ok")
        from samverk.refs import RefStore
        path = self.repos.path_for("volmarr", "mir")
        self.assertEqual(RefStore(path).resolve("refs/heads/main"),
                         self.commit)
        # And the law still refuses local writes afterwards.
        self.assertFalse(self.law.judge("volmarr", "mir").allowed)

    def test_detach_ends_the_law(self):
        self.mirrors.detach_mirror(self.owner.id, "volmarr", "mir")
        self.assertTrue(self.law.judge("volmarr", "mir").allowed)
        self.assertTrue(self.law.require_writable("volmarr", "mir").allowed)

    # -- the receive-gate door --------------------------------------
    def test_gate_plugin_refuses_mirror_allows_plain(self):
        gate = ReceiveGate()
        gate.register_protection("mirror_write_law", self.law.gate_plugin)
        refused = gate.check(owner="volmarr", repo="mir",
                             actor="volmarr", transport="http")
        self.assertFalse(refused.allowed)
        self.assertIn("read-only", refused.reason)
        self.assertIn(str(self.src), refused.reason)
        allowed = gate.check(owner="volmarr", repo="plain",
                             actor="volmarr", transport="http")
        self.assertTrue(allowed.allowed)

    # -- the UI ------------------------------------------------------
    def test_page_states_the_law_for_a_mirror(self):
        page = render_mirror_write_law_page(self.law.judge("volmarr", "mir"))
        self.assertIn("volmarr/mir", page)
        self.assertIn("Read-only for local changes: yes", page)
        self.assertIn(str(self.src), page)
        self.assertIn("read-only", page)

    def test_page_states_a_plain_repository_is_writable(self):
        page = render_mirror_write_law_page(self.law.judge("volmarr", "plain"))
        self.assertIn("not a mirror", page)
        self.assertIn("Read-only for local changes: no", page)

    def test_notice_fragment_only_for_mirrors(self):
        notice = render_mirror_read_only_notice(self.law.judge("volmarr", "mir"))
        self.assertIn("Read-only mirror:", notice)
        self.assertIn("read-only", notice)
        self.assertEqual(
            render_mirror_read_only_notice(self.law.judge("volmarr", "plain")),
            "")

    def test_renders_escape_html(self):
        mirror = self.mirrors.mirror_for("volmarr", "mir")
        from dataclasses import replace
        evil = replace(mirror, source="<script>alert(1)</script>")
        page = render_mirror_write_law_page(
            decide_mirror_write("volmarr/mir", evil))
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)

    # -- the HTTP transport door --------------------------------------
    def test_http_receive_advertisement_refused_for_mirror(self):
        service = SmartHttpService(self.conn, self.data_root,
                                   self.accounts, self.repos)
        with self.assertRaises(TransportError) as caught:
            service.advertise(self.owner, "volmarr", "mir",
                              "git-receive-pack")
        self.assertEqual(caught.exception.reason, "mirror_read_only")
        self.assertIn("read-only", str(caught.exception))

    def test_http_receive_post_refused_for_mirror(self):
        service = SmartHttpService(self.conn, self.data_root,
                                   self.accounts, self.repos)
        with self.assertRaises(TransportError) as caught:
            service.receive_pack(self.owner, "volmarr", "mir", b"")
        self.assertEqual(caught.exception.reason, "mirror_read_only")

    def test_http_reads_still_served_for_mirror(self):
        self.mirrors.sync_mirror("volmarr", "mir")
        service = SmartHttpService(self.conn, self.data_root,
                                   self.accounts, self.repos)
        resp = service.advertise(self.owner, "volmarr", "mir",
                                 "git-upload-pack")
        self.assertIn(b"git-upload-pack", resp.body)

    def test_http_plain_repository_receive_not_refused_by_this_law(self):
        service = SmartHttpService(self.conn, self.data_root,
                                   self.accounts, self.repos)
        resp = service.advertise(self.owner, "volmarr", "plain",
                                 "git-receive-pack")
        self.assertIn(b"git-receive-pack", resp.body)


class SshDoorTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)
        root = self.w["root"]
        outside = root / "outside"; outside.mkdir()
        self.src, self.commit = make_source(outside)
        self.mirrors = MirrorService(self.w["conn"], root,
                                     self.w["accounts"], self.w["repos"])
        self.mirrors.attach_mirror(self.w["owner"].id, "volmarr",
                                   "samverk", self.src)

    def test_ssh_receive_pack_refused_for_mirror(self):
        rc, _, err = serve(self.w, self.w["owner_fp"],
                           "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 128)
        self.assertIn(b"read-only", err)
        self.assertIn(b"mirror", err)
        self.assertEqual(self.runner.calls, [])

    def test_ssh_upload_pack_still_runs_for_mirror(self):
        rc, _, _ = serve(self.w, self.w["owner_fp"],
                         "git-upload-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.runner.calls), 1)
        self.assertEqual(self.runner.calls[0][1], "upload-pack")


if __name__ == "__main__":
    unittest.main()
