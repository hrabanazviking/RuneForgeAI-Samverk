"""S-088 acceptance battery: deploy-key transport rights.

Acceptance (roadmap S-088): deploy keys authenticate transport
for exactly one repo (S-031 proven on the wire) — a deploy
principal reads its bound repository, nothing else (not even a
public repository), a read-only deploy key's push is refused at
the gate, a read/write deploy key pushes and its pushes are
audited as the key, and stock git clones/pushes with deploy
principals end to end.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import stat
import subprocess
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk.deploy_keys import DeployKeyStore
from test_git_http_upload import GIT_ENV, git, seed_commit
from test_ssh_key_resolution import fp_of, make_key_line
from test_ssh_upload_routing import WRAPPER, FakeRunner, make_world, serve


class DeployRoutingTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)
        self.deploy = DeployKeyStore(
            self.w["conn"], self.w["accounts"])
        self.ro_line = make_key_line(b"\x0a" * 32, "ci-ro")
        self.deploy.add_key(
            self.w["owner"].id, "volmarr", "samverk", "CI ro",
            self.ro_line)
        self.rw_line = make_key_line(b"\x0b" * 32, "ci-rw")
        self.deploy.add_key(
            self.w["owner"].id, "volmarr", "samverk", "CI rw",
            self.rw_line, can_write=True)
        self.ro_fp = fp_of(self.ro_line)
        self.rw_fp = fp_of(self.rw_line)

    def test_deploy_principal_reads_its_bound_repo(self):
        rc, _, _ = serve(
            self.w, self.ro_fp, "git-upload-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)
        self.assertEqual(self.runner.calls[0][1], "upload-pack")

    def test_deploy_principal_reaches_no_other_repo(self):
        for target in ("volmarr/open", "astrid/samverk",
                       "volmarr/nonexistent"):
            rc, _, err = serve(
                self.w, self.ro_fp, f"git-upload-pack '{target}'")
            self.assertEqual(rc, 128, target)
        self.assertEqual(self.runner.calls, [])

    def test_read_only_deploy_key_cannot_push(self):
        rc, _, err = serve(
            self.w, self.ro_fp, "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 128)
        self.assertIn(b"read-only", err)
        self.assertEqual(self.runner.calls, [])

    def test_read_write_deploy_key_pushes_and_is_audited_as_key(self):
        rc, _, _ = serve(
            self.w, self.rw_fp, "git-receive-pack 'volmarr/samverk'")
        self.assertEqual(rc, 0)
        rows = self.w["conn"].execute(
            "SELECT actor_kind, target_id FROM audit_log"
            " WHERE action = 'repo.push'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["actor_kind"], "deploy_key")
        self.assertEqual(rows[0]["target_id"], "volmarr/samverk")

    def test_deploy_key_use_is_stamped(self):
        serve(self.w, self.ro_fp, "git-upload-pack 'volmarr/samverk'")
        key = self.deploy.list_keys("volmarr", "samverk")[0]
        self.assertIsNotNone(key.last_used_at)


def write_wrapper(w, fp) -> Path:
    root = w["root"]
    wrapper = root / f"fake-ssh-{fp[-4:]}.py"
    wrapper.write_text(WRAPPER.format(
        repo_root=str(Path(__file__).resolve().parent.parent),
        root=str(root), fp=fp))
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    return wrapper


class DeployInteropTests(unittest.TestCase):
    def setUp(self):
        self.w = make_world(self)
        self.first = seed_commit(self.w["repos"], "volmarr", "samverk")
        self.deploy = DeployKeyStore(
            self.w["conn"], self.w["accounts"])
        self.rw_line = make_key_line(b"\x0b" * 32, "ci-rw")
        self.deploy.add_key(
            self.w["owner"].id, "volmarr", "samverk", "CI rw",
            self.rw_line, can_write=True)
        self.ro_line = make_key_line(b"\x0a" * 32, "ci-ro")
        self.deploy.add_key(
            self.w["owner"].id, "volmarr", "samverk", "CI ro",
            self.ro_line)

    def _env(self, fp):
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["GIT_SSH_COMMAND"] = str(write_wrapper(self.w, fp))
        return env

    def test_rw_deploy_key_clones_and_pushes(self):
        env = self._env(fp_of(self.rw_line))
        work = self.w["root"] / "work"
        out = subprocess.run(
            ["git", "clone", "git@localhost:volmarr/samverk.git",
             str(work)], capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        (work / "deploy.txt").write_bytes(b"by deploy key\n")
        for args in (["add", "deploy.txt"], ["commit", "-m", "d"],
                     ["push", "origin", "main"]):
            out = subprocess.run(
                ["git", "-C", str(work), *args],
                capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        bare = self.w["repos"].path_for("volmarr", "samverk")
        self.assertEqual(
            git(bare, "show", "refs/heads/main:deploy.txt"),
            "by deploy key")

    def test_ro_deploy_key_clone_works_push_is_refused(self):
        env = self._env(fp_of(self.ro_line))
        work = self.w["root"] / "work-ro"
        out = subprocess.run(
            ["git", "clone", "git@localhost:volmarr/samverk.git",
             str(work)], capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        (work / "nope.txt").write_bytes(b"must not land\n")
        for args in (["add", "nope.txt"], ["commit", "-m", "x"]):
            out = subprocess.run(
                ["git", "-C", str(work), *args],
                capture_output=True, env=env)
            self.assertEqual(out.returncode, 0, out.stderr.decode())
        out = subprocess.run(
            ["git", "-C", str(work), "push", "origin", "main"],
            capture_output=True, env=env)
        self.assertNotEqual(out.returncode, 0)
        bare = self.w["repos"].path_for("volmarr", "samverk")
        self.assertEqual(
            git(bare, "rev-parse", "refs/heads/main"), self.first)


if __name__ == "__main__":
    unittest.main()
