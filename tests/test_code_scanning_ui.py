"""S-304 acceptance battery: code scanning alerts UI.

Acceptance (roadmap S-304): Code scanning alerts
UI -- alert list and detail with rule help,
locations, and dismissal reasons; PR annotations
for findings on changed lines.

The centre is samverk/code_scanning_ui.py over
S-303's alerts: the list and detail pages (rule
help lifted from the reporting upload's own SARIF
rule metadata, honestly absent where the upload
carried none; every location of the finding, not
only the first), a dismissal life modelled on
S-294 (closed kind set false_positive / wont_fix /
used_in_tests, a stated reason always recorded,
admin + maintain judged by S-190's engine, every
transition on the alert's own events record in
migration 125's rows, in the same transaction),
and PR annotations laid over S-145's files view of
S-104's diff -- a finding annotates exactly where
its line is a changed (added) line, never on an
unchanged one. Schema 124 to 125 moved in-slice;
taxonomy stands unmoved at 135 (33 auth / 89 repo /
13 admin) -- a dismissal is witnessed by its own
events table, as S-294's transitions are, and the
battery proves the audit log does not move.

Counted with: python3 -m unittest tests.test_code_scanning_ui
"""
from __future__ import annotations

import base64
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.code_scanning import CodeScanningAPI
from samverk.code_scanning_alerts import CodeScanningAlertsAPI
from samverk.code_scanning_ui import (
    ALERT_NOT_FOUND, CodeScanningUIStore, CodeScanningUIError,
    annotations_for_diff, changed_lines_by_path,
    decide_dismissal, dismissal_word, locations_for,
    render_alert_detail_page, render_alerts_page,
    render_annotations_page, rule_help_for,
    validate_dismissal, validate_reason)
from samverk.db import schema_version
from samverk.diff_engine import DiffFile, DiffLine, DiffSet
from samverk.fine_grained_tokens import FineTokenStore
from samverk.issues import IssueStore
from samverk.outside_collaborators import OutsideCollaboratorStore
from samverk.pull_requests import PullRequestStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
OID = "a" * 40
OID2 = "b" * 40

RULE = {
    "id": "CQ-1", "name": "dangerous-sink",
    "shortDescription": {"text": "Dangerous sink used."},
    "fullDescription": {"text": "A dangerous sink was "
                               "used with untrusted data."},
    "help": {"text": "Sanitise input before the sink."},
    "helpUri": "https://example.invalid/help/CQ-1",
}


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(
        f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def result(text="a finding", rule="CQ-1", uri="src/main.py",
           line=3, column=1, level="error", locations=None):
    if locations is None:
        locations = [{"physicalLocation": {
            "artifactLocation": {"uri": uri},
            "region": {"startLine": line,
                       "startColumn": column}}}]
    out = {"message": {"text": text}, "locations": locations}
    if rule is not None:
        out["ruleId"] = rule
    if level is not None:
        out["level"] = level
    return out


def location(uri, line, column=1):
    return {"physicalLocation": {
        "artifactLocation": {"uri": uri},
        "region": {"startLine": line, "startColumn": column}}}


def document(*results, rules=None, tool="CodeQL"):
    driver = {"name": tool}
    if rules is not None:
        driver["rules"] = rules
    return {"version": "2.1.0",
            "runs": [{"tool": {"driver": driver},
                      "results": list(results)}]}


def git(repo, *args, input_bytes=None):
    env = {"GIT_AUTHOR_NAME": "T", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "T",
           "GIT_COMMITTER_EMAIL": "t@t",
           "PATH": "/usr/bin:/bin"}
    out = subprocess.run(
        ["git", f"--git-dir={repo}", *args],
        capture_output=True, input=input_bytes, env=env)
    assert out.returncode == 0, out.stderr.decode()
    return out.stdout.decode().strip()


def build_tree(repo, files):
    lines = []
    dirs = {}
    for name in sorted(files):
        head, sep, rest = name.partition("/")
        if sep:
            dirs.setdefault(head, {})[rest] = files[name]
        else:
            blob = git(repo, "hash-object", "-w", "--stdin",
                       input_bytes=files[name].encode())
            lines.append(f"100644 blob {blob}\t{name}\n")
    for head in sorted(dirs):
        sub = build_tree(repo, dirs[head])
        lines.append(f"040000 tree {sub}\t{head}\n")
    return git(repo, "mktree",
               input_bytes="".join(lines).encode())


def make_commit(repo, parent, files, message):
    tree = build_tree(repo, files)
    args = ["commit-tree", tree]
    if parent:
        args += ["-p", parent]
    return git(repo, *args,
               input_bytes=(message + "\n").encode())


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    maintainer = accounts.register("yrsa", PW)
    writer = accounts.register("tess", PW)
    reader = accounts.register("runa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    pub = repos.create_repository(
        owner.id, "volmarr", "pub", visibility="public")
    priv = repos.create_repository(
        owner.id, "volmarr", "priv", visibility="private")
    grants = OutsideCollaboratorStore(
        conn, accounts, audit=audit, time_fn=clock)
    for repo in (pub, priv):
        grants.grant(owner.id, repo.id, "yrsa", "maintain")
        grants.grant(owner.id, repo.id, "tess", "write")
        grants.grant(owner.id, repo.id, "runa", "read")
    classic = AccessTokenStore(conn, accounts, audit=audit,
                               time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit,
                          time_fn=clock)
    expiry = clock.now + 3600
    _, owner_read = classic.create_token(
        owner.id, "read token", {"repo:read"}, expiry)
    _, owner_write = classic.create_token(
        owner.id, "write token", {"repo:write"}, expiry)
    uploads = CodeScanningAPI(conn, accounts, repos,
                              audit=audit, time_fn=clock)
    alerts = CodeScanningAlertsAPI(conn, accounts, repos,
                                   audit=audit, time_fn=clock)
    issues = IssueStore(conn, repos, accounts,
                        audit=audit, time_fn=clock)
    ui = CodeScanningUIStore(conn, repos, accounts,
                             issues=issues, audit=audit,
                             time_fn=clock)
    prs = PullRequestStore(conn, repos, accounts, issues,
                           audit=audit, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, maintainer=maintainer, writer=writer,
        reader=reader, stranger=stranger, repos=repos,
        uploads=uploads, alerts=alerts, ui=ui, prs=prs,
        issues=issues,
        owner_read=f"Bearer {owner_read}",
        owner_write=f"Bearer {owner_write}")


class WorldCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = make_world(Path(self.tmp.name))

    def make_alert(self, repo="pub", ref="refs/heads/main",
                   oid=OID, doc=None, **kw):
        if doc is None:
            doc = document(result(**kw), rules=[RULE])
        up = self.w.uploads.upload_sarif(
            self.w.owner_write, "volmarr", repo,
            {"oid": oid, "ref": ref, "sarif": doc})
        self.w.alerts.process_upload(
            self.w.owner_write, "volmarr", repo, up["id"])
        listed = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", repo)
        assert listed["total"] >= 1
        return listed["alerts"][0]["id"]

    def audit_count(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log"
        ).fetchone()["n"]


class PinsTest(WorldCase):
    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.w.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)


class PureLawTest(unittest.TestCase):
    def test_dismissal_vocabulary(self):
        self.assertEqual(dismissal_word("false_positive"),
                         "false positive")
        self.assertEqual(dismissal_word("wont_fix"), "won't fix")
        self.assertEqual(dismissal_word("used_in_tests"),
                         "used in tests")
        self.assertEqual(validate_dismissal("wont_fix"),
                         "wont_fix")
        for bad in ("bogus", "", None, 3):
            with self.assertRaises(CodeScanningUIError) as cm:
                validate_dismissal(bad)
            self.assertEqual(cm.exception.reason,
                             "dismissal_invalid")

    def test_reason_law(self):
        self.assertEqual(validate_reason("  said  "), "said")
        with self.assertRaises(CodeScanningUIError) as cm:
            validate_reason("   ")
        self.assertEqual(cm.exception.reason, "reason_required")
        with self.assertRaises(CodeScanningUIError) as cm:
            validate_reason("x" * 501)
        self.assertEqual(cm.exception.reason, "reason_too_long")

    def test_decide_order_state_before_rung(self):
        # A fixed alert refuses as not-open even for a
        # reader: the alert's own state is judged first.
        out = decide_dismissal(
            action="dismiss", role="read", actor="runa",
            full_name="volmarr/pub", alert_state="fixed",
            dismissal="wont_fix", reason="because")
        self.assertFalse(out.may_move)
        self.assertEqual(out.code, "code_scanning_alert_not_open")
        out = decide_dismissal(
            action="reopen", role="admin", actor="volmarr",
            full_name="volmarr/pub", alert_state="open",
            reason="because")
        self.assertEqual(out.code,
                         "code_scanning_alert_not_dismissed")

    def test_decide_rung_kind_reason(self):
        out = decide_dismissal(
            action="dismiss", role="write", actor="tess",
            full_name="volmarr/pub", alert_state="open",
            dismissal="wont_fix", reason="because")
        self.assertEqual(out.code, "dismissal_not_permitted")
        out = decide_dismissal(
            action="dismiss", role=None, actor=None,
            full_name="volmarr/pub", alert_state="open",
            dismissal="wont_fix", reason="because")
        self.assertEqual(out.code, "dismissal_not_permitted")
        out = decide_dismissal(
            action="dismiss", role="maintain", actor="yrsa",
            full_name="volmarr/pub", alert_state="open",
            dismissal="bogus", reason="because")
        self.assertEqual(out.code, "dismissal_invalid")
        out = decide_dismissal(
            action="dismiss", role="admin", actor="volmarr",
            full_name="volmarr/pub", alert_state="open",
            dismissal="false_positive", reason="")
        self.assertEqual(out.code, "reason_required")
        out = decide_dismissal(
            action="dismiss", role="maintain", actor="yrsa",
            full_name="volmarr/pub", alert_state="open",
            dismissal="used_in_tests", reason="fixture data")
        self.assertTrue(out.may_move)
        self.assertEqual(out.code, "")

    def test_rule_help_present_and_absent(self):
        doc = document(result(), rules=[RULE])
        help_found = rule_help_for(doc, "CodeQL", "CQ-1")
        self.assertTrue(help_found.present)
        self.assertEqual(help_found.name, "dangerous-sink")
        self.assertEqual(help_found.short_description,
                         "Dangerous sink used.")
        self.assertIn("Sanitise input", help_found.help_text)
        bare = rule_help_for(document(result()), "CodeQL", "CQ-1")
        self.assertFalse(bare.present)
        self.assertIn("No rule help was carried", bare.words())
        other = rule_help_for(doc, "CodeQL", "CQ-99")
        self.assertFalse(other.present)

    def test_locations_for_collects_every_location(self):
        doc = document(result(locations=[
            location("src/main.py", 3, 1),
            location("src/other.py", 9, 2),
            location("src/main.py", 3, 1)]), rules=[RULE])
        from samverk.code_scanning_alerts import (
            extract_findings)
        _, fingerprint, _ = extract_findings(doc)[0]
        places = locations_for(doc, fingerprint)
        self.assertEqual(
            [(p.uri, p.line) for p in places],
            [("src/main.py", 3), ("src/other.py", 9)])
        self.assertEqual(locations_for(doc, "0" * 64), ())

    def test_changed_lines_and_annotation_boundary(self):
        diff = DiffSet(files=(DiffFile(
            old_path="src/main.py", new_path="src/main.py",
            is_binary=False, additions=1, deletions=1,
            lines=(
                DiffLine("context", "one", 1, 1),
                DiffLine("del", "two", 2, None),
                DiffLine("add", "TWO", None, 2),
                DiffLine("context", "three", 3, 3),
                DiffLine("add", "four", None, 4))),))
        self.assertEqual(changed_lines_by_path(diff),
                         {"src/main.py": frozenset({2, 4})})

        class FakeAlert:
            def __init__(self, line, state="open"):
                self.id = line
                self.rule_id = "CQ-1"
                self.level = "error"
                self.message = "m"
                self.artifact_uri = "src/main.py"
                self.start_line = line
                self.branch = "feature"
                self.fingerprint = "f" * 64
                self.effective_state = state

        notes = annotations_for_diff(
            [FakeAlert(1), FakeAlert(2), FakeAlert(3),
             FakeAlert(4), FakeAlert(2, "dismissed"),
             FakeAlert(4, "fixed")], diff)
        self.assertEqual([n.line for n in notes], [2, 4])


class ListDetailTest(WorldCase):
    def test_list_counts_and_filters(self):
        first = self.make_alert()
        second_doc = document(
            result(),
            result(text="second", rule="CQ-2", line=9),
            rules=[RULE])
        second = self.make_alert(oid=OID2, doc=second_doc)
        views = self.w.ui.list_alerts(
            self.w.reader, "volmarr", "pub")
        self.assertEqual(len(views), 2)
        counts = self.w.ui.count_alerts(
            self.w.reader, "volmarr", "pub")
        self.assertEqual(counts, {"open": 2, "fixed": 0,
                                  "dismissed": 0, "total": 2})
        self.assertEqual(
            self.w.ui.list_alerts(
                self.w.reader, "volmarr", "pub",
                branch="dev"), ())
        self.w.ui.dismiss_alert(
            self.w.maintainer, "volmarr", "pub", first,
            dismissal="wont_fix", reason="accepted risk")
        counts = self.w.ui.count_alerts(
            self.w.reader, "volmarr", "pub")
        self.assertEqual(counts, {"open": 1, "fixed": 0,
                                  "dismissed": 1, "total": 2})
        dismissed = self.w.ui.list_alerts(
            self.w.reader, "volmarr", "pub", state="dismissed")
        self.assertEqual([v.id for v in dismissed], [first])
        views = self.w.ui.list_alerts(
            self.w.reader, "volmarr", "pub")
        page = render_alerts_page(
            views, "volmarr/pub",
            self.w.ui.count_alerts(self.w.reader,
                                   "volmarr", "pub"))
        self.assertIn("1 dismissed", page)
        self.assertIn("dismissed as won", page)

    def test_detail_help_locations_history(self):
        doc = document(result(locations=[
            location("src/main.py", 3, 1),
            location("src/other.py", 9, 2)]), rules=[RULE])
        alert_id = self.make_alert(doc=doc)
        detail = self.w.ui.alert_detail(
            self.w.reader, "volmarr", "pub", alert_id)
        self.assertTrue(detail.rule_help.present)
        self.assertEqual(
            [(p.uri, p.line) for p in detail.locations],
            [("src/main.py", 3), ("src/other.py", 9)])
        self.assertIn("First reported by upload",
                      detail.history[0])
        page = render_alert_detail_page(detail)
        self.assertIn("Sanitise input before the sink.", page)
        self.assertIn("src/other.py line 9", page)
        self.assertIn("structural basis", page)
        self.assertIn("No dismissals or reopenings yet.", page)

    def test_detail_help_absent_is_said(self):
        alert_id = self.make_alert(
            doc=document(result(rule="CQ-7")))
        detail = self.w.ui.alert_detail(
            self.w.reader, "volmarr", "pub", alert_id)
        self.assertFalse(detail.rule_help.present)
        page = render_alert_detail_page(detail)
        self.assertIn("No rule help was carried", page)

    def test_rendering_escapes(self):
        alert_id = self.make_alert(
            text="<script>alert(1)</script>")
        views = self.w.ui.list_alerts(
            self.w.owner, "volmarr", "pub")
        page = render_alerts_page(views, "volmarr/pub")
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("&lt;script&gt;", page)
        detail = self.w.ui.alert_detail(
            self.w.owner, "volmarr", "pub", alert_id)
        page = render_alert_detail_page(detail)
        self.assertNotIn("<script>alert(1)</script>", page)
        self.assertIn("is open", page)

    def test_read_faces(self):
        alert_id = self.make_alert(repo="priv")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.list_alerts(
                self.w.stranger, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.list_alerts(
                self.w.stranger, "volmarr", "nosuch")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.get_alert(
                self.w.reader, "volmarr", "priv", 4242)
        self.assertEqual(cm.exception.reason, ALERT_NOT_FOUND)
        got = self.w.ui.get_alert(
            self.w.reader, "volmarr", "priv", alert_id)
        self.assertEqual(got.id, alert_id)


class DismissalTest(WorldCase):
    def test_full_lifecycle_and_audit_snapshot(self):
        alert_id = self.make_alert()
        before = self.audit_count()
        moved = self.w.ui.dismiss_alert(
            self.w.maintainer, "volmarr", "pub", alert_id,
            dismissal="false_positive",
            reason="the sink is a test double")
        self.assertEqual(moved.effective_state, "dismissed")
        self.assertEqual(moved.dismissal, "false_positive")
        self.assertEqual(moved.dismissed_by, "yrsa")
        self.assertIn("dismissed as false positive",
                      moved.state_words())
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.dismiss_alert(
                self.w.owner, "volmarr", "pub", alert_id,
                dismissal="wont_fix", reason="again")
        self.assertEqual(
            cm.exception.reason,
            "code_scanning_alert_already_dismissed")
        reopened = self.w.ui.reopen_alert(
            self.w.owner, "volmarr", "pub", alert_id,
            reason="the double escaped into prod")
        self.assertEqual(reopened.effective_state, "open")
        self.assertIsNone(reopened.to_dict()["dismissal"])
        again = self.w.ui.dismiss_alert(
            self.w.owner, "volmarr", "pub", alert_id,
            dismissal="used_in_tests", reason="fixture only")
        self.assertEqual(again.dismissal, "used_in_tests")
        events = self.w.ui.list_events(
            self.w.reader, "volmarr", "pub", alert_id)
        self.assertEqual([e.action for e in events],
                         ["dismiss", "reopen", "dismiss"])
        self.assertEqual(events[0].from_state, "open")
        self.assertEqual(events[0].to_state, "dismissed")
        self.assertEqual(events[1].to_state, "open")
        self.assertEqual(self.audit_count(), before)

    def test_refusals(self):
        alert_id = self.make_alert()
        for actor, code in (
                (self.w.writer, "dismissal_not_permitted"),
                (self.w.reader, "dismissal_not_permitted"),
                (None, "dismissal_not_permitted")):
            with self.assertRaises(CodeScanningUIError) as cm:
                self.w.ui.dismiss_alert(
                    actor, "volmarr", "pub", alert_id,
                    dismissal="wont_fix", reason="because")
            self.assertEqual(cm.exception.reason, code)
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.dismiss_alert(
                self.w.owner, "volmarr", "pub", alert_id,
                dismissal="bogus", reason="because")
        self.assertEqual(cm.exception.reason,
                         "dismissal_invalid")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.dismiss_alert(
                self.w.owner, "volmarr", "pub", alert_id,
                dismissal="wont_fix", reason=" ")
        self.assertEqual(cm.exception.reason, "reason_required")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.reopen_alert(
                self.w.owner, "volmarr", "pub", alert_id,
                reason="not dismissed")
        self.assertEqual(
            cm.exception.reason,
            "code_scanning_alert_not_dismissed")
        # Nothing moved.
        view = self.w.ui.get_alert(
            self.w.owner, "volmarr", "pub", alert_id)
        self.assertEqual(view.effective_state, "open")
        self.assertEqual(self.w.ui.list_events(
            self.w.owner, "volmarr", "pub", alert_id), ())

    def test_dismiss_fixed_refused(self):
        alert_id = self.make_alert()
        empty = self.w.uploads.upload_sarif(
            self.w.owner_write, "volmarr", "pub",
            {"oid": OID2, "ref": "refs/heads/main",
             "sarif": document(
                 result(text="other", rule="CQ-9"))})
        self.w.alerts.process_upload(
            self.w.owner_write, "volmarr", "pub", empty["id"])
        view = self.w.ui.get_alert(
            self.w.owner, "volmarr", "pub", alert_id)
        self.assertEqual(view.state, "fixed")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.dismiss_alert(
                self.w.owner, "volmarr", "pub", alert_id,
                dismissal="wont_fix", reason="because")
        self.assertEqual(cm.exception.reason,
                         "code_scanning_alert_not_open")

    def test_judge_writes_nothing(self):
        alert_id = self.make_alert()
        before_audit = self.audit_count()
        before = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM"
            " code_scanning_alert_events").fetchone()["n"]
        decision = self.w.ui.judge(
            self.w.maintainer, "volmarr", "pub", alert_id,
            action="dismiss", dismissal="wont_fix",
            reason="accepted")
        self.assertTrue(decision.may_move)
        after = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM"
            " code_scanning_alert_events").fetchone()["n"]
        self.assertEqual(before, after)
        self.assertEqual(self.audit_count(), before_audit)
        view = self.w.ui.get_alert(
            self.w.owner, "volmarr", "pub", alert_id)
        self.assertEqual(view.effective_state, "open")


class PrAnnotationTest(WorldCase):
    def _repo_with_pr(self, repo="pub"):
        path = self.w.repos.path_for("volmarr", repo)
        base = make_commit(
            path, None,
            {"src/main.py": "one\ntwo\nthree\n"}, "base")
        git(path, "update-ref", "refs/heads/main", base)
        head = make_commit(
            path, base,
            {"src/main.py": "one\nTWO\nthree\nfour\n"},
            "feature work")
        git(path, "update-ref", "refs/heads/feature", head)
        return self.w.prs.create_pull_request(
            self.w.owner, "volmarr", repo,
            base_branch="main", head_branch="feature")

    def _feature_alerts(self, repo="pub"):
        doc = document(
            result(text="on context", rule="CQ-1", line=1),
            result(text="on changed", rule="CQ-2", line=2),
            result(text="on added", rule="CQ-3", line=4),
            result(text="off diff file", rule="CQ-4",
                   uri="src/other.py", line=2),
            rules=[RULE])
        up = self.w.uploads.upload_sarif(
            self.w.owner_write, "volmarr", repo,
            {"oid": OID, "ref": "refs/heads/feature",
             "sarif": doc})
        self.w.alerts.process_upload(
            self.w.owner_write, "volmarr", repo, up["id"])

    def test_annotations_only_on_changed_lines(self):
        pr = self._repo_with_pr()
        self._feature_alerts()
        notes = self.w.ui.pr_annotations(
            self.w.owner, "volmarr", "pub", pr.number)
        self.assertEqual(
            [(n.path, n.line) for n in notes],
            [("src/main.py", 2), ("src/main.py", 4)])
        page = render_annotations_page(
            notes, "volmarr/pub", pr.number)
        self.assertIn("changed line 2", page)
        # Dismissing the line-2 alert removes its note.
        views = self.w.ui.list_alerts(
            self.w.owner, "volmarr", "pub", branch="feature")
        target = [v for v in views
                  if v.start_line == 2
                  and v.artifact_uri == "src/main.py"][0]
        self.w.ui.dismiss_alert(
            self.w.owner, "volmarr", "pub", target.id,
            dismissal="false_positive", reason="not real")
        notes = self.w.ui.pr_annotations(
            self.w.owner, "volmarr", "pub", pr.number)
        self.assertEqual([(n.path, n.line) for n in notes],
                         [("src/main.py", 4)])

    def test_annotations_private_face(self):
        pr = self._repo_with_pr(repo="priv")
        self._feature_alerts(repo="priv")
        with self.assertRaises(CodeScanningUIError) as cm:
            self.w.ui.pr_annotations(
                self.w.stranger, "volmarr", "priv", pr.number)
        self.assertEqual(cm.exception.reason,
                         "pull_request_not_found")
        # The pull-request seam's own door (S-054) is
        # what annotations inherit: the owner reads;
        # the S-191 read grant does not widen that
        # older seam, and this battery invents none.
        notes = self.w.ui.pr_annotations(
            self.w.owner, "volmarr", "priv", pr.number)
        self.assertEqual(len(notes), 2)


if __name__ == "__main__":
    unittest.main()
