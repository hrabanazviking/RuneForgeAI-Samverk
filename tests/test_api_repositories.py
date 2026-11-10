"""S-242 acceptance battery: repositories API.

Acceptance (roadmap S-242): Repositories API --
CRUD, forks, branches, contents read -- parity
with the web's capabilities, no API-only back
doors.

The centre is samverk/api_repositories.py: the
contract's repositories family delegating every
act to the web's own stores (S-049/S-050 creation
and metadata, S-055 forks, S-052 branches, Part
VIII protection, Part V contents, S-056 deletion),
judged through S-238's door and S-190's engine
alone, with refusals in S-240's one problem
format. The planted private repository (`priv`)
is the leak bait in the S-209 shape: a stranger's
answers over a world WITH it must equal the same
answers over a world where it was never created.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, subprocess, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_contract import PROBLEM_FIELDS, get_resource
from samverk.api_repositories import (
    MAX_CONTENT_BYTES, REPOSITORIES_API_PATH, RepositoriesAPI,
    RepositoriesAPIError, branch_to_dict, error_to_dict,
    render_repositories_api_page, repository_to_dict)
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.fine_grained_tokens import FineTokenStore
from samverk.protection_rules import ProtectionRuleStore
from samverk.repo_deletion import GRACE_SECONDS, RepoDeletion
from samverk.repositories import RepositoryStore

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def build_tree(repo, mapping):
    """mapping: name -> bytes (blob) or dict (subtree).
    Returns the tree oid."""
    lines = []
    for name in sorted(mapping):
        value = mapping[name]
        if isinstance(value, dict):
            oid = build_tree(repo, value)
            lines.append(f"040000 tree {oid}\t{name}")
        else:
            oid = git(repo, "hash-object", "-w", "--stdin", input_bytes=value)
            lines.append(f"100644 blob {oid}\t{name}")
    return git(repo, "mktree", input_bytes=("\n".join(lines) + "\n").encode())


def commit_tree(repo, tree, message, parent=None):
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


def make_world(root: Path, with_secret: bool = True) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    boss = accounts.register("boss", PW)
    with conn:
        conn.execute("UPDATE users SET is_admin = 1 WHERE id = ?", (boss.id,))
    boss = accounts.get_by_id(boss.id)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    api = RepositoriesAPI(conn, root, accounts, repos, audit=audit, time_fn=clock)
    w = SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger, boss=boss,
        repos=repos, api=api, root=root)
    pub = repos.create_repository(owner.id, "volmarr", "pub", visibility="public")
    path = repos.path_for("volmarr", "pub")
    tree1 = build_tree(path, {
        "hello.txt": b"hello world\n",
        "dir": {"note.txt": b"nested note\n"}})
    c1 = commit_tree(path, tree1, "first")
    git(path, "update-ref", "refs/heads/main", c1)
    tree2 = build_tree(path, {
        "hello.txt": b"dev hello\n",
        "dir": {"note.txt": b"nested note\n"}})
    c2 = commit_tree(path, tree2, "second", parent=c1)
    git(path, "update-ref", "refs/heads/dev", c2)
    w.pub, w.c1, w.c2 = pub, c1, c2
    repos.create_repository(owner.id, "volmarr", "int", visibility="internal")
    if with_secret:
        repos.create_repository(owner.id, "volmarr", "priv", visibility="private")
    classic = AccessTokenStore(conn, accounts, audit=audit, time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit, time_fn=clock)
    expiry = clock.now + 3600
    _, w.owner_read = classic.create_token(owner.id, "read", {"repo:read"}, expiry)
    _, w.owner_write = classic.create_token(owner.id, "write", {"repo:write"}, expiry)
    _, w.fine_pub = fine.create_token(
        owner.id, "volmarr", "pub", "fine pub",
        {"contents:read", "metadata:read"}, expiry)
    w.deletion = RepoDeletion(conn, root, accounts, repos, audit=audit, time_fn=clock)
    return w


class RepositoriesAPITests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def _error(self, fn, *args, **kwargs):
        with self.assertRaises(RepositoriesAPIError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception

    def _audits(self, action):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = ?",
            (action,)).fetchone()["n"]

    def _audit_total(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- pins ------------------------------------------------
    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.w.conn), 96)
        self.assertEqual(db.MIGRATIONS[-1][0], 96)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 85)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 131)
        self.assertEqual(REPOSITORIES_API_PATH, "/api/repositories")

    def test_contract_now_lands_the_family(self):
        for rid in ("root", "repositories", "repository",
                    "repository-branches", "repository-contents",
                    "repository-forks"):
            self.assertEqual(get_resource(rid).standing, "landed", rid)
            self.assertEqual(get_resource(rid).slice, "S-242", rid)
        repo = self.w.repos.get_repository("volmarr", "pub")
        self.assertEqual(
            tuple(repository_to_dict(repo).keys()),
            get_resource("repository").fields)
        self.assertEqual(
            tuple(branch_to_dict("main", "0" * 40, False).keys()),
            get_resource("repository-branches").fields)

    def test_error_dict_is_the_one_problem_format(self):
        exc = self._error(self.w.api.get_repository, None, "volmarr", "priv")
        rendered = error_to_dict(exc)
        self.assertEqual(tuple(rendered.keys()), PROBLEM_FIELDS)
        self.assertEqual(rendered["type"], "/api/v1/problems/repo_not_found")
        self.assertEqual(rendered["status"], 404)
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    # -- the root ----------------------------------------------
    def test_root_discovers_the_table_anonymously(self):
        data = self.w.api.root()
        self.assertEqual(data["base"], "/api/v1")
        self.assertEqual(data["version"], "v1")
        for rid in ("repositories", "repository", "repository-forks"):
            self.assertIn(rid, data["resources"])
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(
            json.loads(self.w.api.root_json()), data)

    def test_root_refuses_a_bad_credential_verbatim(self):
        exc = self._error(self.w.api.root, "Bearer svk_nope")
        self.assertEqual(exc.reason, "credentials_invalid")

    # -- the collection ------------------------------------------
    def test_list_filters_by_permission_before_counting(self):
        anon = self.w.api.list_repositories(None)
        self.assertEqual(
            [r["full_name"] for r in anon["repositories"]], ["volmarr/pub"])
        self.assertEqual(anon["total"], 1)
        self.assertTrue(anon["complete"])
        signed = self.w.api.list_repositories(basic("mallory", PW))
        self.assertEqual(
            sorted(r["full_name"] for r in signed["repositories"]),
            ["volmarr/int", "volmarr/pub"])  # internal: signed-in members
        own = self.w.api.list_repositories(basic("volmarr", PW))
        self.assertEqual(own["total"], 3)
        capped = self.w.api.list_repositories(basic("volmarr", PW), limit=2)
        self.assertEqual(capped["returned"], 2)
        self.assertFalse(capped["complete"])
        self.assertEqual(capped["limit"], 2)

    def test_list_leak_equivalence_for_a_stranger(self):
        with tempfile.TemporaryDirectory() as td:
            bare = make_world(Path(td), with_secret=False)
            try:
                mine = self.w.api.list_repositories(basic("mallory", PW))
                theirs = bare.api.list_repositories(basic("mallory", PW))
                # The S-209 equivalence, over the visible
                # facts: row ids and creation stamps are
                # the two worlds' own bookkeeping, not
                # facts about the hidden repository.
                def visible(payload):
                    return (
                        payload["total"], payload["returned"],
                        payload["complete"],
                        [(r["full_name"], r["visibility"],
                          r["description"], r["default_branch"])
                         for r in payload["repositories"]])
                self.assertEqual(visible(mine), visible(theirs))
            finally:
                bare.conn.close()

    def test_list_limit_is_refused_outside_the_bounds(self):
        for bad in (0, 501, "10", True):
            exc = self._error(self.w.api.list_repositories, None, limit=bad)
            self.assertEqual(exc.reason, "limit_invalid")

    # -- one repository: read --------------------------------------
    def test_get_repository_reads_and_hides_uniformly(self):
        data = self.w.api.get_repository(None, "volmarr", "pub")
        self.assertEqual(data["full_name"], "volmarr/pub")
        self.assertEqual(data["visibility"], "public")
        hidden = self._error(self.w.api.get_repository, None, "volmarr", "priv")
        missing = self._error(self.w.api.get_repository, None, "volmarr", "nope")
        self.assertEqual(hidden.reason, "repo_not_found")
        self.assertEqual(missing.reason, "repo_not_found")
        self.assertEqual(str(hidden), str(missing))
        own = self.w.api.get_repository(basic("volmarr", PW), "volmarr", "priv")
        self.assertEqual(own["visibility"], "private")

    def test_get_repository_with_tokens(self):
        data = self.w.api.get_repository("Bearer " + self.w.owner_read, "volmarr", "priv")
        self.assertEqual(data["name"], "priv")
        fine = self.w.api.get_repository("Bearer " + self.w.fine_pub, "volmarr", "pub")
        self.assertEqual(fine["name"], "pub")
        exc = self._error(
            self.w.api.get_repository, "Bearer " + self.w.fine_pub, "volmarr", "priv")
        self.assertEqual(exc.reason, "insufficient_scope")

    # -- one repository: create --------------------------------------
    def test_create_repository_through_the_web_store(self):
        before = self._audits("repo.create")
        data = self.w.api.create_repository(
            basic("yrsa", PW),
            {"name": "fresh", "description": "new repo", "visibility": "public"})
        self.assertEqual(data["full_name"], "yrsa/fresh")
        self.assertEqual(data["description"], "new repo")
        self.assertEqual(data["default_branch"], "main")
        self.assertIsNotNone(self.w.repos.get_repository("yrsa", "fresh"))
        self.assertTrue(self.w.repos.path_for("yrsa", "fresh").exists())
        self.assertEqual(self._audits("repo.create"), before + 1)

    def test_create_refusals(self):
        exc = self._error(self.w.api.create_repository, None, {"name": "x"})
        self.assertEqual(exc.reason, "authentication_required")
        exc = self._error(
            self.w.api.create_repository, "Bearer " + self.w.owner_read, {"name": "x"})
        self.assertEqual(exc.reason, "insufficient_scope")
        made = self.w.api.create_repository(
            "Bearer " + self.w.owner_write, {"name": "tokenmade"})
        self.assertEqual(made["full_name"], "volmarr/tokenmade")
        exc = self._error(
            self.w.api.create_repository, "Bearer " + self.w.fine_pub, {"name": "x"})
        self.assertEqual(exc.reason, "insufficient_scope")
        exc = self._error(
            self.w.api.create_repository, basic("volmarr", PW), {"name": "pub"})
        self.assertEqual(exc.reason, "repo_taken")
        self.assertEqual(error_to_dict(exc)["status"], 409)
        for payload in ("text", {"name": "x", "owner": "mallory"},
                        {"description": "no name"}):
            exc = self._error(
                self.w.api.create_repository, basic("volmarr", PW), payload)
            self.assertEqual(exc.reason, "payload_invalid", payload)
        exc = self._error(
            self.w.api.create_repository, basic("volmarr", PW),
            {"name": "x", "visibility": "sideways"})
        self.assertEqual(exc.reason, "visibility_invalid")

    # -- one repository: update ----------------------------------------
    def test_update_repository_through_the_web_store(self):
        data = self.w.api.update_repository(
            basic("volmarr", PW), "volmarr", "pub",
            {"description": "updated words", "visibility": "private"})
        self.assertEqual(data["description"], "updated words")
        self.assertEqual(data["visibility"], "private")
        self.assertGreaterEqual(self._audits("repo.settings.change"), 1)
        self.assertGreaterEqual(self._audits("repo.visibility.change"), 1)
        moved = self.w.api.update_repository(
            basic("volmarr", PW), "volmarr", "pub", {"default_branch": "dev"})
        self.assertEqual(moved["default_branch"], "dev")
        renamed = self.w.api.update_repository(
            basic("volmarr", PW), "volmarr", "pub", {"name": "pub2"})
        self.assertEqual(renamed["full_name"], "volmarr/pub2")
        self.assertIsNone(self.w.repos.get_repository("volmarr", "pub"))

    def test_update_refusals_keep_the_web_law(self):
        exc = self._error(
            self.w.api.update_repository, basic("yrsa", PW),
            "volmarr", "pub", {"description": "nope"})
        self.assertEqual(exc.reason, "repo_not_found")  # no admin rung
        exc = self._error(
            self.w.api.update_repository, basic("boss", PW),
            "volmarr", "pub", {"description": "nope"})
        self.assertEqual(exc.reason, "not_repo_owner")  # site admin != owner
        self.assertEqual(error_to_dict(exc)["status"], 403)
        exc = self._error(
            self.w.api.update_repository, "Bearer " + self.w.owner_read,
            "volmarr", "pub", {"description": "nope"})
        self.assertEqual(exc.reason, "insufficient_scope")
        for payload in ({}, {"bogus": 1}, "text"):
            exc = self._error(
                self.w.api.update_repository, basic("volmarr", PW),
                "volmarr", "pub", payload)
            self.assertEqual(exc.reason, "payload_invalid", payload)
        exc = self._error(
            self.w.api.update_repository, None, "volmarr", "pub",
            {"description": "nope"})
        self.assertEqual(exc.reason, "authentication_required")

    # -- one repository: delete ------------------------------------------
    def test_delete_requests_the_web_process_with_grace(self):
        data = self.w.api.delete_repository(basic("volmarr", PW), "volmarr", "int")
        self.assertEqual(data["deletion"], "pending")
        self.assertEqual(data["repository"]["full_name"], "volmarr/int")
        self.assertEqual(data["scheduled_at"] - data["requested_at"], GRACE_SECONDS)
        self.assertEqual(data["grace_seconds"], GRACE_SECONDS)
        # Nothing is destroyed yet: the row and the disk stand.
        self.assertIsNotNone(self.w.repos.get_repository("volmarr", "int"))
        self.assertTrue(self.w.repos.path_for("volmarr", "int").exists())
        self.assertTrue(self.w.deletion.is_pending("volmarr", "int"))
        exc = self._error(
            self.w.api.delete_repository, basic("volmarr", PW), "volmarr", "int")
        self.assertEqual(exc.reason, "already_pending")
        self.assertEqual(error_to_dict(exc)["status"], 409)

    def test_delete_refusals(self):
        exc = self._error(
            self.w.api.delete_repository, basic("mallory", PW), "volmarr", "priv")
        self.assertEqual(exc.reason, "repo_not_found")
        exc = self._error(
            self.w.api.delete_repository, basic("boss", PW), "volmarr", "pub")
        self.assertEqual(exc.reason, "not_repo_owner")
        exc = self._error(
            self.w.api.delete_repository, None, "volmarr", "pub")
        self.assertEqual(exc.reason, "authentication_required")

    # -- branches -------------------------------------------------------
    def test_branches_carry_tips_and_protection(self):
        data = self.w.api.list_branches(None, "volmarr", "pub")
        self.assertEqual(data["repository"], "volmarr/pub")
        by_name = {b["name"]: b for b in data["branches"]}
        self.assertEqual(by_name["main"]["tip"], self.w.c1)
        self.assertEqual(by_name["dev"]["tip"], self.w.c2)
        self.assertFalse(by_name["main"]["protected"])
        store = ProtectionRuleStore(
            self.w.conn, self.w.repos, self.w.accounts, audit=self.w.audit)
        store.create_rule(self.w.owner, "volmarr", "pub", "main")
        data = self.w.api.list_branches(None, "volmarr", "pub")
        by_name = {b["name"]: b for b in data["branches"]}
        self.assertTrue(by_name["main"]["protected"])
        self.assertFalse(by_name["dev"]["protected"])
        exc = self._error(self.w.api.list_branches, None, "volmarr", "priv")
        self.assertEqual(exc.reason, "repo_not_found")

    # -- contents ---------------------------------------------------------
    def test_contents_tree_and_blob_reads(self):
        root = self.w.api.get_contents(None, "volmarr", "pub")
        self.assertEqual(root["kind"], "tree")
        self.assertEqual(root["path"], "")
        self.assertEqual(root["ref"], "main")
        entries = {e["name"]: e for e in root["entries"]}
        self.assertEqual(entries["hello.txt"]["kind"], "blob")
        self.assertEqual(entries["dir"]["kind"], "tree")
        self.assertEqual(entries["dir"]["path"], "dir")
        blob = self.w.api.get_contents(None, "volmarr", "pub", "hello.txt")
        self.assertEqual(blob["kind"], "blob")
        self.assertEqual(blob["size"], len(b"hello world\n"))
        self.assertEqual(blob["encoding"], "base64")
        self.assertEqual(base64.b64decode(blob["content"]), b"hello world\n")
        self.assertEqual(blob["entries"], None)
        tree = self.w.api.get_contents(None, "volmarr", "pub", "dir")
        self.assertEqual(tree["kind"], "tree")
        self.assertEqual(
            [e["path"] for e in tree["entries"]], ["dir/note.txt"])
        nested = self.w.api.get_contents(None, "volmarr", "pub", "dir/note.txt")
        self.assertEqual(base64.b64decode(nested["content"]), b"nested note\n")
        self.assertEqual(json.loads(json.dumps(root)), root)
        self.assertEqual(
            json.loads(self.w.api.get_contents_json(None, "volmarr", "pub", "hello.txt")),
            blob)

    def test_contents_follow_the_ref(self):
        blob = self.w.api.get_contents(None, "volmarr", "pub", "hello.txt", ref="dev")
        self.assertEqual(blob["ref"], "dev")
        self.assertEqual(base64.b64decode(blob["content"]), b"dev hello\n")

    def test_contents_refusals(self):
        exc = self._error(self.w.api.get_contents, None, "volmarr", "pub", "gone.txt")
        self.assertEqual(exc.reason, "path_not_found")
        self.assertEqual(error_to_dict(exc)["status"], 404)
        exc = self._error(self.w.api.get_contents, None, "volmarr", "pub", "../secret")
        self.assertEqual(exc.reason, "path_invalid")
        exc = self._error(
            self.w.api.get_contents, None, "volmarr", "pub", "hello.txt", ref="nope")
        self.assertEqual(exc.reason, "ref_not_found")
        exc = self._error(self.w.api.get_contents, None, "volmarr", "priv", "hello.txt")
        self.assertEqual(exc.reason, "repo_not_found")
        fine = self.w.api.get_contents("Bearer " + self.w.fine_pub, "volmarr", "pub", "hello.txt")
        self.assertEqual(fine["kind"], "blob")

    def test_contents_refuse_a_blob_past_the_cap(self):
        big = self.w.repos.create_repository(
            self.w.owner.id, "volmarr", "big", visibility="public")
        path = self.w.repos.path_for("volmarr", "big")
        tree = build_tree(path, {"big.bin": b"x" * (MAX_CONTENT_BYTES + 1)})
        commit = commit_tree(path, tree, "big")
        git(path, "update-ref", "refs/heads/main", commit)
        exc = self._error(self.w.api.get_contents, None, "volmarr", "big", "big.bin")
        self.assertEqual(exc.reason, "content_too_large")
        self.assertEqual(error_to_dict(exc)["status"], 413)

    # -- forks --------------------------------------------------------------
    def test_fork_through_the_web_store_and_list(self):
        before = self._audits("repo.fork")
        data = self.w.api.create_fork(basic("yrsa", PW), "volmarr", "pub")
        self.assertEqual(data["full_name"], "yrsa/pub")
        self.assertEqual(data["fork_of"], "volmarr/pub")
        self.assertEqual(self._audits("repo.fork"), before + 1)
        listed = self.w.api.list_forks(None, "volmarr", "pub")
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["forks"][0]["full_name"], "yrsa/pub")
        self.assertEqual(listed["forks"][0]["fork_of"], "volmarr/pub")

    def test_fork_list_filters_unreadable_forks(self):
        self.w.api.create_fork(
            basic("yrsa", PW), "volmarr", "pub", {"visibility": "private"})
        stranger = self.w.api.list_forks(basic("mallory", PW), "volmarr", "pub")
        self.assertEqual(stranger["total"], 0)
        reader = self.w.api.list_forks(basic("yrsa", PW), "volmarr", "pub")
        self.assertEqual(reader["total"], 1)

    def test_fork_refusals_keep_s055_law(self):
        exc = self._error(self.w.api.create_fork, basic("mallory", PW), "volmarr", "priv")
        self.assertEqual(exc.reason, "repo_not_found")
        exc = self._error(
            self.w.api.create_fork, basic("volmarr", PW), "volmarr", "priv",
            {"name": "wide", "visibility": "public"})
        self.assertEqual(exc.reason, "fork_visibility_escalation")
        self.w.api.create_fork(basic("yrsa", PW), "volmarr", "pub")
        exc = self._error(self.w.api.create_fork, basic("yrsa", PW), "volmarr", "pub")
        self.assertEqual(exc.reason, "repo_taken")
        exc = self._error(
            self.w.api.create_fork, "Bearer " + self.w.owner_read, "volmarr", "pub",
            {"name": "scoped"})
        self.assertEqual(exc.reason, "insufficient_scope")
        exc = self._error(self.w.api.create_fork, None, "volmarr", "pub")
        self.assertEqual(exc.reason, "authentication_required")
        exc = self._error(
            self.w.api.create_fork, basic("yrsa", PW), "volmarr", "pub", {"bogus": 1})
        self.assertEqual(exc.reason, "payload_invalid")

    # -- the page, and what reads witness --------------------------------------
    def test_page_states_the_family_in_words(self):
        page = render_repositories_api_page()
        self.assertIn("Repositories API", page)
        self.assertIn("S-190", page)
        self.assertIn("grace period", page)

    def test_reads_witness_nothing(self):
        before = self._audit_total()
        self.w.api.root()
        self.w.api.list_repositories(basic("volmarr", PW))
        self.w.api.get_repository(None, "volmarr", "pub")
        self.w.api.list_branches(None, "volmarr", "pub")
        self.w.api.get_contents(None, "volmarr", "pub", "hello.txt")
        self.w.api.list_forks(None, "volmarr", "pub")
        self.assertEqual(self._audit_total(), before)


if __name__ == "__main__":
    unittest.main()
