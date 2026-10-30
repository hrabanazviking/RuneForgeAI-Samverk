"""S-014 acceptance battery: subprocess discipline.

Acceptance (roadmap S-014): git invoked without a shell, argument
allowlists, no user input in argv position 0 — *the injection
battery passes.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.proc import (
    ProcRefused,
    resolve_program,
    run_git,
    run_git_in,
    run_program,
)


class ProgramAllowlistTests(unittest.TestCase):
    def test_git_resolves_and_runs(self):
        self.assertTrue(resolve_program("git").is_file())
        done = run_program("git", ["--version"])
        self.assertEqual(done.returncode, 0)
        self.assertIn(b"git version", done.stdout)

    def test_argv0_is_never_user_input(self):
        for name in ("sh", "bash", "/bin/sh", "/usr/bin/git",
                     "../../bin/git", "git ", "", "python3"):
            with self.assertRaises(ProcRefused, msg=name):
                resolve_program(name)
            with self.assertRaises(ProcRefused, msg=name):
                run_program(name, ["--version"])


class GitAllowlistTests(unittest.TestCase):
    def test_unlisted_subcommands_do_not_exist(self):
        for args in (["clone", "https://example.invalid/x.git"],
                     ["config", "user.email", "a@b.c"],
                     ["fetch", "origin"], ["pull"], ["-c",
                     "core.fsmonitor=x", "status"], ["--git-dir=/tmp",
                     "status"], ["rebase", "main"]):
            with self.assertRaises(ProcRefused, msg=str(args)):
                run_git(args)

    def test_dangerous_flags_are_refused_in_any_position(self):
        for args in (["status", "--upload-pack=touch /tmp/x"],
                     ["log", "--git-dir=/elsewhere"],
                     ["log", "-c", "x=y"],
                     ["upload-pack", "--timeout=5", "--receive-pack=y"],
                     ["show", "--exec-path=/tmp"]):
            with self.assertRaises(ProcRefused, msg=str(args)) as caught:
                run_git(args)
            self.assertEqual(caught.exception.reason, "dangerous_flag")

    def test_nul_and_non_string_arguments_are_refused(self):
        with self.assertRaises(ProcRefused):
            run_git(["log", "a\x00b"])
        with self.assertRaises(ProcRefused):
            run_git(["log", 42])  # type: ignore[list-item]


class InjectionBatteryTests(unittest.TestCase):
    def test_shell_metacharacters_are_inert_bytes(self):
        """The acceptance in its literal form: classic shell
        injections arrive as single argv entries to a shell-less
        git, fail as nonsense revisions, and create nothing."""
        with tempfile.TemporaryDirectory() as td:
            marker = Path(td) / "pwned"
            injections = [
                f"; touch {marker}",
                f"$(touch {marker})",
                f"`touch {marker}`",
                f"HEAD && touch {marker}",
                f"HEAD | tee {marker}",
            ]
            for payload in injections:
                done = run_git(["rev-parse", payload])
                self.assertNotEqual(done.returncode, 0, msg=payload)
            self.assertFalse(marker.exists())

    def test_real_git_work_flows_through_the_law(self):
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r.git"
            done = run_git(["init", "--bare", str(repo)])
            self.assertEqual(done.returncode, 0, done.stderr)
            blob = run_git_in(
                repo, ["hash-object", "-w", "--stdin"],
                input_bytes=b"samverk\n")
            self.assertEqual(blob.returncode, 0, blob.stderr)
            sha = blob.stdout.decode().strip()
            read = run_git_in(repo, ["cat-file", "-p", sha])
            self.assertEqual(read.stdout, b"samverk\n")

    def test_hostile_environment_cannot_redirect_a_spawn(self):
        """GIT_DIR in the inherited environment is stripped: the
        spawn still operates on the repository it was given."""
        with tempfile.TemporaryDirectory() as td:
            repo = Path(td) / "r.git"
            self.assertEqual(
                run_git(["init", "--bare", str(repo)]).returncode, 0)
            old = os.environ.get("GIT_DIR")
            os.environ["GIT_DIR"] = "/nonexistent/evil.git"
            try:
                done = run_git_in(repo, ["rev-parse", "--git-dir"])
            finally:
                if old is None:
                    del os.environ["GIT_DIR"]
                else:
                    os.environ["GIT_DIR"] = old
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertEqual(
                done.stdout.decode().strip(), str(repo))


if __name__ == "__main__":
    unittest.main()
