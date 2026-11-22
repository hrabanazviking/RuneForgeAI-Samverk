"""S-339 acceptance battery: wiki mirror.

Acceptance (roadmap S-339): a source repo's wiki
(S-273 form) mirrors alongside its code repo.
"""
from __future__ import annotations
import subprocess, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.mirror_credentials import MirrorCredentialService
from samverk.mirrors import MirrorService
from samverk.repositories import RepositoryStore
from samverk.secrets import Secrets
from samverk.wiki_mirror import (
    ACTION_NO_WIKI, ACTION_REFUSE, ACTION_SYNC, FAILED, NO_WIKI,
    PHASE_WIKI, PROBE_ABSENT, PROBE_PRESENT, PROBE_UNREADABLE,
    STATE_FAILED, STATE_NEVER_SYNCED, STATE_NOT_A_MIRROR, STATE_NO_WIKI,
    STATE_SYNCED, VERIFIED, WikiMirrorError, WikiMirrorService,
    decide_wiki_sync, render_wiki_mirror_page, state_from_run,
    wiki_source_for)
from samverk.wiki_storage import WikiStore


def git(repo: Path, *args: str, input_bytes: bytes | None = None) -> str:
    import os
    env = dict(os.environ)
    env.update({"GIT_AUTHOR_NAME": "A", "GIT_AUTHOR_EMAIL": "a@e.c",
                "GIT_COMMITTER_NAME": "A", "GIT_COMMITTER_EMAIL": "a@e.c"})
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         input=input_bytes, capture_output=True, env=env)
    if out.returncode != 0:
        raise AssertionError(out.stderr.decode())
    return out.stdout.decode().strip()


def make_bare(base: Path, name: str, filename: str, body: bytes) -> Path:
    src = base / name
    subprocess.run(["git", "init", "--bare", "-b", "main", str(src)],
                   check=True, capture_output=True)
    blob = git(src, "hash-object", "-w", "--stdin", input_bytes=body)
    tree = git(src, "mktree",
               input_bytes=f"100644 blob {blob}\t{filename}\n".encode())
    commit = git(src, "commit-tree", tree, input_bytes=b"first\n")
    git(src, "update-ref", "refs/heads/main", commit)
    return src


class WikiMirrorTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        root = Path(self._td.name)
        self.outside = root / "outside"; self.outside.mkdir()
        self.data_root = root / "instance"; self.data_root.mkdir()
        self.conn = db.init_db(self.data_root / "samverk.db")
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.data_root, self.accounts)
        self.audit = AuditLog(self.conn)
        self.mirrors = MirrorService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.creds = MirrorCredentialService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.wiki_mirror = WikiMirrorService(
            self.conn, self.data_root, self.accounts, self.repos, self.audit)
        self.wiki = WikiStore(self.conn, self.repos, self.audit)

    def make_mirror(self, name: str, with_wiki: bool = True,
                    wiki_body: bytes = b"# Home\n") -> Path:
        src = make_bare(self.outside, f"{name}.git", "code.txt", b"code\n")
        if with_wiki:
            make_bare(self.outside, f"{name}.wiki", "Home.md", wiki_body)
        self.mirrors.create_mirror(self.owner.id, "volmarr", name, src)
        return src

    # -- pins ------------------------------------------------------
    def test_schema_and_taxonomy_pins_unchanged(self):
        self.assertEqual(schema_version(self.conn), 139)
        self.assertEqual(db.MIGRATIONS[-1][0], 139)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 138)

    # -- pure derivation ---------------------------------------------
    def test_derive_local_git_source(self):
        self.assertEqual(
            wiki_source_for(Path("/srv/code.git"), "local"),
            Path("/srv/code.wiki"))

    def test_derive_local_bare_name_source(self):
        self.assertEqual(
            wiki_source_for(Path("/srv/code"), "local"),
            Path("/srv/code.wiki"))

    def test_derive_remote_git_source(self):
        self.assertEqual(
            wiki_source_for("https://github.com/o/code.git", "url"),
            "https://github.com/o/code.wiki.git")

    def test_derive_remote_bare_source(self):
        self.assertEqual(
            wiki_source_for("https://github.com/o/code", "url"),
            "https://github.com/o/code.wiki.git")

    def test_derive_refuses_wiki_source_and_bad_kind(self):
        with self.assertRaises(WikiMirrorError):
            wiki_source_for(Path("/srv/code.wiki"), "local")
        with self.assertRaises(WikiMirrorError):
            wiki_source_for("https://github.com/o/code.wiki.git", "url")
        with self.assertRaises(WikiMirrorError):
            wiki_source_for(Path("/srv/code.git"), "carrier-pigeon")

    # -- pure decisions ------------------------------------------------
    def test_decide_sync_only_for_present_wiki_of_a_mirror(self):
        self.assertEqual(decide_wiki_sync(True, PROBE_PRESENT).action, ACTION_SYNC)
        self.assertEqual(decide_wiki_sync(True, PROBE_ABSENT).action, ACTION_NO_WIKI)
        self.assertEqual(decide_wiki_sync(True, PROBE_UNREADABLE).action, ACTION_REFUSE)
        self.assertEqual(decide_wiki_sync(False, PROBE_PRESENT).action, ACTION_REFUSE)

    def test_state_from_run_words(self):
        self.assertEqual(state_from_run(VERIFIED), STATE_SYNCED)
        self.assertEqual(state_from_run(NO_WIKI), STATE_NO_WIKI)
        self.assertEqual(state_from_run(FAILED), STATE_FAILED)
        self.assertEqual(state_from_run(None), STATE_NEVER_SYNCED)

    # -- the sync ------------------------------------------------------
    def test_wiki_syncs_and_verifies_ref_for_ref(self):
        self.make_mirror("proj")
        run = self.wiki_mirror.sync_wiki("volmarr", "proj")
        self.assertEqual(run.state, VERIFIED)
        self.assertEqual(run.refs_matched, 1)
        page = self.wiki.read_page(self.owner, "volmarr", "proj", "Home")
        self.assertEqual(page.content, "# Home\n")
        status = self.wiki_mirror.status_for("volmarr", "proj")
        self.assertEqual(status.state, STATE_SYNCED)
        self.assertTrue(status.wiki_source.endswith("proj.wiki"))

    def test_wiki_sync_follows_source_updates(self):
        self.make_mirror("proj")
        self.wiki_mirror.sync_wiki("volmarr", "proj")
        wiki_src = self.outside / "proj.wiki"
        blob = git(wiki_src, "hash-object", "-w", "--stdin",
                   input_bytes=b"# Home v2\n")
        tree = git(wiki_src, "mktree",
                   input_bytes=f"100644 blob {blob}\tHome.md\n".encode())
        tip = git(wiki_src, "rev-parse", "refs/heads/main")
        commit = git(wiki_src, "commit-tree", tree, "-p", tip,
                     input_bytes=b"second\n")
        git(wiki_src, "update-ref", "refs/heads/main", commit)
        run = self.wiki_mirror.sync_wiki("volmarr", "proj")
        self.assertEqual(run.state, VERIFIED)
        page = self.wiki.read_page(self.owner, "volmarr", "proj", "Home")
        self.assertEqual(page.content, "# Home v2\n")
        self.assertEqual(len(self.wiki_mirror.runs_for("volmarr/proj")), 2)

    def test_source_without_wiki_reports_no_wiki_and_creates_nothing(self):
        self.make_mirror("bare", with_wiki=False)
        run = self.wiki_mirror.sync_wiki("volmarr", "bare")
        self.assertEqual(run.state, NO_WIKI)
        self.assertIn("no wiki", run.detail)
        self.assertFalse(self.wiki_mirror.wiki_path("volmarr", "bare").exists())
        status = self.wiki_mirror.status_for("volmarr", "bare")
        self.assertEqual(status.state, STATE_NO_WIKI)

    def test_empty_source_wiki_reports_no_wiki(self):
        src = make_bare(self.outside, "empty.git", "code.txt", b"code\n")
        subprocess.run(["git", "init", "--bare", "-b", "main",
                        str(self.outside / "empty.wiki")],
                       check=True, capture_output=True)
        self.mirrors.create_mirror(self.owner.id, "volmarr", "empty", src)
        run = self.wiki_mirror.sync_wiki("volmarr", "empty")
        self.assertEqual(run.state, NO_WIKI)

    def test_not_a_mirror_is_refused_plainly(self):
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        with self.assertRaises(WikiMirrorError) as caught:
            self.wiki_mirror.sync_wiki("volmarr", "plain")
        self.assertEqual(caught.exception.reason, "not_a_mirror")
        status = self.wiki_mirror.status_for("volmarr", "plain")
        self.assertEqual(status.state, STATE_NOT_A_MIRROR)
        self.assertFalse(status.is_mirror)

    def test_never_synced_status_is_honest(self):
        self.make_mirror("proj")
        status = self.wiki_mirror.status_for("volmarr", "proj")
        self.assertEqual(status.state, STATE_NEVER_SYNCED)
        self.assertIsNone(status.last_run_at)

    def test_drifted_local_wiki_path_fails_and_is_not_adopted(self):
        self.make_mirror("proj")
        path = self.wiki_mirror.wiki_path("volmarr", "proj")
        path.mkdir(parents=True)
        (path / "junk.txt").write_text("junk")
        run = self.wiki_mirror.sync_wiki("volmarr", "proj")
        self.assertEqual(run.state, FAILED)
        self.assertIn("not a bare git repository", run.detail)
        self.assertTrue((path / "junk.txt").exists())

    def test_unreadable_source_wiki_fails_not_no_wiki(self):
        src = make_bare(self.outside, "bad.git", "code.txt", b"code\n")
        (self.outside / "bad.wiki").mkdir()
        self.mirrors.create_mirror(self.owner.id, "volmarr", "bad", src)
        run = self.wiki_mirror.sync_wiki("volmarr", "bad")
        self.assertEqual(run.state, FAILED)

    # -- credential gate (S-330, same as code) --------------------------
    def test_named_but_unloaded_credential_refuses_before_fetch(self):
        self.make_mirror("proj")
        self.creds.set_credential(self.owner.id, "volmarr", "proj", "WIKI_TOKEN")
        run = self.wiki_mirror.sync_wiki("volmarr", "proj", secrets=None)
        self.assertEqual(run.state, FAILED)
        self.assertIn("credential gate refused", run.detail)
        self.assertNotIn("test-token-value", run.detail)
        self.assertFalse(self.wiki_mirror.wiki_path("volmarr", "proj").exists())

    def test_loaded_credential_syncs(self):
        self.make_mirror("proj")
        self.creds.set_credential(self.owner.id, "volmarr", "proj", "WIKI_TOKEN")
        secrets = Secrets({"WIKI_TOKEN": "test-token-value"})
        run = self.wiki_mirror.sync_wiki("volmarr", "proj", secrets=secrets)
        self.assertEqual(run.state, VERIFIED)

    # -- cadence + batch --------------------------------------------------
    def test_sync_alongside_code_syncs_both(self):
        self.make_mirror("proj")
        run = self.wiki_mirror.sync_alongside_code("volmarr", "proj")
        self.assertEqual(run.state, VERIFIED)
        mirror = self.mirrors.mirror_for("volmarr", "proj")
        self.assertEqual(mirror.last_status, "ok")

    def test_sync_owner_wikis_reports_each_honestly(self):
        self.make_mirror("alpha")
        self.make_mirror("beta", with_wiki=False)
        self.repos.create_repository(self.owner.id, "volmarr", "plain")
        report = self.wiki_mirror.sync_owner_wikis("volmarr")
        self.assertEqual(report.verified_count, 1)
        self.assertEqual(report.no_wiki_count, 1)
        self.assertEqual(len(report.failed), 0)
        self.assertEqual(len(report.runs), 2)
        self.assertIn("1 verified", report.headline)
        self.assertIn("1 with no source wiki", report.headline)

    def test_sync_owner_wikis_with_no_mirrors_notes_it(self):
        report = self.wiki_mirror.sync_owner_wikis("volmarr")
        self.assertEqual(report.runs, [])
        self.assertIn("no mirrors", report.note)

    def test_runs_recorded_under_wiki_phase(self):
        self.make_mirror("proj")
        self.wiki_mirror.sync_wiki("volmarr", "proj")
        rows = self.conn.execute(
            "SELECT phase FROM first_pass_mirror_runs").fetchall()
        self.assertEqual([r["phase"] for r in rows], [PHASE_WIKI])

    # -- render -----------------------------------------------------------
    def test_render_states_verdicts_in_words_and_escapes(self):
        self.make_mirror("proj")
        self.wiki_mirror.sync_wiki("volmarr", "proj")
        page = render_wiki_mirror_page(
            [self.wiki_mirror.status_for("volmarr", "proj")])
        self.assertIn("Wiki mirrors", page)
        self.assertIn("volmarr/proj", page)
        self.assertIn(STATE_SYNCED, page)
        evil = render_wiki_mirror_page([])
        self.assertIn("No repositories", evil)


if __name__ == "__main__":
    unittest.main()
