"""S-302 acceptance battery: code scanning ingestion.

Acceptance (roadmap S-302): Code scanning ingestion
-- SARIF uploads via API, validated against the
SARIF schema, stored per commit.

The centre is samverk/code_scanning.py: uploads
arrive through S-238's door judged by S-190 (write
to post, read to fetch, a missing or unreadable
repository the one repo_not_found), the document is
judged whole by the pure sarif_problems against the
SARIF 2.1.0 structure before anything is stored --
a refusal stores nothing and audits nothing -- and
an accepted upload lands as one row in migration
123's code_scanning_uploads, keyed by the commit it
names, witnessed by exactly one
repo.code_scanning.upload. Schema 122 to 123 and
taxonomy 134 to 135 (33 auth / 89 repo / 13 admin)
moved in-slice; the webhook taxonomy carries the
new verb in the checks category, at repository
scope.

Counted with: python3 -m unittest tests.test_code_scanning
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
from samverk.audit import AuditLog, verify_chain
from samverk.code_scanning import (
    CODE_SCANNING_API_PATH, LEVELS, MAX_RUNS_PER_UPLOAD,
    MAX_SARIF_BYTES, SARIF_VERSION, CodeScanningAPI,
    CodeScanningError, render_code_scanning_page,
    render_upload, sarif_problems, summarise_sarif,
    upload_to_dict, validate_upload_payload)
from samverk.db import schema_version
from samverk.error_shape import is_registered_reason
from samverk.fine_grained_tokens import FineTokenStore
from samverk.api_contract import PROBLEM_FIELDS
from samverk.code_scanning import error_to_dict
from samverk.repositories import RepositoryStore
from samverk.webhook_events import (
    audit_webhook_events, get_webhook_event)

PW = "correct horse battery"
OID = "a" * 40
OID2 = "b" * 40


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
    api = CodeScanningAPI(conn, accounts, repos,
                          audit=audit, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger,
        repos=repos, api=api,
        owner_read=f"Bearer {owner_read}",
        owner_write=f"Bearer {owner_write}",
        reader_read=f"Bearer {reader_read}")


def result(level="error", text="a finding", rule="CQ-1"):
    out = {"message": {"text": text},
           "locations": [{"physicalLocation": {
               "artifactLocation": {"uri": "src/main.py"},
               "region": {"startLine": 3}}}]}
    if rule is not None:
        out["ruleId"] = rule
    if level is not None:
        out["level"] = level
    return out


def valid_sarif(**overrides):
    doc = {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {"driver": {
                "name": "CodeQL", "version": "2.15.0",
                "rules": [{"id": "CQ-1"}]}},
            "results": [result(), result(level=None),
                        result(level="note", text="a note")],
        }],
    }
    doc.update(overrides)
    return doc


def payload(oid=OID, doc=None, ref="refs/heads/main"):
    return {"oid": oid, "ref": ref,
            "sarif": valid_sarif() if doc is None else doc}


def audit_actions(w):
    return [r["action"] for r in w.conn.execute(
        "SELECT action FROM audit_log ORDER BY seq")]


class SarifProblemsTests(unittest.TestCase):
    def test_valid_document_has_no_problems(self):
        self.assertEqual(sarif_problems(valid_sarif()), ())

    def test_non_object_document(self):
        self.assertEqual(sarif_problems([1, 2]),
                         ("the document is not a JSON object",))
        self.assertEqual(sarif_problems("x"),
                         ("the document is not a JSON object",))

    def test_version_must_be_sarif_210(self):
        doc = valid_sarif()
        del doc["version"]
        self.assertIn("version is not '2.1.0'",
                      sarif_problems(doc))
        self.assertIn("version is not '2.1.0'",
                      sarif_problems(valid_sarif(version="2.0.0")))
        self.assertEqual(SARIF_VERSION, "2.1.0")

    def test_schema_must_be_a_string_when_present(self):
        self.assertTrue(any(
            "$schema" in p
            for p in sarif_problems(valid_sarif(**{"$schema": 5}))))

    def test_runs_required_nonempty_and_capped(self):
        doc = valid_sarif()
        del doc["runs"]
        self.assertTrue(any("runs is missing" in p
                            for p in sarif_problems(doc)))
        self.assertTrue(any("runs is empty" in p
                            for p in sarif_problems(
                                valid_sarif(runs=[]))))
        big = [{"tool": {"driver": {"name": "T"}}}]
        doc = valid_sarif(
            runs=big * (MAX_RUNS_PER_UPLOAD + 1))
        self.assertTrue(any("more than" in p
                            for p in sarif_problems(doc)))

    def test_run_tool_driver_name_required(self):
        for runs in ([{}], [{"tool": {}}],
                     [{"tool": {"driver": {}}}],
                     [{"tool": {"driver": {"name": "  "}}}]):
            problems = sarif_problems(valid_sarif(runs=runs))
            self.assertTrue(problems, runs)
        problems = sarif_problems(valid_sarif(runs=["x"]))
        self.assertIn("runs[0] is not an object", problems)

    def test_results_shape_and_message_required(self):
        run = {"tool": {"driver": {"name": "T"}},
               "results": "nope"}
        self.assertTrue(any("results is not an array" in p
                            for p in sarif_problems(
                                valid_sarif(runs=[run]))))
        run = {"tool": {"driver": {"name": "T"}},
               "results": [{"ruleId": "X"}]}
        problems = sarif_problems(valid_sarif(runs=[run]))
        self.assertTrue(any("message is missing" in p
                            for p in problems))
        run = {"tool": {"driver": {"name": "T"}},
               "results": [{"message": {"text": " "}}]}
        problems = sarif_problems(valid_sarif(runs=[run]))
        self.assertTrue(any("neither a text nor an id" in p
                            for p in problems))
        run = {"tool": {"driver": {"name": "T"}},
               "results": [{"message": {"id": "m1"}}]}
        self.assertEqual(sarif_problems(valid_sarif(runs=[run])),
                         ())

    def test_level_vocabulary(self):
        for level in LEVELS:
            run = {"tool": {"driver": {"name": "T"}},
                   "results": [result(level=level)]}
            self.assertEqual(
                sarif_problems(valid_sarif(runs=[run])), ())
        run = {"tool": {"driver": {"name": "T"}},
               "results": [result(level="fatal")]}
        self.assertTrue(any("level is not one of" in p
                            for p in sarif_problems(
                                valid_sarif(runs=[run]))))

    def test_locations_must_be_location_objects(self):
        bad = result()
        bad["locations"] = "here"
        run = {"tool": {"driver": {"name": "T"}}, "results": [bad]}
        self.assertTrue(any("locations is not an array" in p
                            for p in sarif_problems(
                                valid_sarif(runs=[run]))))
        bad = result()
        bad["locations"] = [42]
        run = {"tool": {"driver": {"name": "T"}}, "results": [bad]}
        self.assertTrue(any("is not an object" in p
                            for p in sarif_problems(
                                valid_sarif(runs=[run]))))

    def test_unknown_properties_are_carried(self):
        doc = valid_sarif()
        doc["inlineExternalProperties"] = [{"anything": True}]
        doc["runs"][0]["brandNewField"] = {"x": 1}
        doc["runs"][0]["results"][0]["futureField"] = [1]
        self.assertEqual(sarif_problems(doc), ())

    def test_summary_counts_tools_runs_results_levels(self):
        doc = valid_sarif()
        doc["runs"].append({
            "tool": {"driver": {"name": "Bandit"}},
            "results": [result(level="error")]})
        summary = summarise_sarif(doc)
        self.assertEqual(summary.tool_names, ("CodeQL", "Bandit"))
        self.assertEqual(summary.run_count, 2)
        self.assertEqual(summary.result_count, 4)
        # error, level-less (SARIF default warning), note, error
        self.assertEqual(summary.level_counts,
                         {"error": 2, "warning": 1, "note": 1})


class PayloadTests(unittest.TestCase):
    def test_payload_must_be_object_with_known_keys(self):
        with self.assertRaises(CodeScanningError) as caught:
            validate_upload_payload("nope")
        self.assertEqual(caught.exception.reason, "payload_invalid")
        bad = payload()
        bad["extra"] = 1
        with self.assertRaises(CodeScanningError) as caught:
            validate_upload_payload(bad)
        self.assertEqual(caught.exception.reason, "payload_invalid")

    def test_oid_required(self):
        for bad in (payload(oid=""), payload(oid="  "),
                    {"ref": "", "sarif": valid_sarif()}):
            with self.assertRaises(CodeScanningError) as caught:
                validate_upload_payload(bad)
            self.assertEqual(caught.exception.reason,
                             "check_head_invalid")

    def test_sarif_may_arrive_as_json_text(self):
        report = validate_upload_payload(
            {"oid": OID, "sarif": json.dumps(valid_sarif())})
        self.assertEqual(report["summary"].run_count, 1)
        with self.assertRaises(CodeScanningError) as caught:
            validate_upload_payload({"oid": OID, "sarif": "{no"})
        self.assertEqual(caught.exception.reason, "sarif_invalid")
        with self.assertRaises(CodeScanningError) as caught:
            validate_upload_payload({"oid": OID})
        self.assertEqual(caught.exception.reason, "sarif_invalid")

    def test_invalid_document_refused_with_problems_named(self):
        doc = valid_sarif(version="1.0.0", runs=[])
        with self.assertRaises(CodeScanningError) as caught:
            validate_upload_payload({"oid": OID, "sarif": doc})
        self.assertEqual(caught.exception.reason, "sarif_invalid")
        self.assertIn("version is not", str(caught.exception))
        self.assertIn("runs is empty", str(caught.exception))

    def test_oversized_document_refused(self):
        doc = valid_sarif()
        doc["runs"][0]["tool"]["driver"]["informationUri"] = (
            "x" * (MAX_SARIF_BYTES + 1))
        with self.assertRaises(CodeScanningError) as caught:
            validate_upload_payload({"oid": OID, "sarif": doc})
        self.assertEqual(caught.exception.reason, "sarif_too_large")


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = make_world(Path(self.tmp.name))

    def upload(self, repo="pub", header=None, **kw):
        return self.w.api.upload_sarif(
            self.w.owner_write if header is None else header,
            "volmarr", repo, payload(**kw))

    def test_upload_stores_per_commit_and_answers_summary(self):
        answer = self.upload()
        self.assertEqual(answer["oid"], OID)
        self.assertEqual(answer["ref"], "refs/heads/main")
        self.assertEqual(answer["tool_names"], ["CodeQL"])
        self.assertEqual(answer["runs"], 1)
        self.assertEqual(answer["results"], 3)
        self.assertEqual(answer["levels"],
                         {"error": 1, "warning": 1, "note": 1})
        self.assertEqual(answer["poster"], "volmarr")
        row = self.w.conn.execute(
            "SELECT * FROM code_scanning_uploads").fetchone()
        self.assertEqual(row["commit_oid"], OID)
        self.assertEqual(json.loads(row["sarif_text"]),
                         valid_sarif())

    def test_upload_is_witnessed_exactly_once(self):
        before = audit_actions(self.w)
        self.upload()
        after = audit_actions(self.w)
        self.assertEqual(len(after), len(before) + 1)
        self.assertEqual(after[-1], "repo.code_scanning.upload")
        row = self.w.conn.execute(
            "SELECT detail FROM audit_log ORDER BY seq DESC"
            " LIMIT 1").fetchone()
        detail = json.loads(row["detail"])
        self.assertEqual(detail["poster"], "volmarr")
        self.assertEqual(detail["oid"], OID)
        self.assertEqual(detail["runs"], 1)
        self.assertEqual(detail["results"], 3)
        ok, bad, _ = verify_chain(self.w.conn)
        self.assertTrue(ok, bad)

    def test_upload_requires_authentication(self):
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.upload_sarif(None, "volmarr", "pub",
                                    payload())
        self.assertEqual(caught.exception.reason,
                         "authentication_required")

    def test_read_token_cannot_upload(self):
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.upload_sarif(
                self.w.owner_read, "volmarr", "pub", payload())
        self.assertEqual(caught.exception.reason,
                         "insufficient_scope")

    def test_private_repo_is_repo_not_found_to_strangers(self):
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.upload_sarif(
                basic("mallory", PW), "volmarr", "priv", payload())
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.list_uploads(None, "volmarr", "priv")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.list_uploads(None, "volmarr", "missing")
        self.assertEqual(caught.exception.reason, "repo_not_found")

    def test_refused_upload_stores_and_audits_nothing(self):
        before_rows = self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM code_scanning_uploads"
        ).fetchone()["n"]
        before_audit = len(audit_actions(self.w))
        with self.assertRaises(CodeScanningError):
            self.upload(doc=valid_sarif(version="9.9.9"))
        self.assertEqual(self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM code_scanning_uploads"
        ).fetchone()["n"], before_rows)
        self.assertEqual(len(audit_actions(self.w)), before_audit)

    def test_listing_is_per_commit_and_newest_first(self):
        first = self.upload()
        second = self.upload()
        other = self.upload(oid=OID2)
        whole = self.w.api.list_uploads(
            None, "volmarr", "pub")
        self.assertEqual(whole["total"], 3)
        self.assertEqual(
            [u["id"] for u in whole["uploads"]],
            [other["id"], second["id"], first["id"]])
        mine = self.w.api.list_uploads(
            None, "volmarr", "pub", oid=OID)
        self.assertEqual(mine["total"], 2)
        self.assertTrue(all(u["oid"] == OID
                            for u in mine["uploads"]))
        empty = self.w.api.list_uploads(
            None, "volmarr", "pub", oid="c" * 40)
        self.assertEqual(empty["total"], 0)

    def test_uploads_do_not_leak_between_repositories(self):
        self.upload(repo="pub")
        self.upload(repo="priv")
        pub = self.w.api.list_uploads(None, "volmarr", "pub")
        self.assertEqual(pub["total"], 1)
        priv = self.w.api.list_uploads(
            self.w.owner_read, "volmarr", "priv")
        self.assertEqual(priv["total"], 1)
        self.assertNotEqual(pub["uploads"][0]["id"],
                            priv["uploads"][0]["id"])

    def test_get_upload_returns_the_whole_document(self):
        answer = self.upload()
        fetched = self.w.api.get_upload(
            None, "volmarr", "pub", answer["id"])
        self.assertEqual(fetched["sarif"], valid_sarif())
        self.assertEqual(fetched["id"], answer["id"])
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.get_upload(None, "volmarr", "pub", 9999)
        self.assertEqual(caught.exception.reason,
                         "code_scanning_not_found")
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.get_upload(None, "volmarr", "pub", "x")
        self.assertEqual(caught.exception.reason,
                         "code_scanning_not_found")

    def test_get_upload_in_another_repo_is_not_found(self):
        answer = self.upload(repo="priv")
        with self.assertRaises(CodeScanningError) as caught:
            self.w.api.get_upload(
                self.w.owner_read, "volmarr", "pub", answer["id"])
        self.assertEqual(caught.exception.reason,
                         "code_scanning_not_found")

    def test_reupload_is_a_new_row_beside_the_old(self):
        first = self.upload()
        changed = valid_sarif()
        changed["runs"][0]["results"] = [result()]
        second = self.upload(doc=changed)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(second["results"], 1)
        fetched = self.w.api.get_upload(
            None, "volmarr", "pub", first["id"])
        self.assertEqual(fetched["results"], 3)

    def test_json_forms_render_the_same_answers(self):
        text = self.w.api.upload_sarif_json(
            self.w.owner_write, "volmarr", "pub", payload())
        self.assertEqual(json.loads(text)["oid"], OID)
        listed = json.loads(self.w.api.list_uploads_json(
            None, "volmarr", "pub", oid=OID))
        self.assertEqual(listed["total"], 1)

    def test_error_shape_is_the_one_problem_format(self):
        try:
            self.upload(doc=valid_sarif(runs=[]))
        except CodeScanningError as exc:
            problem = error_to_dict(exc)
        else:  # pragma: no cover
            self.fail("upload should have been refused")
        self.assertEqual(set(problem), set(PROBLEM_FIELDS))
        self.assertEqual(problem["status"], 400)
        self.assertTrue(is_registered_reason("sarif_invalid"))
        self.assertTrue(is_registered_reason("sarif_too_large"))
        self.assertTrue(
            is_registered_reason("code_scanning_not_found"))

    def test_rendering_escapes_and_says_standing_in_words(self):
        doc = valid_sarif()
        doc["runs"][0]["tool"]["driver"]["name"] = (
            "<script>alert(1)</script>")
        answer = self.upload(doc=doc)
        fetched = self.w.api.get_upload(
            None, "volmarr", "pub", answer["id"])
        from samverk.code_scanning import CodeScanningUpload
        record = CodeScanningUpload(
            id=fetched["id"], repo_id=0, oid=fetched["oid"],
            ref=fetched["ref"],
            tool_names=tuple(fetched["tool_names"]),
            run_count=fetched["runs"],
            result_count=fetched["results"],
            level_counts=fetched["levels"],
            poster=fetched["poster"],
            created_at=fetched["created_at"])
        html = render_upload(record)
        self.assertNotIn("<script>alert(1)</script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("3 result(s)", html)
        page = render_code_scanning_page()
        self.assertIn("Code scanning ingestion", page)
        self.assertIn("/api/v1", page)
        self.assertTrue(CODE_SCANNING_API_PATH.startswith(
            "/api/v1/repos/"))

    def test_upload_dict_field_order_is_the_contract(self):
        answer = self.upload()
        self.assertEqual(
            list(answer.keys()),
            ["id", "oid", "ref", "tool_names", "runs",
             "results", "levels", "poster", "created_at"])
        record = SimpleNamespace(**{
            "id": 1, "repo_id": 1, "oid": OID, "ref": "",
            "tool_names": ("T",), "run_count": 1,
            "result_count": 0, "level_counts": {},
            "poster": "volmarr", "created_at": 1})
        from samverk.code_scanning import CodeScanningUpload
        self.assertEqual(
            list(upload_to_dict(CodeScanningUpload(
                **vars(record))).keys()),
            list(answer.keys()))


class PinsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.w = make_world(Path(self.tmp.name))

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.w.conn), 128)
        self.assertEqual(db.MIGRATIONS[-1][0], 128)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 135)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 89)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("repo.code_scanning.upload",
                      taxonomy.REPO_EVENTS)
        tables = {r["name"] for r in self.w.conn.execute(
            "SELECT name FROM sqlite_master"
            " WHERE type = 'table'")}
        self.assertIn("code_scanning_uploads", tables)

    def test_webhook_taxonomy_carries_the_new_verb(self):
        spec = get_webhook_event("repo.code_scanning.upload")
        self.assertEqual(spec.category, "checks")
        self.assertEqual(spec.scope, "repository")
        audit = audit_webhook_events()
        self.assertTrue(audit.ratified, audit.problems)
        self.assertEqual(audit.verbs_checked, 135)


if __name__ == "__main__":
    unittest.main()
