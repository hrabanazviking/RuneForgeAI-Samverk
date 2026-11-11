"""S-275 acceptance battery: wiki transports.

Acceptance (roadmap S-275): Wiki transports -- the wiki
clones and pushes over both transports with repo-equal
permissions (Parts IV machinery, reused whole).

The centre is samverk/wiki_transports.py (the naming
law, the parent resolver, the audit and the render),
standing on the one seam this slice changes in the
Parts IV services themselves: in SmartHttpService /
TransportGate (samverk/git_http.py) and SshServeService
(samverk/ssh_serve.py), a `<repo>.wiki` name with no
exact repository row resolves to the parent repository's
wiki repository on disk (S-273's `<repo>.wiki`), and
every other step -- advertisement, pack legs, protocol
v2, the S-083 gate shapes, the S-089 receive gate, the
S-090 push event, the S-091 limits, the S-092 locks,
the S-094 transport audit -- is the machinery itself.
Permissions are repo-equal through S-054 on the parent:
a private repo's wiki is repo_not_found on both doors
exactly as the repo is, push requires the repo's writer
law, deploy keys are judged against the parent. A wiki
that does not stand yet (no page written) answers
repo_not_found on every leg and is never created by a
transport attempt. No new taxonomy event -- 133 stand;
no migration -- schema 106 stands.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
import sqlite3
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.deploy_keys import DeployKeyStore
from samverk.git_auth import GitAuthenticator
from samverk.git_http import SmartHttpService, TransportError, TransportGate
from samverk.push_events import PushEventStore
from samverk.receive_gate import ReceiveGate
from samverk.repositories import RepositoryStore
from samverk.wiki_storage import WikiStore
from samverk.wiki_transports import (
    WikiTransportError, WikiTransports, audit_wiki_transports,
    is_wiki_repo_name, render_wiki_transports_page,
    resolve_wiki_parent, split_wiki_repo_name, wiki_repo_name)
from test_git_basic_auth import basic
from test_git_http_receive import make_full_harness
from test_git_http_upload import GIT_ENV, cross_thread_service, seed_commit
from test_ssh_key_resolution import fp_of, make_key_line
from test_ssh_upload_routing import WRAPPER, FakeRunner, make_world, serve

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


def git_in(path: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", f"--git-dir={path}", *args],
        capture_output=True, text=True, env={**os.environ, **GIT_ENV})
    if out.returncode != 0:
        raise AssertionError(out.stderr)
    return out.stdout.strip()


def client_env(home: Path) -> dict:
    env = dict(os.environ)
    env.update(GIT_ENV)
    env["HOME"] = str(home)
    return env


class WikiWorldTests(unittest.TestCase):
    """One world for the direct-service and gate tests."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.wiki = WikiStore(
            self.conn, self.repos, audit=self.audit, time_fn=self.clock)
        self.service = SmartHttpService(
            self.conn, self.root, self.accounts, self.repos)
        self.gate = TransportGate(
            self.repos, GitAuthenticator(self.conn, self.accounts))
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.pub_code = seed_commit(self.repos, "volmarr", "pub")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.priv_code = seed_commit(self.repos, "volmarr", "priv")
        self.repos.create_repository(
            self.owner.id, "volmarr", "empty", visibility="public")
        self.pub_home = self.wiki.write_page(
            self.owner, "volmarr", "pub", "Home", "# Home\n\nPublic.\n")
        self.priv_home = self.wiki.write_page(
            self.owner, "volmarr", "priv", "Secret", "# Secret\n\nShh.\n")

    # -- helpers -------------------------------------------------

    def _reason(self, fn, *a, **k):
        with self.assertRaises(TransportError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def wiki_path(self, repo="pub"):
        return self.root / "repos" / "volmarr" / f"{repo}.wiki"

    def wiki_tip(self, repo="pub"):
        return git_in(self.wiki_path(repo), "rev-parse", "refs/heads/main")

    def code_tip(self, repo="pub"):
        return git_in(self.repos.path_for("volmarr", repo),
                      "rev-parse", "refs/heads/main")

    # -- the naming law ------------------------------------------

    def test_naming_law_splits_and_round_trips(self):
        self.assertEqual(split_wiki_repo_name("pub.wiki"), "pub")
        self.assertEqual(split_wiki_repo_name("pub.wiki.git"), "pub")
        self.assertEqual(split_wiki_repo_name("my.repo.wiki"), "my.repo")
        self.assertIsNone(split_wiki_repo_name("pub"))
        self.assertIsNone(split_wiki_repo_name("pub.git"))
        self.assertIsNone(split_wiki_repo_name(".wiki"))
        self.assertIsNone(split_wiki_repo_name("pub.wiki/.."))
        self.assertIsNone(split_wiki_repo_name("bad name.wiki"))
        self.assertIsNone(split_wiki_repo_name(None))
        self.assertIsNone(split_wiki_repo_name(42))
        self.assertTrue(is_wiki_repo_name("pub.wiki"))
        self.assertFalse(is_wiki_repo_name("pub"))
        self.assertEqual(wiki_repo_name("pub"), "pub.wiki")
        self.assertEqual(wiki_repo_name("pub.git"), "pub.wiki")
        self.assertEqual(
            split_wiki_repo_name(wiki_repo_name("pub")), "pub")
        with self.assertRaises(WikiTransportError) as ctx:
            wiki_repo_name("bad name")
        self.assertEqual(ctx.exception.reason, "repo_name_invalid")

    def test_resolve_wiki_parent_and_exact_row_wins(self):
        parent = resolve_wiki_parent(self.repos, "volmarr", "pub.wiki")
        self.assertIsNotNone(parent)
        self.assertEqual(parent.full_name, "volmarr/pub")
        self.assertIsNone(
            resolve_wiki_parent(self.repos, "volmarr", "pub"))
        self.assertIsNone(
            resolve_wiki_parent(self.repos, "volmarr", "nope.wiki"))
        # A repository literally named data.wiki is a code
        # repository: the exact row wins, no wiki reading.
        self.repos.create_repository(
            self.owner.id, "volmarr", "data", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "data.wiki", visibility="public")
        self.assertIsNone(
            resolve_wiki_parent(self.repos, "volmarr", "data.wiki"))
        code = seed_commit(self.repos, "volmarr", "data.wiki")
        resp = self.service.advertise(
            None, "volmarr", "data.wiki", "git-upload-pack")
        self.assertIn(code.encode(), resp.body)

    # -- HTTP: advertisement --------------------------------------

    def test_http_advertise_serves_the_wiki_tip_not_the_code_tip(self):
        resp = self.service.advertise(
            None, "volmarr", "pub.wiki", "git-upload-pack")
        self.assertEqual(
            resp.content_type,
            "application/x-git-upload-pack-advertisement")
        self.assertIn(self.pub_home.commit_oid.encode(), resp.body)
        self.assertNotIn(self.pub_code.encode(), resp.body)
        # The .git spelling is the same name.
        resp2 = self.service.advertise(
            None, "volmarr", "pub.wiki.git", "git-upload-pack")
        self.assertIn(self.pub_home.commit_oid.encode(), resp2.body)

    def test_http_private_wiki_is_invisible_exactly_as_the_repo(self):
        for viewer in (None, self.stranger):
            self.assertEqual(
                self._reason(self.service.advertise, viewer,
                             "volmarr", "priv.wiki", "git-upload-pack"),
                "repo_not_found")
            self.assertEqual(
                self._reason(self.service.advertise, viewer,
                             "volmarr", "priv", "git-upload-pack"),
                "repo_not_found")
        # The owner reads the private wiki's tip.
        resp = self.service.advertise(
            self.owner, "volmarr", "priv.wiki", "git-upload-pack")
        self.assertIn(self.priv_home.commit_oid.encode(), resp.body)

    def test_http_missing_and_unborn_wiki_answer_repo_not_found(self):
        self.assertEqual(
            self._reason(self.service.advertise, None,
                         "volmarr", "nope.wiki", "git-upload-pack"),
            "repo_not_found")
        # A public repo whose wiki has no page yet: same answer,
        # and the attempt created nothing on disk.
        self.assertFalse(self.wiki_path("empty").exists())
        self.assertEqual(
            self._reason(self.service.advertise, None,
                         "volmarr", "empty.wiki", "git-upload-pack"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.service.advertise, self.owner,
                         "volmarr", "empty.wiki", "git-receive-pack"),
            "repo_not_found")
        self.assertFalse(self.wiki_path("empty").exists())

    def test_http_receive_advertise_requires_the_writer_law(self):
        self.assertEqual(
            self._reason(self.service.advertise, None,
                         "volmarr", "pub.wiki", "git-receive-pack"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.service.advertise, self.reader,
                         "volmarr", "pub.wiki", "git-receive-pack"),
            "permission_denied")
        # A stranger at a private wiki hears nothing at all.
        self.assertEqual(
            self._reason(self.service.advertise, self.stranger,
                         "volmarr", "priv.wiki", "git-receive-pack"),
            "repo_not_found")
        resp = self.service.advertise(
            self.owner, "volmarr", "pub.wiki", "git-receive-pack")
        self.assertIn(self.pub_home.commit_oid.encode(), resp.body)
        # And the read legs refuse a bad service name unchanged.
        self.assertEqual(
            self._reason(self.service.advertise, None,
                         "volmarr", "pub.wiki", "git-teleport-pack"),
            "service_invalid")

    # -- HTTP: the S-083 gate shapes, judged on the parent --------

    def _shape(self, decision):
        return (decision.allowed, decision.status,
                decision.reason, decision.challenge)

    def test_gate_shapes_for_wiki_names_match_the_parent(self):
        anon_pub = self.gate.decide(
            "volmarr", "pub.wiki", "git-upload-pack", None)
        self.assertEqual(self._shape(anon_pub), (True, 200, "ok", False))
        self.assertIsNone(anon_pub.viewer)
        priv = self.gate.decide(
            "volmarr", "priv.wiki", "git-upload-pack", None)
        missing = self.gate.decide(
            "volmarr", "nope.wiki", "git-upload-pack", None)
        self.assertEqual(self._shape(priv), self._shape(missing))
        self.assertEqual(
            self._shape(priv), (False, 401, "credentials_needed", True))
        bad = basic("volmarr", "wrong horse battery")
        self.assertEqual(
            self._shape(self.gate.decide(
                "volmarr", "priv.wiki", "git-upload-pack", bad)),
            self._shape(self.gate.decide(
                "volmarr", "nope.wiki", "git-upload-pack", bad)))
        self.assertEqual(
            self._shape(self.gate.decide(
                "volmarr", "priv.wiki", "git-upload-pack", bad)),
            (False, 404, "repo_not_found", False))
        owner_push = self.gate.decide(
            "volmarr", "priv.wiki", "git-receive-pack",
            basic("volmarr", PW))
        self.assertTrue(owner_push.allowed)
        self.assertEqual(owner_push.viewer.username, "volmarr")
        reader_push = self.gate.decide(
            "volmarr", "pub.wiki", "git-receive-pack",
            basic("yrsa", PW))
        self.assertEqual(
            self._shape(reader_push),
            (False, 403, "permission_denied", False))

    # -- HTTP: stock git end to end --------------------------------

    def _harness(self, viewer, **service_kw):
        service = cross_thread_service(self.root)
        if service_kw:
            service = SmartHttpService(
                service._conn, self.root, service._accounts,
                service._repos, **service_kw)
        server = make_full_harness(service, viewer)
        self.addCleanup(server.shutdown)
        return server

    def _clone_http(self, server, name, dest, expect=0):
        port = server.server_address[1]
        out = subprocess.run(
            ["git", "clone",
             f"http://127.0.0.1:{port}/volmarr/{name}", str(dest)],
            capture_output=True, env=client_env(self.root))
        self.assertEqual(out.returncode, expect, out.stderr.decode())
        return out

    def test_stock_git_clones_public_wiki_anonymously(self):
        server = self._harness(None)
        dest = self.root / "clone-pub-wiki"
        self._clone_http(server, "pub.wiki.git", dest)
        self.assertEqual(
            (dest / "Home.md").read_text(), "# Home\n\nPublic.\n")
        head = subprocess.run(
            ["git", "-C", str(dest), "rev-parse", "HEAD"],
            capture_output=True, text=True, env=client_env(self.root))
        self.assertEqual(head.stdout.strip(), self.pub_home.commit_oid)
        # The code repository is a different history entirely.
        self.assertNotEqual(head.stdout.strip(), self.pub_code)

    def test_stock_git_clone_private_wiki_owner_only(self):
        server = self._harness(self.owner)
        dest = self.root / "clone-priv-wiki"
        self._clone_http(server, "priv.wiki.git", dest)
        self.assertEqual(
            (dest / "Secret.md").read_text(), "# Secret\n\nShh.\n")
        stranger_server = self._harness(self.stranger)
        out = self._clone_http(
            stranger_server, "priv.wiki.git",
            self.root / "clone-priv-denied", expect=128)
        self.assertFalse((self.root / "clone-priv-denied").exists()
                         and list((self.root / "clone-priv-denied")
                                  .glob("*.md")))

    def test_stock_git_pushes_a_new_page_to_the_wiki_over_http(self):
        # The witnesses ride the cross-thread connection: the
        # harness serves on its own thread and sqlite connections
        # are thread-bound (the codebase's own batteries wire it
        # the same way; a main-thread store recording from the
        # server thread would raise and be swallowed by the
        # transport's never-veto guard).
        base = cross_thread_service(self.root)
        events = PushEventStore(base._conn, base._repos)
        server = make_full_harness(
            SmartHttpService(base._conn, self.root, base._accounts,
                             base._repos, push_events=events,
                             audit=AuditLog(base._conn)),
            self.owner)
        self.addCleanup(server.shutdown)
        dest = self.root / "push-wiki"
        self._clone_http(server, "pub.wiki.git", dest)
        (dest / "Guide.md").write_text("# Guide\n\nNew page.\n")
        env = client_env(self.root)
        for args in (["add", "Guide.md"],
                     ["commit", "-m", "Add the guide"],
                     ["push", "origin", "main"]):
            out = subprocess.run(
                ["git", "-C", str(dest), *args],
                capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        # The wiki moved; S-273 reads the pushed page; code did not.
        pages = self.wiki.list_pages(self.owner, "volmarr", "pub")
        self.assertEqual([p.name for p in pages], ["Guide", "Home"])
        self.assertEqual(
            self.wiki.read_page(
                None, "volmarr", "pub", "Guide").content,
            "# Guide\n\nNew page.\n")
        self.assertEqual(self.code_tip("pub"), self.pub_code)
        # The machinery witnessed the push on the parent repo.
        landed = events.list_for_repo("volmarr", "pub")
        self.assertEqual(len(landed), 1)
        self.assertEqual(landed[0].transport, "http")
        self.assertEqual(landed[0].refs, ("refs/heads/main",))
        rows = self.conn.execute(
            "SELECT target_id FROM audit_log WHERE action = 'repo.push'"
        ).fetchall()
        self.assertEqual([r[0] for r in rows], ["volmarr/pub"])

    def test_http_push_by_a_mere_reader_moves_nothing(self):
        server = self._harness(self.reader)
        dest = self.root / "reader-clone"
        self._clone_http(server, "pub.wiki.git", dest)
        (dest / "Sneak.md").write_text("# Sneak\n")
        env = client_env(self.root)
        subprocess.run(["git", "-C", str(dest), "add", "Sneak.md"],
                       capture_output=True, env=env, check=True)
        subprocess.run(["git", "-C", str(dest), "commit", "-m", "sneak"],
                       capture_output=True, env=env, check=True)
        out = subprocess.run(
            ["git", "-C", str(dest), "push", "origin", "main"],
            capture_output=True, env=env)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.wiki_tip("pub"), self.pub_home.commit_oid)
        self.assertEqual(
            [p.name for p in self.wiki.list_pages(
                self.owner, "volmarr", "pub")],
            ["Home"])

    def test_http_wiki_push_meets_the_receive_gate(self):
        gate = ReceiveGate()
        gate.register_protection("stop", lambda ctx: "frozen by the operator")
        service = SmartHttpService(
            self.conn, self.root, self.accounts, self.repos,
            receive_gate=gate)
        server = make_full_harness(
            _cross(self.root, receive_gate=gate), self.owner)
        self.addCleanup(server.shutdown)
        dest = self.root / "gated-clone"
        self._clone_http(server, "pub.wiki.git", dest)
        (dest / "Late.md").write_text("# Late\n")
        env = client_env(self.root)
        subprocess.run(["git", "-C", str(dest), "add", "Late.md"],
                       capture_output=True, env=env, check=True)
        subprocess.run(["git", "-C", str(dest), "commit", "-m", "late"],
                       capture_output=True, env=env, check=True)
        out = subprocess.run(
            ["git", "-C", str(dest), "push", "origin", "main"],
            capture_output=True, env=env)
        self.assertNotEqual(out.returncode, 0)
        self.assertEqual(self.wiki_tip("pub"), self.pub_home.commit_oid)
        # Directly, the refusal reason is the gate's own.
        from test_git_http_receive import push_body
        with self.assertRaises(TransportError) as ctx:
            service.receive_pack(
                self.owner, "volmarr", "pub.wiki",
                push_body(self.pub_home.commit_oid,
                          self.pub_home.commit_oid))
        self.assertEqual(ctx.exception.reason, "push_refused")

    # -- the audit + render face -----------------------------------

    def test_audit_reproves_and_writes_nothing(self):
        before = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        audit = audit_wiki_transports(
            self.repos, None, "volmarr", "pub.wiki")
        self.assertEqual(audit.full_name, "volmarr/pub")
        self.assertEqual(audit.wiki_name, "pub.wiki")
        self.assertEqual(audit.wiki_path, str(self.wiki_path("pub")))
        self.assertTrue(audit.wiki_standing)
        self.assertEqual(audit.default_branch, "main")
        self.assertEqual(audit.transports, ("http", "ssh"))
        unborn = audit_wiki_transports(
            self.repos, None, "volmarr", "empty.wiki")
        self.assertFalse(unborn.wiki_standing)
        self.assertFalse(self.wiki_path("empty").exists())
        after = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(before, after)
        for viewer, name in ((None, "priv.wiki"),
                             (self.stranger, "priv.wiki"),
                             (None, "pub"),
                             (None, "nope.wiki")):
            with self.assertRaises(WikiTransportError) as ctx:
                audit_wiki_transports(self.repos, viewer, "volmarr", name)
            self.assertEqual(ctx.exception.reason, "repo_not_found")
        seam = WikiTransports(self.conn, self.repos, audit=self.audit)
        self.assertEqual(
            seam.parent_for("volmarr", "pub.wiki").full_name,
            "volmarr/pub")
        self.assertEqual(
            seam.audit(None, "volmarr", "pub.wiki").wiki_name, "pub.wiki")

    def test_render_names_both_transports_and_the_unborn_state(self):
        html = render_wiki_transports_page(audit_wiki_transports(
            self.repos, None, "volmarr", "pub.wiki"))
        self.assertIn("/volmarr/pub.wiki.git", html)
        self.assertIn("git@samverk:volmarr/pub.wiki.git", html)
        self.assertIn("git-upload-pack", html)
        unborn = render_wiki_transports_page(audit_wiki_transports(
            self.repos, None, "volmarr", "empty.wiki"))
        self.assertIn("no pages yet", unborn)
        self.assertNotIn("git@samverk", unborn)

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 113)
        from samverk import taxonomy
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)


def _cross(root: Path, **kw) -> SmartHttpService:
    """cross_thread_service with the optional machinery wired."""
    base = cross_thread_service(root)
    if not kw:
        return base
    return SmartHttpService(
        base._conn, root, base._accounts, base._repos, **kw)


class SshWikiTests(unittest.TestCase):
    """The SSH door, through SshServeService itself."""

    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)
        self.wiki = WikiStore(self.w["conn"], self.w["repos"])
        self.owner = self.w["owner"]
        # "open" is public in make_world; "samverk" is its
        # private-by-default sibling. Both get a wiki page.
        self.open_home = self.wiki.write_page(
            self.owner, "volmarr", "open", "Home", "# Open wiki\n")
        self.priv_home = self.wiki.write_page(
            self.owner, "volmarr", "samverk", "Home", "# Private wiki\n")

    def wiki_path(self, repo):
        return self.w["root"] / "repos" / "volmarr" / f"{repo}.wiki"

    def test_ssh_upload_pack_runs_on_the_wiki_path(self):
        rc, out, _ = serve(
            self.w, self.w["owner_fp"],
            "git-upload-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 0)
        self.assertEqual(out, b"PACK-OK")
        (path, program, _proto), = self.runner.calls
        self.assertEqual(program, "upload-pack")
        self.assertEqual(path, self.wiki_path("open"))
        # The .git spelling resolves identically.
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-upload-pack 'volmarr/open.wiki.git'")
        self.assertEqual(rc, 0)
        self.assertEqual(self.runner.calls[-1][0], self.wiki_path("open"))

    def test_ssh_receive_pack_runs_on_the_wiki_path_for_a_writer(self):
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 0)
        (path, program, _proto), = self.runner.calls
        self.assertEqual(program, "receive-pack")
        self.assertEqual(path, self.wiki_path("open"))

    def test_ssh_private_wiki_is_invisible_to_strangers(self):
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/samverk.wiki'")
        self.assertEqual(rc, 128)
        self.assertEqual(self.runner.calls, [])
        rc2, _, err2 = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/nope.wiki'")
        self.assertEqual(rc2, 128)
        self.assertEqual(err, err2)  # existence never leaks
        # The owner reads the private wiki fine.
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-upload-pack 'volmarr/samverk.wiki'")
        self.assertEqual(rc, 0)
        self.assertEqual(
            self.runner.calls[-1][0], self.wiki_path("samverk"))

    def test_ssh_reader_cannot_push_a_public_wiki(self):
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 128)
        self.assertIn(b"write permission", err)
        self.assertEqual(self.runner.calls, [])
        # ...but may clone it.
        rc, _, _ = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 0)

    def test_ssh_unborn_wiki_refused_and_never_created(self):
        self.w["repos"].create_repository(
            self.owner.id, "volmarr", "fresh", visibility="public")
        rc, _, err = serve(
            self.w, self.w["owner_fp"],
            "git-upload-pack 'volmarr/fresh.wiki'")
        self.assertEqual(rc, 128)
        self.assertEqual(self.runner.calls, [])
        self.assertFalse(self.wiki_path("fresh").exists())
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-receive-pack 'volmarr/fresh.wiki'")
        self.assertEqual(rc, 128)
        self.assertFalse(self.wiki_path("fresh").exists())

    def test_ssh_wiki_push_meets_the_receive_gate(self):
        gate = ReceiveGate()
        gate.register_protection("stop", lambda ctx: "frozen by the operator")
        self.w["service"]._receive_gate = gate
        rc, _, err = serve(
            self.w, self.w["owner_fp"],
            "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 128)
        self.assertIn(b"frozen by the operator", err)
        self.assertEqual(self.runner.calls, [])

    def test_ssh_deploy_keys_are_judged_on_the_parent(self):
        deploy = DeployKeyStore(self.w["conn"], self.w["accounts"])
        ro_line = make_key_line(b"\x0c" * 32, "wiki-ro")
        deploy.add_key(
            self.owner.id, "volmarr", "open", "Wiki ro", ro_line)
        rw_line = make_key_line(b"\x0d" * 32, "wiki-rw")
        deploy.add_key(
            self.owner.id, "volmarr", "open", "Wiki rw", rw_line,
            can_write=True)
        rc, _, _ = serve(
            self.w, fp_of(ro_line), "git-upload-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 0)
        self.assertEqual(self.runner.calls[-1][0], self.wiki_path("open"))
        rc, _, err = serve(
            self.w, fp_of(ro_line), "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 128)
        self.assertIn(b"read-only", err)
        rc, _, _ = serve(
            self.w, fp_of(rw_line), "git-receive-pack 'volmarr/open.wiki'")
        self.assertEqual(rc, 0)
        self.assertEqual(self.runner.calls[-1][0], self.wiki_path("open"))
        # A deploy key bound elsewhere reaches no wiki at all.
        rc, _, _ = serve(
            self.w, fp_of(ro_line),
            "git-upload-pack 'volmarr/samverk.wiki'")
        self.assertEqual(rc, 128)

    def test_stock_git_clones_and_pushes_wiki_through_the_ssh_door(self):
        w = make_world(self)  # the wrapper builds its own service
        wiki = WikiStore(w["conn"], w["repos"])
        home = wiki.write_page(
            w["owner"], "volmarr", "samverk", "Home", "# Home\n")
        root = w["root"]
        wrapper = root / "fake-ssh.py"
        wrapper.write_text(WRAPPER.format(
            repo_root=str(Path(__file__).resolve().parent.parent),
            root=str(root), fp=w["owner_fp"]))
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IEXEC)
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["GIT_SSH_COMMAND"] = str(wrapper)
        dest = root / "ssh-wiki-clone"
        out = subprocess.run(
            ["git", "clone", "git@localhost:volmarr/samverk.wiki.git",
             str(dest)],
            capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual((dest / "Home.md").read_text(), "# Home\n")
        (dest / "Next.md").write_text("# Next\n")
        for args in (["add", "Next.md"], ["commit", "-m", "next"],
                     ["push", "origin", "main"]):
            out = subprocess.run(
                ["git", "-C", str(dest), *args],
                capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        pages = wiki.list_pages(w["owner"], "volmarr", "samverk")
        self.assertEqual([p.name for p in pages], ["Home", "Next"])
        self.assertNotEqual(
            git_in(wiki_path_for(w), "rev-parse", "refs/heads/main"),
            home.commit_oid)


def wiki_path_for(world):
    return world["root"] / "repos" / "volmarr" / "samverk.wiki"


if __name__ == "__main__":
    unittest.main()
