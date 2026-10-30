"""S-087 acceptance battery: SSH receive-pack routing.

Acceptance (roadmap S-087): `git-receive-pack '<owner>/<repo>'`
under write permission, same seams as upload; a push audit
event is emitted for accepted pushes — and a stock git client
pushes through the serve door end to end.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk.audit import verify_chain
from test_git_http_upload import GIT_ENV, git, seed_commit
from test_ssh_upload_routing import WRAPPER, FakeRunner, make_world, serve


class ReceiveRoutingTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)

    def test_owner_receive_runs_receive_pack(self):
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-receive-pack 'volmarr/samverk.git'")
        self.assertEqual(rc, 0)
        (path, program, _), = self.runner.calls
        self.assertEqual(program, "receive-pack")

    def test_reader_cannot_push_to_a_readable_repo(self):
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-receive-pack 'volmarr/open'")
        self.assertEqual(rc, 128)
        self.assertIn(b"write permission", err)
        self.assertEqual(self.runner.calls, [])

    def test_stranger_push_to_private_repo_sees_nothing(self):
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 128)
        self.assertIn(b"not found or access denied", err.lower())
        self.assertEqual(self.runner.calls, [])

    def test_accepted_push_appends_repo_push_event(self):
        serve(self.w, self.w["owner_fp"],
              "git-receive-pack 'volmarr/samverk'")
        rows = self.w["conn"].execute(
            "SELECT actor_kind, actor_id, target_id, detail"
            " FROM audit_log WHERE action = 'repo.push'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_kind"], "user")
        self.assertEqual(rows[0]["actor_id"], self.w["owner"].id)
        self.assertEqual(rows[0]["target_id"], "volmarr/samverk")
        self.assertIn('"transport":"ssh"', rows[0]["detail"])
        ok, bad, _ = verify_chain(self.w["conn"])
        self.assertTrue(ok, bad)

    def test_failed_push_appends_nothing(self):
        self.runner.rc = 1
        rc, _, _ = serve(
            self.w, self.w["owner_fp"],
            "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 1)
        rows = self.w["conn"].execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.push'").fetchone()
        self.assertEqual(rows["n"], 0)


class StockGitPushInteropTests(unittest.TestCase):
    def test_stock_git_pushes_through_the_serve_door(self):
        w = make_world(self)
        first = seed_commit(w["repos"], "volmarr", "samverk")
        root = w["root"]
        wrapper = root / "fake-ssh.py"
        wrapper.write_text(WRAPPER.format(
            repo_root=str(Path(__file__).resolve().parent.parent),
            root=str(root), fp=w["owner_fp"]))
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["GIT_SSH_COMMAND"] = str(wrapper)

        work = root / "work"
        out = subprocess.run(
            ["git", "clone", "git@localhost:volmarr/samverk.git",
             str(work)], capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        (work / "second.txt").write_bytes(b"pushed over ssh\n")
        for args in (["add", "second.txt"],
                     ["commit", "-m", "second"],
                     ["push", "origin", "main"]):
            out = subprocess.run(
                ["git", "-C", str(work), *args],
                capture_output=True, env=env)
            self.assertEqual(
                out.returncode, 0,
                f"{args}: {out.stderr.decode()}")
        bare = w["repos"].path_for("volmarr", "samverk")
        head = git(bare, "rev-parse", "refs/heads/main")
        self.assertNotEqual(head, first)
        self.assertEqual(
            git(bare, "show", "refs/heads/main:second.txt"),
            "pushed over ssh")
        rows = w["conn"].execute(
            "SELECT COUNT(*) AS n FROM audit_log"
            " WHERE action = 'repo.push'").fetchone()
        self.assertGreaterEqual(rows["n"], 1)


if __name__ == "__main__":
    unittest.main()
