"""S-301 acceptance battery: dependency review on PRs.

Acceptance (roadmap S-301): Dependency review on
PRs -- a PR's manifest changes summarised with new
vulnerabilities flagged, as a check (S-246) the
branch rules can require.

The review lives in samverk/dependency_review.py
over the pull request's recorded base and head
snapshots: both sides read through S-297's parsers
under the graph's own skip law, the diff judged
against the standing advisory snapshot by S-299's
own pure judgement. New means new -- a vulnerability
the base already carried is never laid at the pull
request's door; an unjudged new specifier or a
changed manifest that could not be read makes the
review incomplete, and an incomplete review's check
fails. Publishing records one check row under the
context ``dependency-review`` against the head
commit through S-157's seam, in S-246's shape.
No migration (schema 122 stands) and no new
taxonomy event -- 134 stand (33 auth / 88 repo /
13 admin); the battery proves the audit log does
not move.

Counted with: python3 -m unittest tests.test_dependency_review
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.advisory_data import AdvisoryStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.dependency_graph import parse_manifest
from samverk.dependency_review import (
    CHECK_CONTEXT, CONCLUSION_CLEAN, CONCLUSION_INCOMPLETE,
    CONCLUSION_NO_CHANGES, CONCLUSION_VULNERABILITIES,
    DependencyReviewStore, check_state_for, decide_conclusion,
    diff_snapshots, flag_vulnerabilities, ManifestSnapshot,
    render_dependency_review, render_dependency_review_page)
from samverk.issues import IssueStore
from samverk.pull_request_checks import PullRequestChecksStore
from samverk.pull_requests import PullRequestError, PullRequestStore
from samverk.repositories import RepositoryStore

TODAY = date(2026, 11, 12)
T0 = 1_700_000_000


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T", "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(["git", f"--git-dir={repo}", *args],
                         capture_output=True, input=input_bytes,
                         env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def make_tree(repo, files):
    def build(items):
        entries = []
        dirs = {}
        for path, content in items:
            head, _, rest = path.partition("/")
            if rest:
                dirs.setdefault(head, []).append((rest, content))
            else:
                blob = git(repo, "hash-object", "-w", "--stdin",
                           input_bytes=content.encode())
                entries.append(
                    (path, f"100644 blob {blob}\t{path}"))
        for name, sub in dirs.items():
            tree = build(sub)
            entries.append(
                (name + "/", f"040000 tree {tree}\t{name}"))
        entries.sort(key=lambda item: item[0])
        return git(repo, "mktree",
                   input_bytes=("\n".join(
                       line for _key, line in entries)
                       + "\n").encode())
    return build(sorted(files.items()))


def make_commit(repo, parent, files, message):
    tree = make_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args, input_bytes=(message + "\n").encode())


def snap_text(*advisories, snapshot_date="2026-11-10"):
    return json.dumps({
        "snapshot_format": 1,
        "source": "S-301 battery snapshot",
        "snapshot_date": snapshot_date,
        "advisories": list(advisories),
    })


def advisory(adv_id, package, affected, fixed="2.0.0",
             severity="high", ecosystem="python",
             summary="a test advisory"):
    return {"id": adv_id, "ecosystem": ecosystem,
            "package": package, "severity": severity,
            "affected": affected, "fixed_version": fixed,
            "summary": summary, "published": "2026-01-01",
            "references": []}


CUSTOM = AdvisoryStore.from_text(snap_text(
    advisory("CVE-3010-0001", "vulnpkg", "<2.0.0"),
    advisory("CVE-3010-0002", "safepkg", "<1.0.0",
             fixed="1.0.0", severity="low"),
), now=TODAY)


def parsed_snapshot(path, text, blob="b" * 40):
    ecosystem_kind = {"requirements.txt": ("python", "requirements"),
                      "package.json": ("npm", "package_json"),
                      "go.mod": ("go", "go_mod"),
                      "Cargo.toml": ("rust", "cargo_toml")}
    ecosystem, kind = ecosystem_kind[Path(path).name]
    parsed = parse_manifest(path, text)
    return ManifestSnapshot(
        path=path, ecosystem=ecosystem, kind=kind,
        status="parsed", dependencies=tuple(parsed.dependencies),
        blob_oid=blob)


class Clock:
    def __init__(self, now=T0):
        self.now = now

    def __call__(self):
        return self.now


class PureDiffTests(unittest.TestCase):
    def test_added_removed_changed_unchanged(self):
        base = {"requirements.txt": parsed_snapshot(
            "requirements.txt",
            "alpha==1.0.0\nbeta==1.0.0\ngone==3.0.0\n",
            blob="a" * 40)}
        head = {"requirements.txt": parsed_snapshot(
            "requirements.txt",
            "alpha==1.0.0\nbeta==1.1.0\nnewpkg==0.5.0\n",
            blob="c" * 40)}
        manifests, deps = diff_snapshots(base, head)
        self.assertEqual(len(manifests), 1)
        self.assertEqual(manifests[0].change, "modified")
        by_name = {d.name: d for d in deps}
        self.assertEqual(set(by_name), {"beta", "gone", "newpkg"})
        self.assertEqual(by_name["beta"].change, "changed")
        self.assertEqual(by_name["beta"].old_specifier, "==1.0.0")
        self.assertEqual(by_name["beta"].new_specifier, "==1.1.0")
        self.assertEqual(by_name["gone"].change, "removed")
        self.assertEqual(by_name["newpkg"].change, "added")

    def test_manifest_added_and_removed(self):
        base = {"requirements.txt": parsed_snapshot(
            "requirements.txt", "alpha==1.0.0\n")}
        head = {"package.json": parsed_snapshot(
            "package.json", '{"dependencies": {"x": "1.0.0"}}')}
        manifests, deps = diff_snapshots(base, head)
        changes = {m.path: m.change for m in manifests}
        self.assertEqual(changes, {
            "requirements.txt": "removed",
            "package.json": "added"})
        dep_changes = {(d.manifest_path, d.change) for d in deps}
        self.assertEqual(dep_changes, {
            ("requirements.txt", "removed"),
            ("package.json", "added")})

    def test_same_blob_is_no_change(self):
        snap = parsed_snapshot(
            "requirements.txt", "alpha==1.0.0\n", blob="d" * 40)
        manifests, deps = diff_snapshots(
            {"requirements.txt": snap},
            {"requirements.txt": snap})
        self.assertEqual(manifests, ())
        self.assertEqual(deps, ())


class PureFlagTests(unittest.TestCase):
    def _diff(self, base_text, head_text):
        base = {"requirements.txt": parsed_snapshot(
            "requirements.txt", base_text, blob="a" * 40)}
        head = {"requirements.txt": parsed_snapshot(
            "requirements.txt", head_text, blob="c" * 40)}
        _m, deps = diff_snapshots(base, head)
        return flag_vulnerabilities(deps, CUSTOM.for_package)

    def test_added_vulnerable_dependency_flagged(self):
        new, resolved, unjudged = self._diff(
            "alpha==1.0.0\n", "alpha==1.0.0\nvulnpkg==1.5.0\n")
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].advisory_id, "CVE-3010-0001")
        self.assertEqual(new[0].severity, "high")
        self.assertEqual(new[0].fixed_version, "2.0.0")
        self.assertEqual(new[0].change, "added")
        self.assertEqual(resolved, ())
        self.assertEqual(unjudged, 0)

    def test_changed_into_range_flagged(self):
        new, _r, _u = self._diff(
            "vulnpkg==2.5.0\n", "vulnpkg==1.5.0\n")
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].change, "changed")

    def test_already_vulnerable_base_is_not_new(self):
        new, resolved, _u = self._diff(
            "vulnpkg==1.5.0\n", "vulnpkg==1.6.0\n")
        self.assertEqual(new, ())
        self.assertEqual(resolved, ())

    def test_changed_out_of_range_is_resolved(self):
        new, resolved, _u = self._diff(
            "vulnpkg==1.5.0\n", "vulnpkg==2.5.0\n")
        self.assertEqual(new, ())
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0].change, "resolved")

    def test_removed_vulnerable_dependency_is_resolved(self):
        new, resolved, _u = self._diff(
            "vulnpkg==1.5.0\nalpha==1.0.0\n", "alpha==1.0.0\n")
        self.assertEqual(new, ())
        self.assertEqual(len(resolved), 1)

    def test_bare_name_is_an_unconstrained_range(self):
        # S-299's semantics: a bare name constrains
        # nothing, so its range overlaps the affected
        # range and the match stands, on a range basis.
        new, _r, unjudged = self._diff(
            "alpha==1.0.0\n", "alpha==1.0.0\nvulnpkg\n")
        self.assertEqual(len(new), 1)
        self.assertEqual(new[0].basis, "range")
        self.assertEqual(unjudged, 0)

    def test_unjudged_specifier_counted(self):
        new, _r, unjudged = self._diff(
            "alpha==1.0.0\n",
            "alpha==1.0.0\n"
            "vulnpkg @ https://example.com/vulnpkg-1.0.tar.gz\n")
        self.assertEqual(new, ())
        self.assertEqual(unjudged, 1)

    def test_conclusion_and_check_state_law(self):
        self.assertEqual(
            decide_conclusion((), (), (), ("why",)),
            CONCLUSION_INCOMPLETE)
        self.assertEqual(
            decide_conclusion(("m",), ("d",), ("f",), ()),
            CONCLUSION_VULNERABILITIES)
        self.assertEqual(
            decide_conclusion((), (), (), ()),
            CONCLUSION_NO_CHANGES)
        self.assertEqual(
            decide_conclusion(("m",), ("d",), (), ()),
            CONCLUSION_CLEAN)
        self.assertEqual(
            check_state_for(CONCLUSION_CLEAN), "passed")
        self.assertEqual(
            check_state_for(CONCLUSION_NO_CHANGES), "passed")
        self.assertEqual(
            check_state_for(CONCLUSION_VULNERABILITIES), "failed")
        self.assertEqual(
            check_state_for(CONCLUSION_INCOMPLETE), "failed")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.clock = Clock()
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(self.conn, time_fn=self.clock)
        self.owner = self.accounts.register(
            "volmarr", "correct horse battery")
        self.reader = self.accounts.register(
            "yrsa", "correct horse battery")
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts)
        self.issues = IssueStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.prs = PullRequestStore(
            self.conn, self.repos, self.accounts, self.issues,
            audit=self.audit, time_fn=self.clock)
        self.checks = PullRequestChecksStore(
            self.conn, self.repos, self.accounts, self.issues,
            time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.path = self.repos.path_for("volmarr", "pub")

    def _open(self, base_files, head_files, *, name="pub",
              visibility="public"):
        if name != "pub" or visibility != "public":
            self.repos.create_repository(
                self.owner.id, "volmarr", name,
                visibility=visibility)
        path = self.repos.path_for("volmarr", name)
        base_oid = make_commit(path, None, base_files, "base")
        git(path, "update-ref", "refs/heads/main", base_oid)
        head_oid = make_commit(
            path, base_oid, head_files, "feature work")
        git(path, "update-ref", "refs/heads/feature", head_oid)
        pr = self.prs.create_pull_request(
            self.owner, "volmarr", name,
            base_branch="main", head_branch="feature")
        return pr, base_oid, head_oid

    def _store(self, advisories=CUSTOM):
        return DependencyReviewStore(
            self.conn, self.repos, self.accounts, self.issues,
            advisories=advisories, time_fn=self.clock)


class ReviewTests(StoreCase):
    def test_no_manifest_changes(self):
        pr, _b, _h = self._open(
            {"a.txt": "alpha\n"}, {"a.txt": "alpha\nbeta\n"})
        review = self._store().review_pull_request(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(review.conclusion, CONCLUSION_NO_CHANGES)
        self.assertEqual(review.check_state, "passed")
        self.assertEqual(review.manifest_changes, ())
        self.assertIn("2026-11-10", review.age_words)

    def test_clean_manifest_change(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt": "alpha==1.0.0\nbeta==2.0.0\n"})
        review = self._store().review_pull_request(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(review.conclusion, CONCLUSION_CLEAN)
        self.assertEqual(review.added_count, 1)
        self.assertEqual(review.new_vulnerabilities, ())

    def test_new_vulnerability_flagged_and_check_fails(self):
        pr, _b, head_oid = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.5.0\n"})
        store = self._store()
        review, check = store.publish_check(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(
            review.conclusion, CONCLUSION_VULNERABILITIES)
        self.assertEqual(len(review.new_vulnerabilities), 1)
        flag = review.new_vulnerabilities[0]
        self.assertEqual(flag.advisory_id, "CVE-3010-0001")
        self.assertEqual(flag.fixed_words, "fixed in 2.0.0")
        self.assertEqual(check.context, CHECK_CONTEXT)
        self.assertEqual(check.state, "failed")
        self.assertEqual(check.head_oid, head_oid)
        self.assertIn("new vulnerabilities",
                      check.description.lower())
        panel = self.checks.checks_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(len(panel), 1)
        self.assertEqual(panel[0].context, "dependency-review")

    def test_new_manifests_dependencies_are_reviewed(self):
        pr, _b, _h = self._open(
            {"a.txt": "alpha\n"},
            {"requirements.txt": "vulnpkg==1.5.0\n"})
        review = self._store().review_pull_request(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(review.manifest_changes[0].change,
                         "added")
        self.assertEqual(review.added_count, 1)
        self.assertEqual(
            review.conclusion, CONCLUSION_VULNERABILITIES)

    def test_upgrade_resolves_and_passes(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "vulnpkg==1.5.0\n"},
            {"requirements.txt": "vulnpkg==2.5.0\n"})
        review, check = self._store().publish_check(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(review.conclusion, CONCLUSION_CLEAN)
        self.assertEqual(len(review.resolved_vulnerabilities), 1)
        self.assertEqual(check.state, "passed")

    def test_broken_head_manifest_is_incomplete(self):
        pr, _b, _h = self._open(
            {"package.json": '{"dependencies": {}}'},
            {"package.json": "{not json"})
        review, check = self._store().publish_check(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(review.conclusion, CONCLUSION_INCOMPLETE)
        self.assertTrue(review.incomplete_reasons)
        self.assertIn("package.json",
                      review.incomplete_reasons[0])
        self.assertEqual(check.state, "failed")

    def test_unjudged_new_specifier_is_incomplete(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\n"
             "vulnpkg @ https://example.com/v-1.0.tar.gz\n"})
        review = self._store().review_pull_request(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(review.unjudged, 1)
        self.assertEqual(review.conclusion, CONCLUSION_INCOMPLETE)

    def test_review_is_a_pure_read_until_published(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.5.0\n"})
        store = self._store()
        store.review_pull_request(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(self.checks.checks_for(
            self.owner, "volmarr", "pub", pr.number), [])

    def test_republish_updates_the_one_check_row(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.5.0\n"})
        store = self._store()
        store.publish_check(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        store.publish_check(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        panel = self.checks.checks_for(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(len(panel), 1)
        self.assertEqual(panel[0].state, "failed")

    def test_bundled_snapshot_end_to_end(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "requests==2.0.0\n"},
            {"requirements.txt":
             "requests==2.0.0\nPyYAML==5.3\n"})
        store = self._store(advisories=None)
        review = store.review_pull_request(
            self.owner, "volmarr", "pub", pr.number)
        self.assertEqual(
            review.conclusion, CONCLUSION_VULNERABILITIES)
        self.assertEqual(
            review.new_vulnerabilities[0].advisory_id,
            "CVE-2020-14343")
        self.assertIn("2026-11-12", review.snapshot_date)

    def test_npm_manifest_change_flagged(self):
        store_adv = AdvisoryStore.from_text(snap_text(
            advisory("CVE-3010-0009", "lodash", "<4.17.19",
                     fixed="4.17.19", ecosystem="npm"),
        ), now=TODAY)
        pr, _b, _h = self._open(
            {"package.json": '{"dependencies": {}}'},
            {"package.json":
             '{"dependencies": {"lodash": "4.17.18"}}'})
        review = self._store(advisories=store_adv) \
            .review_pull_request(
                self.owner, "volmarr", "pub", pr.number,
                now=TODAY)
        self.assertEqual(
            review.conclusion, CONCLUSION_VULNERABILITIES)
        self.assertEqual(
            review.new_vulnerabilities[0].name, "lodash")

    def test_subdirectory_manifest_reviewed(self):
        pr, _b, _h = self._open(
            {"sub/requirements.txt": "alpha==1.0.0\n"},
            {"sub/requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.0.0\n"})
        review = self._store().review_pull_request(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        self.assertEqual(
            review.conclusion, CONCLUSION_VULNERABILITIES)
        self.assertEqual(
            review.manifest_changes[0].path,
            "sub/requirements.txt")

    def test_private_repo_stranger_refused(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.5.0\n"},
            name="priv", visibility="private")
        store = self._store()
        with self.assertRaises(PullRequestError) as caught:
            store.review_pull_request(
                self.reader, "volmarr", "priv", pr.number,
                now=TODAY)
        self.assertEqual(caught.exception.reason,
                         "pull_request_not_found")
        self.assertEqual(self.checks.checks_for_commit(
            "volmarr", "priv", pr.head_oid), [])


class StandingTests(StoreCase):
    def test_no_migration_and_taxonomy_unchanged(self):
        self.assertEqual(schema_version(self.conn), 125)
        self.assertEqual(db.MIGRATIONS[-1][0], 125)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)

    def test_audit_log_does_not_move_across_publish(self):
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.5.0\n"})
        before = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self._store().publish_check(
            self.owner, "volmarr", "pub", pr.number, now=TODAY)
        after = self.conn.execute(
            "SELECT COUNT(*) FROM audit_log").fetchone()[0]
        self.assertEqual(before, after)

    def test_render_says_standing_in_words_and_escapes(self):
        evil = AdvisoryStore.from_text(snap_text(
            advisory("CVE-3010-0007", "vulnpkg", "<2.0.0",
                     summary="<script>alert(1)</script>"),
        ), now=TODAY)
        pr, _b, _h = self._open(
            {"requirements.txt": "alpha==1.0.0\n"},
            {"requirements.txt":
             "alpha==1.0.0\nvulnpkg==1.5.0\n"})
        review = self._store(advisories=evil) \
            .review_pull_request(
                self.owner, "volmarr", "pub", pr.number,
                now=TODAY)
        html = render_dependency_review(review)
        self.assertIn("New vulnerabilities", html)
        self.assertIn("CVE-3010-0007", html)
        self.assertIn("advisory snapshot dated 2026-11-10",
                      html)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        page = render_dependency_review_page(review)
        self.assertIn("<h1>", page)
        payload = review.to_dict()
        self.assertEqual(payload["check_context"],
                         "dependency-review")
        self.assertEqual(payload["check_state"], "failed")
        self.assertEqual(
            payload["new_vulnerabilities"][0]["advisory"],
            "CVE-3010-0007")


if __name__ == "__main__":
    unittest.main()
