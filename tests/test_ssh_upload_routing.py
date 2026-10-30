"""S-086 acceptance battery: SSH upload-pack routing.

Acceptance (roadmap S-086 + study 02): `git-upload-pack
'<owner>/<repo>'` resolved under S-013 law and read permission —
the original command parsed strictly (never a shell), private
repos indistinguishable from missing ones, and a stock git
client cloning through the serve door with a stand-in ssh
program (real sshd is S-095's cell).

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import os
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
from samverk.repositories import RepositoryStore
from samverk.ssh_auth import SshKeyResolver
from samverk.ssh_keys import SshKeyStore
from samverk.ssh_serve import (
    REFUSAL_EXIT,
    SshServeError,
    SshServeService,
    parse_original_command,
)
from test_git_http_upload import GIT_ENV, seed_commit
from test_ssh_key_resolution import fp_of, make_key_line

GOOD_PW = "a long enough passphrase"


class FakeRunner:
    def __init__(self, rc: int = 0):
        self.rc = rc
        self.calls = []

    def __call__(self, path, program, *, stdin, stdout, stderr,
                 protocol_version=None):
        self.calls.append((path, program, protocol_version))
        stdout.write(b"PACK-OK")
        return self.rc


def make_world(test: unittest.TestCase, runner=None):
    td = tempfile.TemporaryDirectory()
    test.addCleanup(td.cleanup)
    test.addCleanup(lambda: None)
    root = Path(td.name)
    conn = db.init_db(root / "samverk.db")
    test.addCleanup(conn.close)
    audit = AuditLog(conn)
    accounts = AccountStore(conn, audit=audit)
    owner = accounts.register("volmarr", GOOD_PW)
    other = accounts.register("astrid", GOOD_PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    repos.create_repository(owner.id, "volmarr", "samverk")
    repos.create_repository(
        owner.id, "volmarr", "open", visibility="public")
    keys = SshKeyStore(conn, accounts, audit=audit,
                       reauth_verifier=lambda uid: True)
    line = make_key_line()
    keys.add_key(owner.id, "laptop", line)
    other_line = make_key_line(b"\x08" * 32, "astrid")
    keys.add_key(other.id, "laptop", other_line)
    resolver = SshKeyResolver(conn, accounts)
    service = SshServeService(
        conn, root, accounts, repos, audit=audit,
        pack_runner=runner if runner is not None else FakeRunner())
    world = {
        "root": root, "conn": conn, "accounts": accounts,
        "repos": repos, "owner": owner, "other": other,
        "resolver": resolver, "service": service,
        "owner_fp": fp_of(line), "other_fp": fp_of(other_line),
    }
    return world


def serve(world, fp, command, **kw):
    principal = world["resolver"].resolve(fp) if fp else None
    out, err = io.BytesIO(), io.BytesIO()
    rc = world["service"].serve(
        principal, command, stdin=io.BytesIO(), stdout=out,
        stderr=err, **kw)
    return rc, out.getvalue(), err.getvalue()


class ParserTests(unittest.TestCase):
    def test_valid_commands_parse(self):
        self.assertEqual(
            parse_original_command("git-upload-pack 'volmarr/samverk.git'"),
            ("git-upload-pack", "volmarr", "samverk"))
        self.assertEqual(
            parse_original_command("git-receive-pack 'a/b'"),
            ("git-receive-pack", "a", "b"))

    def test_anything_else_is_refused(self):
        bad = [
            "", None, 42,
            "git-upload-pack volmarr/samverk",            # unquoted
            "git-upload-pack 'volmarr/samverk'; id",      # injection
            "git-upload-pack 'volmarr/samverk' extra",
            "git-upload-pack '/etc/passwd'",              # absolute
            "git-upload-pack '../samverk'",               # traversal
            "git-upload-pack 'volmarr'",                  # one part
            "git-upload-pack 'a/b/c'",                    # three parts
            "git-upload-pack '-oProxyCommand=id/x'",      # dash host trick
            "git-shell 'volmarr/samverk'",                # not a service
            "git-upload-pack 'volmarr/sam verk'",         # space in name
            "git-upload-pack 'volmarr/samverk'\n",        # trailing newline
            "git-upload-pack 'volmarr\\samverk'",         # backslash
        ]
        for command in bad:
            with self.assertRaises(SshServeError, msg=repr(command)):
                parse_original_command(command)


class UploadRoutingTests(unittest.TestCase):
    def setUp(self):
        self.runner = FakeRunner()
        self.w = make_world(self, runner=self.runner)

    def test_owner_upload_runs_upload_pack_on_resolved_path(self):
        rc, out, _ = serve(
            self.w, self.w["owner_fp"],
            "git-upload-pack 'volmarr/samverk.git'")
        self.assertEqual(rc, 0)
        self.assertEqual(out, b"PACK-OK")
        (path, program, proto), = self.runner.calls
        self.assertEqual(program, "upload-pack")
        self.assertEqual(
            path, self.w["repos"].path_for("volmarr", "samverk"))
        self.assertIsNone(proto)

    def test_protocol_v2_is_passed_only_when_exact(self):
        serve(self.w, self.w["owner_fp"],
              "git-upload-pack 'volmarr/samverk'",
              git_protocol="version=2")
        self.assertEqual(self.runner.calls[-1][2], 2)
        serve(self.w, self.w["owner_fp"],
              "git-upload-pack 'volmarr/samverk'",
              git_protocol="version=2; agent=x")
        self.assertIsNone(self.runner.calls[-1][2])

    def test_private_repo_is_invisible_to_strangers(self):
        rc, _, err = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/samverk'")
        self.assertEqual(rc, REFUSAL_EXIT)
        self.assertEqual(self.runner.calls, [])
        rc2, _, err2 = serve(
            self.w, self.w["other_fp"],
            "git-upload-pack 'volmarr/nonexistent'")
        self.assertEqual(rc2, REFUSAL_EXIT)
        self.assertEqual(err, err2)  # existence never leaks

    def test_public_repo_reads_for_any_key_holder(self):
        rc, _, _ = serve(
            self.w, self.w["other_fp"], "git-upload-pack 'volmarr/open'")
        self.assertEqual(rc, 0)

    def test_no_principal_no_service(self):
        rc, _, err = serve(self.w, None, "git-upload-pack 'volmarr/open'")
        self.assertEqual(rc, REFUSAL_EXIT)
        self.assertIn(b"Authentication required", err)
        self.assertEqual(self.runner.calls, [])

    def test_archive_is_named_not_served_yet(self):
        rc, _, err = serve(
            self.w, self.w["owner_fp"],
            "git-upload-archive 'volmarr/samverk'")
        self.assertEqual(rc, REFUSAL_EXIT)
        self.assertIn(b"not served yet", err)


WRAPPER = '''#!/usr/bin/env python3
import sqlite3, sys
from pathlib import Path
sys.path.insert(0, {repo_root!r})
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.repositories import RepositoryStore
from samverk.ssh_auth import SshKeyResolver
from samverk.ssh_serve import SshServeService

root = Path({root!r})
conn = sqlite3.connect(str(root / "samverk.db"), timeout=5.0)
conn.row_factory = sqlite3.Row
accounts = AccountStore(conn, audit=AuditLog(conn))
repos = RepositoryStore(conn, root, accounts, audit=AuditLog(conn))
principal = SshKeyResolver(conn, accounts).resolve({fp!r})
service = SshServeService(conn, root, accounts, repos,
                          audit=AuditLog(conn))
rc = service.serve(principal, sys.argv[-1], stdin=sys.stdin.buffer,
                   stdout=sys.stdout.buffer, stderr=sys.stderr.buffer,
                   git_protocol=None)
sys.exit(rc)
'''


class StockGitSshInteropTests(unittest.TestCase):
    def test_stock_git_clones_through_the_serve_door(self):
        w = make_world(self)
        seed_commit(w["repos"], "volmarr", "samverk")
        root = w["root"]
        wrapper = root / "fake-ssh.py"
        wrapper.write_text(WRAPPER.format(
            repo_root=str(Path(__file__).resolve().parent.parent),
            root=str(root), fp=w["owner_fp"]))
        wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
        env = dict(os.environ)
        env.update(GIT_ENV)
        env["GIT_SSH_COMMAND"] = str(wrapper)
        dest = root / "clone"
        out = subprocess.run(
            ["git", "clone", "git@localhost:volmarr/samverk.git",
             str(dest)],
            capture_output=True, env=env)
        self.assertEqual(out.returncode, 0, out.stderr.decode())
        self.assertEqual(
            (dest / "hello.txt").read_bytes(), b"hello\n")


if __name__ == "__main__":
    unittest.main()
