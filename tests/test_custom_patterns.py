"""S-295 acceptance battery: custom patterns.

Acceptance (roadmap S-295): Custom patterns --
org/instance-defined regex patterns with a dry-run
against repo history before activation.

The definition, dry-run and activation law live in
samverk/custom_patterns.py over migration 116's
custom_patterns / custom_pattern_dry_runs /
custom_pattern_dry_run_matches tables (schema
115 -> 116). A pattern is defined at instance scope
(site admin) or organization scope (org owner or
site admin) standing draft; its regex is judged at
the door (compiles, capped, no backreference, no
nested quantifiers, cannot match the empty string);
activation requires a complete dry-run of the
current regex text against a repository's whole
history from its tips (S-291's introduced-blob law),
and a dry-run match carries commit, path, line, a
redacted preview and a fingerprint -- never the
matched text. The effective set for a repository is
its active instance patterns plus its owning
organization's active patterns.

No new taxonomy event -- 133 stand (33 auth /
87 repo / 13 admin); definition acts ride the
standing admin.settings.change /
auth.organization.update events, and a dry-run,
like S-291's scan, is unwitnessed.

Counted with: python3 -m unittest tests.test_custom_patterns
"""
from __future__ import annotations
import hashlib
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.custom_patterns import (
    CustomPatternError, CustomPatternStore, GitHistory,
    audit_custom_patterns, decide_activation, decide_manager,
    history_commits, pattern_sha, render_custom_patterns_page,
    render_dry_run_page, scan_text_custom, validate_regex)
from samverk.db import schema_version
from samverk.organization_members import OrgMembershipStore
from samverk.organizations import OrganizationStore
from samverk.org_repositories import OrgRepoStore
from samverk.repositories import RepositoryStore
from samverk.taxonomy import AUDIT_EVENTS

PW = "correct horse battery"
T0 = 1_700_000_000
SECRET = "ACME-SECRET-12345"
PATTERN = r"ACME-SECRET-\d+"


def oid(n: int) -> str:
    return f"{n:040x}"


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class FakeHistory:
    """In-memory history, S-291's battery shape:
    commits oid -> (parents, tree), trees are dicts
    path -> (mode, blob_oid), blobs oid -> bytes."""

    def __init__(self):
        self.parents: dict = {}
        self.trees: dict = {}
        self.blobs: dict = {}
        self._next = 1000

    def add_blob(self, data: bytes) -> str:
        self._next += 1
        b = oid(self._next)
        self.blobs[b] = data
        return b

    def add_commit(self, parents=(), files=None) -> str:
        self._next += 1
        c = oid(self._next)
        tree = {}
        for path, data in (files or {}).items():
            tree[path] = ("100644", self.add_blob(data))
        self.parents[c] = tuple(parents)
        self.trees[c] = tree
        return c

    def add_commit_tree(self, parents, tree) -> str:
        self._next += 1
        c = oid(self._next)
        self.parents[c] = tuple(parents)
        self.trees[c] = dict(tree)
        return c

    def commit_parents(self, o):
        return self.parents[o]

    def commit_tree(self, o):
        return o

    def flatten_tree(self, t):
        return dict(self.trees[t])

    def read_blob(self, o):
        return self.blobs[o]


class CustomPatternTests(unittest.TestCase):
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
        self.member = self.accounts.register("yrsa", PW)
        self.outsider = self.accounts.register("freya", PW)
        self.admin = self.accounts.register("sitemod", PW)
        with self.conn:
            self.conn.execute(
                "UPDATE users SET is_admin = 1 WHERE id = ?",
                (self.admin.id,))
        self.admin = self.accounts.get_by_id(self.admin.id)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.repo = self.repos.create_repository(
            self.owner.id, "volmarr", "forge")
        self.orgs = OrganizationStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        self.org = self.orgs.create_organization(
            self.owner.id, "acme")
        self.members = OrgMembershipStore(
            self.conn, self.accounts, self.audit,
            time_fn=self.clock)
        self.members.add_member(
            self.owner.id, self.org.id, self.member.id)
        self.org_repos = OrgRepoStore(
            self.conn, self.accounts, self.root, self.audit,
            time_fn=self.clock)
        self.org_repo = self.org_repos.create_repository(
            self.owner.id, self.org.id, "anvil")
        self.patterns = CustomPatternStore(
            self.conn, self.repos, self.orgs, self.members,
            audit=self.audit, time_fn=self.clock)
        self.hist = FakeHistory()

    # -- helpers -----------------------------------------------------

    def reason(self, fn, *args, **kwargs):
        with self.assertRaises(CustomPatternError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def instance_pattern(self, name="Acme secret", regex=PATTERN):
        return self.patterns.create_pattern(
            self.admin, "instance", name, regex,
            description="the acme internal token")

    def org_pattern(self, name="Acme secret", regex=PATTERN):
        return self.patterns.create_pattern(
            self.owner, "org", name, regex, org_name="acme")

    def chain(self, n=2, secret_at=None):
        commits = []
        parent = ()
        for i in range(n):
            body = (f"token = {SECRET}\n" if i == secret_at
                    else f"ordinary content {i}\n")
            c = self.hist.add_commit(
                parents=parent, files={"app.py": body.encode()})
            commits.append(c)
            parent = (c,)
        return commits

    def audit_count(self, action=None):
        if action is None:
            return self.conn.execute(
                "SELECT COUNT(*) AS n FROM audit_log"
            ).fetchone()["n"]
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action = ?",
            (action,)).fetchone()["n"]

    # -- schema / taxonomy pins ---------------------------------------

    def test_schema_stands_at_116(self):
        self.assertEqual(schema_version(self.conn), 116)
        self.assertEqual(db.MIGRATIONS[-1][0], 116)

    def test_taxonomy_still_133(self):
        self.assertEqual(len(AUDIT_EVENTS), 133)

    # -- the definition door -------------------------------------------

    def test_instance_pattern_created_draft_by_admin(self):
        p = self.instance_pattern()
        self.assertEqual(p.state, "draft")
        self.assertEqual(p.scope, "instance")
        self.assertIsNone(p.org_id)
        self.assertEqual(p.regex_sha, pattern_sha(PATTERN))
        self.assertEqual(p.created_by, self.admin.id)
        self.assertIsNone(p.activated_at)

    def test_org_pattern_created_draft_by_owner(self):
        p = self.org_pattern()
        self.assertEqual(p.scope, "org")
        self.assertEqual(p.org_id, self.org.id)
        self.assertEqual(p.org_name_lower, "acme")

    def test_org_pattern_created_by_site_admin(self):
        p = self.patterns.create_pattern(
            self.admin, "org", "Admin made", PATTERN,
            org_name="acme")
        self.assertEqual(p.created_by, self.admin.id)

    def test_anonymous_definition_refused(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        None, "instance", "X", PATTERN),
            "authentication_required")

    def test_non_admin_cannot_define_instance_pattern(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        self.owner, "instance", "X", PATTERN),
            "permission_denied")

    def test_org_member_cannot_define_org_pattern(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        self.member, "org", "X", PATTERN,
                        org_name="acme"),
            "permission_denied")

    def test_outsider_cannot_define_org_pattern(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        self.outsider, "org", "X", PATTERN,
                        org_name="acme"),
            "permission_denied")

    def test_missing_org_is_named(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        self.admin, "org", "X", PATTERN,
                        org_name="nope"),
            "org_not_found")

    def test_bad_scope_refused(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        self.admin, "repo", "X", PATTERN),
            "scope_invalid")
        self.assertEqual(
            decide_manager("repo", is_admin=True, org_role=None),
            "scope_invalid")

    def test_duplicate_name_refused_per_scope(self):
        self.instance_pattern()
        self.assertEqual(
            self.reason(self.instance_pattern, "acme secret"),
            "pattern_taken")
        # the same name at org scope is a different scope
        p = self.org_pattern("acme secret")
        self.assertEqual(p.name_lower, "acme secret")

    def test_uncompilable_regex_refused_storing_nothing(self):
        self.assertEqual(
            self.reason(self.patterns.create_pattern,
                        self.admin, "instance", "X", "(["),
            "pattern_invalid")
        self.assertEqual(self.patterns.count_patterns(), 0)
        with self.assertRaises(CustomPatternError) as ctx:
            validate_regex("([")
        self.assertEqual(ctx.exception.reason, "pattern_invalid")

    def test_unsafe_regexes_refused(self):
        self.assertEqual(
            self.reason(validate_regex, r"(a+)+$"),
            "pattern_unsafe")
        self.assertEqual(
            self.reason(validate_regex, r"(abc)\1"),
            "pattern_unsafe")
        self.assertEqual(self.patterns.count_patterns(), 0)

    def test_empty_matching_regex_refused(self):
        self.assertEqual(
            self.reason(validate_regex, r"a*"),
            "pattern_matches_empty")
        self.assertEqual(
            self.reason(validate_regex, r"x?"),
            "pattern_matches_empty")

    def test_overlong_regex_refused(self):
        self.assertEqual(
            self.reason(validate_regex, "a" * 501),
            "pattern_too_long")

    def test_definition_is_witnessed_on_standing_events(self):
        before = self.audit_count("admin.settings.change")
        self.instance_pattern()
        self.assertEqual(
            self.audit_count("admin.settings.change"), before + 1)
        before = self.audit_count("auth.organization.update")
        self.org_pattern()
        self.assertEqual(
            self.audit_count("auth.organization.update"),
            before + 1)

    def test_refused_definition_audits_nothing(self):
        before = self.audit_count()
        self.reason(self.patterns.create_pattern,
                    self.owner, "instance", "X", PATTERN)
        self.assertEqual(self.audit_count(), before)

    # -- pure decisions ---------------------------------------------------

    def test_decide_manager_pure_law(self):
        self.assertIsNone(decide_manager(
            "instance", is_admin=True, org_role=None))
        self.assertEqual(decide_manager(
            "instance", is_admin=False, org_role="owner"),
            "permission_denied")
        self.assertIsNone(decide_manager(
            "org", is_admin=False, org_role="owner"))
        self.assertEqual(decide_manager(
            "org", is_admin=False, org_role="member"),
            "permission_denied")
        self.assertIsNone(decide_manager(
            "org", is_admin=True, org_role=None))

    def test_history_commits_oldest_first(self):
        c1, c2, c3 = self.chain(3)
        self.assertEqual(
            history_commits(self.hist, [c3]), [c1, c2, c3])
        self.assertEqual(history_commits(self.hist, []), [])

    def test_scan_text_custom_overlap_law(self):
        p1 = self.instance_pattern("Long", r"ACME-SECRET-\d+")
        p2 = self.patterns.create_pattern(
            self.admin, "instance", "Short", r"ACME")
        findings = scan_text_custom(
            f"x {SECRET} y\n", [p1, p2])
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern_id, p1.id)
        self.assertEqual(findings[0].line, 1)
        self.assertNotIn(SECRET, findings[0].redacted)
        self.assertEqual(
            findings[0].fingerprint,
            hashlib.sha256(SECRET.encode()).hexdigest())

    # -- the dry-run ---------------------------------------------------------

    def test_dry_run_finds_secret_buried_in_history(self):
        p = self.org_pattern()
        c1, c2, c3 = self.chain(3, secret_at=0)
        run = self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=[c3])
        self.assertEqual(run.status, "complete")
        self.assertEqual(run.commits_scanned, 3)
        self.assertEqual(run.matches_count, 1)
        self.assertEqual(run.pattern_sha, p.regex_sha)
        matches = self.patterns.dry_run_matches(run.id)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0].commit_oid, c1)
        self.assertEqual(matches[0].path, "app.py")
        self.assertEqual(matches[0].line, 1)

    def test_dry_run_clean_history_matches_nothing(self):
        p = self.instance_pattern()
        commits = self.chain(2)
        run = self.patterns.dry_run(
            self.admin, p.id, "volmarr", "forge",
            history=self.hist, tips=[commits[-1]])
        self.assertEqual(run.status, "complete")
        self.assertEqual(run.matches_count, 0)

    def test_dry_run_requires_repo_read(self):
        p = self.org_pattern()
        commits = self.chain(1, secret_at=0)
        # a manager of nothing is refused at the manager door
        self.assertEqual(
            self.reason(self.patterns.dry_run,
                        self.member, p.id, "volmarr", "forge",
                        history=self.hist, tips=commits),
            "permission_denied")
        # the org owner manages the pattern but cannot read
        # another account's private repository: it answers
        # exactly as a missing one
        self.repos.create_repository(
            self.outsider.id, "freya", "vault")
        self.assertEqual(
            self.reason(self.patterns.dry_run,
                        self.owner, p.id, "freya", "vault",
                        history=self.hist, tips=commits),
            "repo_not_found")

    def test_dry_run_missing_repo_named(self):
        p = self.instance_pattern()
        self.assertEqual(
            self.reason(self.patterns.dry_run,
                        self.admin, p.id, "volmarr", "nope",
                        history=self.hist, tips=[oid(1)]),
            "repo_not_found")
        self.assertEqual(
            self.reason(self.patterns.dry_run,
                        self.admin, 9999, "volmarr", "forge",
                        history=self.hist, tips=[oid(1)]),
            "pattern_not_found")

    def test_dry_run_bad_tips_refused(self):
        p = self.org_pattern()
        self.assertEqual(
            self.reason(self.patterns.dry_run,
                        self.owner, p.id, "volmarr", "forge",
                        history=self.hist, tips=["zz"]),
            "tips_invalid")
        self.assertEqual(
            self.reason(self.patterns.dry_run,
                        self.owner, p.id, "volmarr", "forge",
                        history=self.hist, tips=[]),
            "tips_invalid")

    def test_dry_run_binary_blob_skipped_and_counted(self):
        p = self.org_pattern()
        blob = self.hist.add_blob(b"\x00\x01" + SECRET.encode())
        c = self.hist.add_commit_tree(
            (), {"bin.dat": ("100644", blob)})
        run = self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=[c])
        self.assertEqual(run.blobs_skipped, 1)
        self.assertEqual(run.matches_count, 0)

    def test_dry_run_is_unwitnessed(self):
        p = self.org_pattern()
        before = self.audit_count()
        commits = self.chain(1, secret_at=0)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        self.assertEqual(self.audit_count(), before)

    def test_commit_cap_marks_partial_and_blocks_activation(self):
        import samverk.custom_patterns as cp
        p = self.org_pattern()
        commits = self.chain(4, secret_at=3)
        old = cp.MAX_COMMITS_PER_RUN
        cp.MAX_COMMITS_PER_RUN = 2
        try:
            run = self.patterns.dry_run(
                self.owner, p.id, "volmarr", "forge",
                history=self.hist, tips=[commits[-1]])
        finally:
            cp.MAX_COMMITS_PER_RUN = old
        self.assertEqual(run.status, "partial")
        self.assertEqual(run.partial_reason, "commit_cap")
        self.assertEqual(
            self.reason(self.patterns.activate_pattern,
                        self.owner, p.id),
            "dry_run_incomplete")
        self.assertEqual(
            decide_activation("draft", p.regex_sha, run),
            "dry_run_incomplete")

    # -- activation law ---------------------------------------------------------

    def test_activation_requires_dry_run(self):
        p = self.org_pattern()
        self.assertEqual(
            self.reason(self.patterns.activate_pattern,
                        self.owner, p.id),
            "dry_run_required")
        self.assertEqual(
            decide_activation("draft", p.regex_sha, None),
            "dry_run_required")

    def test_activation_after_complete_dry_run(self):
        p = self.org_pattern()
        commits = self.chain(2, secret_at=1)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=[commits[-1]])
        active = self.patterns.activate_pattern(self.owner, p.id)
        self.assertEqual(active.state, "active")
        self.assertEqual(active.activated_by, self.owner.id)
        self.assertIsNotNone(active.activated_at)
        self.assertEqual(
            self.reason(self.patterns.activate_pattern,
                        self.owner, p.id),
            "already_active")

    def test_edit_after_dry_run_makes_it_stale(self):
        p = self.org_pattern()
        commits = self.chain(1)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        edited = self.patterns.update_pattern(
            self.owner, p.id, regex=r"ACME-TOKEN-\d+")
        self.assertEqual(edited.state, "draft")
        self.assertEqual(
            self.reason(self.patterns.activate_pattern,
                        self.owner, p.id),
            "dry_run_stale")

    def test_active_regex_edit_refused_until_disabled(self):
        p = self.org_pattern()
        commits = self.chain(1)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        self.patterns.activate_pattern(self.owner, p.id)
        self.assertEqual(
            self.reason(self.patterns.update_pattern,
                        self.owner, p.id, regex=r"OTHER-\d+"),
            "pattern_is_active")
        # a name-only edit is lawful while active
        renamed = self.patterns.update_pattern(
            self.owner, p.id, name="Renamed")
        self.assertEqual(renamed.state, "active")
        disabled = self.patterns.disable_pattern(self.owner, p.id)
        self.assertEqual(disabled.state, "disabled")
        self.assertEqual(
            self.reason(self.patterns.disable_pattern,
                        self.owner, p.id),
            "not_active")
        # reactivation stands on the same complete dry-run
        again = self.patterns.activate_pattern(self.owner, p.id)
        self.assertEqual(again.state, "active")

    def test_activation_by_non_manager_refused(self):
        p = self.org_pattern()
        commits = self.chain(1)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        self.assertEqual(
            self.reason(self.patterns.activate_pattern,
                        self.member, p.id),
            "permission_denied")

    # -- the effective set -------------------------------------------------------

    def test_effective_patterns_compose_scopes(self):
        org_p = self.org_pattern()
        inst_p = self.instance_pattern("Instance one")
        commits = self.chain(1)
        for pattern, actor in ((org_p, self.owner),
                               (inst_p, self.admin)):
            self.patterns.dry_run(
                actor, pattern.id, "volmarr", "forge",
                history=self.hist, tips=commits)
            self.patterns.activate_pattern(actor, pattern.id)
        # the org's own repository: both scopes judge it
        effective = self.patterns.effective_patterns(
            "acme", "anvil")
        self.assertEqual(
            {p.id for p in effective}, {org_p.id, inst_p.id})
        # a user repository: the instance scope only
        effective = self.patterns.effective_patterns(
            "volmarr", "forge")
        self.assertEqual({p.id for p in effective}, {inst_p.id})
        findings = self.patterns.scan_text_effective(
            f"leak {SECRET}\n", "acme", "anvil")
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].pattern_id, inst_p.id)

    def test_draft_and_disabled_patterns_judge_nothing(self):
        p = self.org_pattern()
        self.assertEqual(
            self.patterns.effective_patterns("acme", "anvil"),
            ())
        commits = self.chain(1)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        self.patterns.activate_pattern(self.owner, p.id)
        self.patterns.disable_pattern(self.owner, p.id)
        self.assertEqual(
            self.patterns.effective_patterns("acme", "anvil"),
            ())

    def test_effective_missing_repo_named(self):
        self.assertEqual(
            self.reason(self.patterns.effective_patterns,
                        "volmarr", "nope"),
            "repo_not_found")

    # -- redaction law ------------------------------------------------------------

    def test_secret_never_stored_or_rendered(self):
        p = self.org_pattern()
        commits = self.chain(1, secret_at=0)
        run = self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        match = self.patterns.dry_run_matches(run.id)[0]
        for surface in (
                str(match.to_dict()), str(run.to_dict()),
                str(p.to_dict()),
                render_dry_run_page(
                    run, self.patterns.dry_run_matches(run.id), p),
                render_custom_patterns_page([p])):
            self.assertNotIn(SECRET, surface)
        row = self.conn.execute(
            "SELECT * FROM custom_pattern_dry_run_matches"
        ).fetchone()
        self.assertNotIn(SECRET, str(dict(row)))

    def test_render_pages_state_facts_in_words(self):
        p = self.org_pattern()
        page = render_custom_patterns_page([p])
        self.assertIn("draft", page)
        self.assertIn("acme", page)
        commits = self.chain(1, secret_at=0)
        run = self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        run_page = render_dry_run_page(
            run, self.patterns.dry_run_matches(run.id), p)
        self.assertIn("whole history", run_page)
        self.assertIn("app.py", run_page)

    # -- reads and the audit --------------------------------------------------------

    def test_list_and_count_reads(self):
        self.instance_pattern("One")
        self.org_pattern("Two")
        self.assertEqual(self.patterns.count_patterns(), 2)
        self.assertEqual(
            self.patterns.count_patterns(state="draft"), 2)
        self.assertEqual(
            len(self.patterns.list_patterns(scope="org")), 1)
        self.assertEqual(
            len(self.patterns.list_patterns(org_name="ACME")), 1)
        self.assertEqual(
            self.reason(self.patterns.list_patterns,
                        state="bogus"),
            "state_invalid")

    def test_audit_reproves_activation_invariant(self):
        report = audit_custom_patterns(self.conn)
        self.assertTrue(report.ok)
        p = self.org_pattern()
        commits = self.chain(1)
        self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=self.hist, tips=commits)
        self.patterns.activate_pattern(self.owner, p.id)
        report = audit_custom_patterns(self.conn)
        self.assertTrue(report.ok)
        self.assertEqual(report.active_total, 1)
        # plant a lawless active pattern: the audit catches it
        with self.conn:
            self.conn.execute(
                "INSERT INTO custom_patterns (scope, org_id,"
                " org_name, org_name_lower, name, name_lower,"
                " description, regex, regex_sha, state,"
                " created_by, created_at, updated_at,"
                " activated_by, activated_at) VALUES"
                " ('instance', NULL, NULL, NULL, 'Planted',"
                " 'planted', '', 'X\\\\d+', ?, 'active', ?,"
                " ?, ?, NULL, NULL)",
                (pattern_sha(r"X\d+"), self.admin.id, T0, T0))
        report = audit_custom_patterns(self.conn)
        self.assertFalse(report.ok)
        self.assertTrue(any(
            s.startswith("active_without_dry_run")
            for s in report.problems))

    # -- the real-git road -------------------------------------------------------------

    @unittest.skipUnless(subprocess.run(
        ["git", "--version"], capture_output=True).returncode == 0,
        "git not available")
    def test_real_git_history_road(self):
        p = self.org_pattern()
        bare = self.repos.path_for("volmarr", "forge")
        work = Path(self._td.name) / "work"
        env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "T",
               "GIT_COMMITTER_EMAIL": "t@t", "PATH": "/usr/bin:/bin"}

        def git(*args, cwd):
            r = subprocess.run(["git", *args], cwd=cwd, env=env,
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)

        git("clone", str(bare), str(work), cwd=self.root)
        (work / "app.py").write_text(f"{SECRET}\n")
        git("add", ".", cwd=work)
        git("commit", "-m", "one", cwd=work)
        (work / "app.py").write_text("clean now\n")
        git("add", ".", cwd=work)
        git("commit", "-m", "two", cwd=work)
        git("push", "origin", "HEAD:refs/heads/main", cwd=work)
        tip = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=work, env=env,
            capture_output=True, text=True).stdout.strip()
        run = self.patterns.dry_run(
            self.owner, p.id, "volmarr", "forge",
            history=GitHistory(bare), tips=[tip])
        self.assertEqual(run.commits_scanned, 2)
        self.assertEqual(run.matches_count, 1)
        active = self.patterns.activate_pattern(self.owner, p.id)
        self.assertEqual(active.state, "active")


if __name__ == "__main__":
    unittest.main()
