"""S-303 acceptance battery: SARIF fingerprinting and dedup.

Acceptance (roadmap S-303): SARIF fingerprinting
and dedup -- the same finding across runs is one
alert; new/fixed transitions computed per branch.

The centre is samverk/code_scanning_alerts.py:
the pure extract_findings lifts every SARIF
result into a finding, fingerprint_finding names
it across runs (the scanner's partialFingerprints
where supplied, basis partial; the structural
shape otherwise, basis structural), and
CodeScanningAlertsAPI.process_upload settles one
stored S-302 upload against its branch's alerts
through S-238's door judged by S-190 (write to
process, read to fetch, a missing or unreadable
repository the one repo_not_found) -- new,
reopened, still-open and fixed transitions in
migration 124's rows, in upload order per branch,
an older upload refused
code_scanning_stale_upload. Schema 123 to 124
moved in-slice; taxonomy stands unmoved at 135
(33 auth / 89 repo / 13 admin) -- alerts are
derived data and carry no audit verb.

Counted with: python3 -m unittest tests.test_code_scanning_alerts
"""
from __future__ import annotations

import base64
import json
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
from samverk.api_contract import PROBLEM_FIELDS
from samverk.audit import AuditLog
from samverk.code_scanning import CodeScanningAPI
from samverk.code_scanning_alerts import (
    ALERT_STATES, CODE_SCANNING_ALERTS_API_PATH, Finding,
    CodeScanningAlertsAPI, CodeScanningAlertsError,
    alert_to_dict, branch_of, compute_transitions,
    error_to_dict, extract_findings, fingerprint_finding,
    render_alert, render_code_scanning_alerts_page)
from samverk.db import schema_version
from samverk.error_shape import is_registered_reason
from samverk.fine_grained_tokens import FineTokenStore
from samverk.repositories import RepositoryStore

PW = "correct horse battery"
OID = "a" * 40
OID2 = "b" * 40
OID3 = "c" * 40
OID4 = "d" * 40


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now

    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(
        f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    repos.create_repository(owner.id, "volmarr", "pub",
                            visibility="public")
    repos.create_repository(owner.id, "volmarr", "priv",
                            visibility="private")
    classic = AccessTokenStore(conn, accounts, audit=audit,
                               time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit,
                          time_fn=clock)
    expiry = clock.now + 3600
    _, owner_read = classic.create_token(
        owner.id, "read token", {"repo:read"}, expiry)
    _, owner_write = classic.create_token(
        owner.id, "write token", {"repo:write"}, expiry)
    _, reader_read = classic.create_token(
        reader.id, "reader read", {"repo:read"}, expiry)
    uploads = CodeScanningAPI(conn, accounts, repos,
                              audit=audit, time_fn=clock)
    alerts = CodeScanningAlertsAPI(conn, accounts, repos,
                                   audit=audit, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger,
        repos=repos, uploads=uploads, alerts=alerts,
        owner_basic=basic("volmarr", PW),
        owner_read=f"Bearer {owner_read}",
        owner_write=f"Bearer {owner_write}",
        reader_read=f"Bearer {reader_read}")


def result(text="a finding", rule="CQ-1", uri="src/main.py",
           line=3, column=1, level="error", partial=None):
    out = {"message": {"text": text},
           "locations": [{"physicalLocation": {
               "artifactLocation": {"uri": uri},
               "region": {"startLine": line,
                          "startColumn": column}}}]}
    if rule is not None:
        out["ruleId"] = rule
    if level is not None:
        out["level"] = level
    if partial is not None:
        out["partialFingerprints"] = partial
    return out


def document(*results, tool="CodeQL"):
    return {"version": "2.1.0",
            "runs": [{"tool": {"driver": {"name": tool}},
                      "results": list(results)}]}


def finding(**kw):
    base = dict(tool_name="CodeQL", rule_id="CQ-1",
                level="error", message="a finding",
                artifact_uri="src/main.py", start_line=3,
                start_column=1, partial=())
    base.update(kw)
    return Finding(**base)


class PinsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = make_world(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.w.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)

    def test_reasons_registered(self):
        self.assertTrue(
            is_registered_reason("code_scanning_alert_not_found"))
        self.assertTrue(
            is_registered_reason("code_scanning_stale_upload"))
        self.assertTrue(
            is_registered_reason("code_scanning_not_found"))

    def test_states_and_path(self):
        self.assertEqual(ALERT_STATES, ("open", "fixed"))
        self.assertIn("code-scanning/alerts",
                      CODE_SCANNING_ALERTS_API_PATH)


class PureLawTest(unittest.TestCase):
    def test_branch_of(self):
        self.assertEqual(branch_of("refs/heads/main"), "main")
        self.assertEqual(branch_of("main"), "main")
        self.assertEqual(branch_of("refs/heads/dev/x"), "dev/x")
        self.assertEqual(branch_of(""), "")
        self.assertEqual(branch_of(None), "")

    def test_partial_basis_ignores_line_moves(self):
        a = finding(partial=(("primary", "abc"),), start_line=3)
        b = finding(partial=(("primary", "abc"),), start_line=99)
        fa, ba = fingerprint_finding(a)
        fb, bb = fingerprint_finding(b)
        self.assertEqual((ba, bb), ("partial", "partial"))
        self.assertEqual(fa, fb)

    def test_structural_basis_tracks_the_shape(self):
        a = finding()
        same = finding()
        moved = finding(start_line=99)
        other_rule = finding(rule_id="CQ-2")
        fa, ba = fingerprint_finding(a)
        self.assertEqual(ba, "structural")
        self.assertEqual(fa, fingerprint_finding(same)[0])
        self.assertNotEqual(fa, fingerprint_finding(moved)[0])
        self.assertNotEqual(fa, fingerprint_finding(other_rule)[0])
        self.assertEqual(len(fa), 64)

    def test_extract_defaults_and_dedup(self):
        doc = document(
            result(), result(),
            {"message": {"id": "m-1"}},
            tool="CodeQL")
        found = extract_findings(doc)
        self.assertEqual(len(found), 2)
        bare = [f for f, _, _ in found if f.message == "m-1"]
        self.assertEqual(len(bare), 1)
        self.assertEqual(bare[0].rule_id, "")
        self.assertEqual(bare[0].level, "warning")
        self.assertEqual(bare[0].artifact_uri, "")
        self.assertEqual(bare[0].start_line, 0)

    def test_compute_transitions(self):
        out = compute_transitions({"a", "b"}, {"b", "c"})
        self.assertEqual(out, {"appeared": ["c"],
                               "still_open": ["b"],
                               "fixed": ["a"]})


class FlowTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = make_world(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def upload(self, oid, doc, ref="refs/heads/main",
               repo="pub", header=None):
        return self.w.uploads.upload_sarif(
            header or self.w.owner_write, "volmarr", repo,
            {"oid": oid, "ref": ref, "sarif": doc})

    def process(self, upload_id, repo="pub", header=None):
        return self.w.alerts.process_upload(
            header or self.w.owner_write, "volmarr", repo,
            upload_id)

    def test_first_process_opens_alerts(self):
        up = self.upload(OID, document(result(), result(
            text="second", rule="CQ-2", line=9)))
        out = self.process(up["id"])
        self.assertEqual(out["branch"], "main")
        self.assertEqual(out["findings"], 2)
        self.assertEqual(out["duplicates_collapsed"], 0)
        self.assertEqual(len(out["new"]), 2)
        self.assertEqual(out["fixed"], [])
        self.assertEqual(out["open_alerts"], 2)
        listed = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub")
        self.assertEqual(listed["total"], 2)
        one = listed["alerts"][0]
        self.assertEqual(list(one.keys()), [
            "id", "branch", "fingerprint", "basis", "tool",
            "rule_id", "level", "message", "artifact_uri",
            "start_line", "start_column", "state",
            "first_seen_upload", "first_seen_oid",
            "last_seen_upload", "last_seen_oid",
            "fixed_upload", "fixed_oid", "times_seen",
            "times_fixed", "created_at", "updated_at"])
        self.assertEqual(one["state"], "open")
        self.assertEqual(one["first_seen_oid"], OID)
        self.assertEqual(one["times_seen"], 1)

    def test_duplicate_results_collapse(self):
        up = self.upload(OID, document(result(), result()))
        out = self.process(up["id"])
        self.assertEqual(out["findings"], 1)
        self.assertEqual(out["duplicates_collapsed"], 1)
        self.assertEqual(len(out["new"]), 1)

    def test_new_still_fixed_across_runs(self):
        first = self.upload(OID, document(
            result(), result(text="second", rule="CQ-2")))
        self.process(first["id"])
        second = self.upload(OID2, document(
            result(), result(text="third", rule="CQ-3")))
        out = self.process(second["id"])
        self.assertEqual(len(out["still_open"]), 1)
        self.assertEqual(len(out["new"]), 1)
        self.assertEqual(len(out["fixed"]), 1)
        self.assertEqual(out["open_alerts"], 2)
        fixed = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub",
            state="fixed")
        self.assertEqual(fixed["total"], 1)
        self.assertEqual(fixed["alerts"][0]["rule_id"], "CQ-2")
        self.assertEqual(fixed["alerts"][0]["fixed_oid"], OID2)
        self.assertEqual(
            fixed["alerts"][0]["fixed_upload"], second["id"])

    def test_fixed_finding_reopens(self):
        first = self.upload(OID, document(result()))
        self.process(first["id"])
        second = self.upload(OID2, document(
            result(text="other", rule="CQ-9")))
        self.process(second["id"])
        third = self.upload(OID3, document(result()))
        out = self.process(third["id"])
        self.assertEqual(len(out["reopened"]), 1)
        self.assertEqual(len(out["fixed"]), 1)
        alert = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub",
            branch="main")["alerts"]
        reopened = [a for a in alert if a["rule_id"] == "CQ-1"]
        self.assertEqual(reopened[0]["state"], "open")
        self.assertEqual(reopened[0]["times_fixed"], 1)
        self.assertIsNone(reopened[0]["fixed_upload"])

    def test_transitions_are_per_branch(self):
        main_up = self.upload(OID, document(result()))
        self.process(main_up["id"])
        dev_up = self.upload(OID2, document(result()),
                             ref="refs/heads/dev")
        out = self.process(dev_up["id"])
        self.assertEqual(len(out["new"]), 1)
        main_empty = self.upload(OID3, document(
            result(text="other", rule="CQ-9")))
        out = self.process(main_empty["id"])
        self.assertEqual(len(out["fixed"]), 1)
        dev = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub", branch="dev")
        self.assertEqual(dev["total"], 1)
        self.assertEqual(dev["alerts"][0]["state"], "open")

    def test_refless_uploads_group_together(self):
        up = self.upload(OID, document(result()), ref="")
        out = self.process(up["id"])
        self.assertEqual(out["branch"], "")
        listed = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub", branch="")
        self.assertEqual(listed["total"], 1)

    def test_reprocessing_head_is_idempotent(self):
        up = self.upload(OID, document(result()))
        self.process(up["id"])
        again = self.process(up["id"])
        self.assertEqual(again["new"], [])
        self.assertEqual(again["fixed"], [])
        self.assertEqual(len(again["still_open"]), 1)
        alert = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub")["alerts"][0]
        self.assertEqual(alert["times_seen"], 1)

    def test_stale_upload_refused(self):
        first = self.upload(OID, document(result()))
        second = self.upload(OID2, document(result()))
        self.process(first["id"])
        self.process(second["id"])
        with self.assertRaises(CodeScanningAlertsError) as cm:
            self.process(first["id"])
        self.assertEqual(cm.exception.reason,
                         "code_scanning_stale_upload")
        err = error_to_dict(cm.exception)
        self.assertEqual(set(err.keys()), set(PROBLEM_FIELDS))
        self.assertEqual(err["status"], 409)

    def test_missing_upload_refused(self):
        with self.assertRaises(CodeScanningAlertsError) as cm:
            self.process(9999)
        self.assertEqual(cm.exception.reason,
                         "code_scanning_not_found")

    def test_partial_fingerprint_survives_move(self):
        first = self.upload(OID, document(result(
            partial={"primary": "abc"})))
        self.process(first["id"])
        second = self.upload(OID2, document(result(
            line=42, partial={"primary": "abc"})))
        out = self.process(second["id"])
        self.assertEqual(len(out["still_open"]), 1)
        self.assertEqual(out["new"], [])
        alert = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub")["alerts"][0]
        self.assertEqual(alert["basis"], "partial")
        self.assertEqual(alert["start_line"], 42)

    def test_get_alert_and_missing(self):
        up = self.upload(OID, document(result()))
        self.process(up["id"])
        listed = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub")
        got = self.w.alerts.get_alert(
            self.w.owner_read, "volmarr", "pub",
            listed["alerts"][0]["id"])
        self.assertEqual(got["fingerprint"],
                         listed["alerts"][0]["fingerprint"])
        with self.assertRaises(CodeScanningAlertsError) as cm:
            self.w.alerts.get_alert(
                self.w.owner_read, "volmarr", "pub", 4242)
        self.assertEqual(cm.exception.reason,
                         "code_scanning_alert_not_found")

    def test_bad_state_filter_refused(self):
        with self.assertRaises(CodeScanningAlertsError) as cm:
            self.w.alerts.list_alerts(
                self.w.owner_read, "volmarr", "pub",
                state="dismissed")
        self.assertEqual(cm.exception.reason, "payload_invalid")

    def test_process_audits_nothing(self):
        before = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        up = self.upload(OID, document(result()))
        mid = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(mid, before + 1)
        self.process(up["id"])
        after = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]
        self.assertEqual(after, mid)


class DoorTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = make_world(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_process_needs_write(self):
        up = self.w.uploads.upload_sarif(
            self.w.owner_write, "volmarr", "pub",
            {"oid": OID, "ref": "main", "sarif": document(result())})
        with self.assertRaises(CodeScanningAlertsError):
            self.w.alerts.process_upload(
                self.w.owner_read, "volmarr", "pub", up["id"])

    def test_private_repo_uniform_not_found(self):
        up = self.w.uploads.upload_sarif(
            self.w.owner_write, "volmarr", "priv",
            {"oid": OID, "ref": "main", "sarif": document(result())})
        self.w.alerts.process_upload(
            self.w.owner_write, "volmarr", "priv", up["id"])
        with self.assertRaises(CodeScanningAlertsError) as cm:
            self.w.alerts.list_alerts(
                self.w.reader_read, "volmarr", "priv")
        self.assertEqual(cm.exception.reason, "repo_not_found")
        with self.assertRaises(CodeScanningAlertsError) as cm:
            self.w.alerts.list_alerts(
                self.w.reader_read, "volmarr", "nosuch")
        self.assertEqual(cm.exception.reason, "repo_not_found")


class RenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.w = make_world(Path(self.tmp.name))

    def tearDown(self):
        self.tmp.cleanup()

    def test_render_escapes_and_speaks(self):
        up = self.w.uploads.upload_sarif(
            self.w.owner_write, "volmarr", "pub",
            {"oid": OID, "ref": "main", "sarif": document(
                result(text="<script>alert(1)</script>"))})
        self.w.alerts.process_upload(
            self.w.owner_write, "volmarr", "pub", up["id"])
        listed = self.w.alerts.list_alerts(
            self.w.owner_read, "volmarr", "pub")
        from samverk.code_scanning_alerts import (
            CodeScanningAlert)
        record = CodeScanningAlert(
            id=listed["alerts"][0]["id"], repo_id=1,
            branch="main",
            fingerprint=listed["alerts"][0]["fingerprint"],
            basis="structural", tool_name="CodeQL",
            rule_id="CQ-1", level="error",
            message="<script>alert(1)</script>",
            artifact_uri="src/main.py", start_line=3,
            start_column=1, state="open",
            first_seen_upload_id=up["id"],
            first_seen_oid=OID,
            last_seen_upload_id=up["id"],
            last_seen_oid=OID, fixed_upload_id=None,
            fixed_oid="", times_seen=1, times_fixed=0,
            created_at=1, updated_at=1)
        html = render_alert(record)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("is open", html)
        page = render_code_scanning_alerts_page()
        self.assertIn("partial fingerprints", page)


if __name__ == "__main__":
    unittest.main()
