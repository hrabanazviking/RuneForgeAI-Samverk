"""S-266 acceptance battery: CI artifacts API.

Acceptance (roadmap S-266): CI artifacts API --
upload/download of build artifacts tied to a commit
and a check run, with retention policies.

The centre is samverk/ci_artifacts.py: CIArtifactsAPI
over migration 105 (schema 104 to 105; ci_artifacts +
ci_artifact_upload_sessions). Every call resolves
through S-238's door at S-190's rungs; an upload
opens only against a standing S-246 check run for
its commit, moves in chunks under S-012's law, and
promotes with the sniffed type; every artifact
carries its retention choice and computed expires_at
as data; completed uploads and deletions are
witnessed repo.artifact.upload / repo.artifact.delete
(133 events stand).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, hashlib, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore
from samverk.api_checks import StatusChecksAPI
from samverk.audit import AuditLog
from samverk.ci_artifacts import (
    ARTIFACT_POLICY, CIArtifactsAPI, CIArtifactsError,
    artifact_to_dict, decide_expiry, error_to_dict, is_expired,
    render_ci_artifacts_page, validate_artifact_name,
    validate_retention_days)
from samverk.db import schema_version
from samverk.error_shape import is_registered_reason
from samverk.issues import IssueStore
from samverk.repositories import RepositoryStore
from samverk.uploads import UploadPolicy

PW = "correct horse battery"
OID = "a" * 40
OID2 = "b" * 40
T0 = 1_700_000_000
ZIP = b"PK\x03\x04" + b"\x00" * 40
TEXT = b"test report: all green\n"


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(f"{username}:{credential}".encode())
    return "Basic " + raw.decode("ascii")


def make_world(root: Path, policy=ARTIFACT_POLICY) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    issues = IssueStore(conn, repos, accounts, audit=audit, time_fn=clock)
    repos.create_repository(owner.id, "volmarr", "pub", visibility="public")
    repos.create_repository(owner.id, "volmarr", "priv", visibility="private")
    classic = AccessTokenStore(conn, accounts, audit=audit, time_fn=clock)
    expiry = clock.now + 3600
    _, owner_read = classic.create_token(owner.id, "read token", {"repo:read"}, expiry)
    _, owner_write = classic.create_token(owner.id, "write token", {"repo:write"}, expiry)
    checks_api = StatusChecksAPI(conn, accounts, repos, issues, audit=audit, time_fn=clock)
    api = CIArtifactsAPI(conn, accounts, repos, issues, root, audit=audit, time_fn=clock, policy=policy)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger, repos=repos,
        issues=issues, owner_read=owner_read, owner_write=owner_write,
        checks_api=checks_api, api=api, root=root)


class CIArtifactsTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)
        self.owner_basic = basic("volmarr", PW)
        self.reader_basic = basic("yrsa", PW)
        # one standing check run on OID in pub, from S-246's face
        self.w.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/build", "status": "completed",
             "conclusion": "success"})

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(CIArtifactsError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception.reason

    def _begin(self, header=None, repo="pub", **over):
        payload = {"oid": OID, "check_run": "ci/build",
                   "name": "build.zip"}
        payload.update(over)
        return self.w.api.begin_upload(
            header or self.owner_basic, "volmarr", repo, payload)

    def _upload(self, data=ZIP, header=None, **over):
        session = self._begin(header=header, **over)
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)]
        for idx, chunk in enumerate(chunks):
            self.w.api.upload_chunk(
                header or self.owner_basic, "volmarr", "pub",
                session["id"], idx, chunk)
        return self.w.api.complete_upload(
            header or self.owner_basic, "volmarr", "pub", session["id"])

    def _audit(self, action):
        rows = self.w.conn.execute(
            "SELECT actor_id, target_id, detail FROM audit_log"
            " WHERE action = ? ORDER BY seq", (action,)).fetchall()
        return [(r["actor_id"], r["target_id"],
                 json.loads(r["detail"]) if r["detail"] else {})
                for r in rows]

    # -- pins --------------------------------------
    def test_pins_schema_105_taxonomy_133(self):
        self.assertEqual(schema_version(self.w.conn), 122)
        self.assertEqual(db.MIGRATIONS[-1][0], 122)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 88)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertIn("repo.artifact.upload", taxonomy.AUDIT_EVENTS)
        self.assertIn("repo.artifact.delete", taxonomy.AUDIT_EVENTS)
        tables = {r["name"] for r in self.w.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("ci_artifacts", tables)
        self.assertIn("ci_artifact_upload_sessions", tables)

    def test_upgrade_from_104_creates_artifact_tables(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 104:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(schema_version(conn), 104)
            db.migrate(conn)
            self.assertEqual(schema_version(conn), 122)
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("ci_artifacts", tables)
            conn.close()

    # -- pure law ------------------------------------
    def test_validate_artifact_name(self):
        self.assertEqual(validate_artifact_name(" build.zip "), "build.zip")
        self.assertEqual(self._reason(validate_artifact_name, "  "),
                         "artifact_name_required")
        self.assertEqual(self._reason(validate_artifact_name, "../evil"),
                         "artifact_name_invalid")
        self.assertEqual(self._reason(validate_artifact_name, "a/b"),
                         "artifact_name_invalid")
        self.assertEqual(self._reason(validate_artifact_name, "x" * 256),
                         "artifact_name_invalid")

    def test_retention_law_pure(self):
        self.assertEqual(validate_retention_days(None), 90)
        self.assertEqual(validate_retention_days(0), 0)
        self.assertEqual(validate_retention_days(365), 365)
        self.assertEqual(self._reason(validate_retention_days, 45),
                         "retention_invalid")
        self.assertEqual(self._reason(validate_retention_days, True),
                         "retention_invalid")
        self.assertEqual(self._reason(validate_retention_days, "90"),
                         "retention_invalid")
        self.assertIsNone(decide_expiry(0, T0))
        self.assertEqual(decide_expiry(90, T0), T0 + 90 * 86400)
        self.assertFalse(is_expired(None, T0 + 10 ** 9))
        self.assertFalse(is_expired(T0 + 100, T0 + 99))
        self.assertTrue(is_expired(T0 + 100, T0 + 100))

    # -- the door ------------------------------------
    def test_begin_requires_a_standing_check_run(self):
        self.assertEqual(
            self._reason(self._begin, check_run="ci/nope"),
            "check_run_not_found")
        self.assertEqual(
            self._reason(self._begin, oid=OID2), "check_run_not_found")

    def test_begin_validation_whole(self):
        self.assertEqual(
            self._reason(self.w.api.begin_upload, self.owner_basic,
                         "volmarr", "pub", {"oid": OID, "bogus": 1}),
            "payload_invalid")
        self.assertEqual(self._reason(self._begin, oid=""),
                         "check_head_invalid")
        self.assertEqual(self._reason(self._begin, check_run=" "),
                         "check_name_invalid")
        self.assertEqual(self._reason(self._begin, name=""),
                         "artifact_name_required")
        self.assertEqual(self._reason(self._begin, retention_days=45),
                         "retention_invalid")
        self.assertEqual(
            self._reason(self._begin, expected_size=ARTIFACT_POLICY.max_bytes + 1),
            "too_large")
        self.assertEqual(self._reason(self._begin, expected_size=0),
                         "size_invalid")
        rows = self.w.conn.execute(
            "SELECT COUNT(*) c FROM ci_artifact_upload_sessions").fetchone()
        self.assertEqual(rows["c"], 0)

    def test_begin_scoped_through_the_door(self):
        self.assertEqual(
            self._reason(self.w.api.begin_upload, None,
                         "volmarr", "pub",
                         {"oid": OID, "check_run": "ci/build",
                          "name": "x.zip"}),
            "authentication_required")
        self.assertEqual(
            self._reason(self._begin, header=f"Bearer {self.w.owner_read}"),
            "insufficient_scope")
        self.assertEqual(
            self._reason(self._begin, header=self.reader_basic),
            "repo_not_found")
        self.assertEqual(
            self._reason(self._begin, header=basic("mallory", PW), repo="priv"),
            "repo_not_found")

    # -- the happy path ------------------------------
    def test_upload_round_trip_and_shape(self):
        artifact = self._upload()
        self.assertEqual(artifact["oid"], OID)
        self.assertEqual(artifact["check_run"], "ci/build")
        self.assertEqual(artifact["name"], "build.zip")
        self.assertEqual(artifact["size"], len(ZIP))
        self.assertEqual(artifact["sha256"], hashlib.sha256(ZIP).hexdigest())
        self.assertEqual(artifact["content_type"], "application/zip")
        self.assertEqual(artifact["download_count"], 0)
        self.assertEqual(artifact["retention_days"], 90)
        self.assertEqual(artifact["expires_at"], T0 + 90 * 86400)
        self.assertFalse(artifact["expired"])
        self.assertEqual(artifact["poster"], "volmarr")
        self.assertEqual(artifact["created_at"], T0)
        got = self.w.api.get_artifact(None, "volmarr", "pub", artifact["id"])
        self.assertEqual(got["name"], "build.zip")
        listed = self.w.api.list_artifacts(None, "volmarr", "pub", oid=OID)
        self.assertEqual(listed["total"], 1)
        self.assertEqual(listed["artifacts"][0]["check_run"], "ci/build")
        by_run = self.w.api.list_artifacts(
            None, "volmarr", "pub", check_run="ci/build")
        self.assertEqual(by_run["total"], 1)
        other = self.w.api.list_artifacts(None, "volmarr", "pub", oid=OID2)
        self.assertEqual(other["total"], 0)

    def test_upload_witnessed_once_with_poster(self):
        self._upload(header=f"Bearer {self.w.owner_write}")
        entries = self._audit("repo.artifact.upload")
        self.assertEqual(len(entries), 1)
        actor_id, target_id, detail = entries[0]
        self.assertEqual(actor_id, self.w.owner.id)
        self.assertEqual(target_id, "volmarr/pub")
        self.assertEqual(detail["poster"], "volmarr")
        self.assertEqual(detail["credential"], "classic_token")
        self.assertIsNotNone(detail["token_id"])
        self.assertEqual(detail["oid"], OID)
        self.assertEqual(detail["check_run"], "ci/build")
        self.assertEqual(detail["name"], "build.zip")

    def test_name_taken_per_run(self):
        self._upload()
        self.assertEqual(self._reason(self._begin), "artifact_taken")

    def test_chunk_order_and_caps(self):
        session = self._begin()
        self.assertEqual(
            self._reason(self.w.api.upload_chunk, self.owner_basic,
                         "volmarr", "pub", session["id"], 1, b"x"),
            "chunk_out_of_order")
        self.assertEqual(
            self._reason(self.w.api.upload_chunk, self.owner_basic,
                         "volmarr", "pub", session["id"], 0, b""),
            "chunk_empty")
        state = self.w.api.upload_chunk(
            self.owner_basic, "volmarr", "pub", session["id"], 0, ZIP[:10])
        self.assertEqual(state["received"], 10)
        self.assertEqual(state["chunks"], 1)
        aborted = self.w.api.abort_upload(
            self.owner_basic, "volmarr", "pub", session["id"])
        self.assertEqual(aborted["state"], "aborted")
        self.assertEqual(
            self._reason(self.w.api.upload_chunk, self.owner_basic,
                         "volmarr", "pub", session["id"], 1, b"x"),
            "upload_closed")
        self.assertEqual(self._audit("repo.artifact.upload"), [])

    def test_sniffed_type_and_disguise_refused(self):
        artifact = self._upload(data=TEXT, name="report.txt")
        self.assertEqual(artifact["content_type"], "text/plain")
        session = self._begin(name="fake.zip", declared_type="image/png")
        self.w.api.upload_chunk(
            self.owner_basic, "volmarr", "pub", session["id"], 0, ZIP)
        self.assertEqual(
            self._reason(self.w.api.complete_upload, self.owner_basic,
                         "volmarr", "pub", session["id"]),
            "type_mismatch")
        row = self.w.conn.execute(
            "SELECT state FROM ci_artifact_upload_sessions WHERE id = ?",
            (session["id"],)).fetchone()
        self.assertEqual(row["state"], "aborted")
        self.assertEqual(self.w.api.list_artifacts(
            None, "volmarr", "pub")["total"], 1)

    def test_expected_size_mismatch_aborts(self):
        session = self._begin(name="sized.zip", expected_size=len(ZIP) + 5)
        self.w.api.upload_chunk(
            self.owner_basic, "volmarr", "pub", session["id"], 0, ZIP)
        self.assertEqual(
            self._reason(self.w.api.complete_upload, self.owner_basic,
                         "volmarr", "pub", session["id"]),
            "size_mismatch")

    def test_small_policy_cap_aborts_as_it_flows(self):
        small = UploadPolicy(max_bytes=16,
                             allowed_types=ARTIFACT_POLICY.allowed_types)
        w2 = make_world(Path(self._td.name) / "second", policy=small)
        self.addCleanup(w2.conn.close)
        w2.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "name": "ci/build", "status": "completed",
             "conclusion": "success"})
        session = w2.api.begin_upload(
            self.owner_basic, "volmarr", "pub",
            {"oid": OID, "check_run": "ci/build", "name": "big.zip"})
        self.assertEqual(
            self._reason(w2.api.upload_chunk, self.owner_basic,
                         "volmarr", "pub", session["id"], 0, ZIP),
            "too_large")

    # -- download, expiry, delete ---------------------
    def test_download_counts_and_bytes(self):
        artifact = self._upload()
        first = self.w.api.download_artifact(
            None, "volmarr", "pub", artifact["id"])
        self.assertEqual(first.read_all(), ZIP)
        self.assertEqual(first.artifact.download_count, 1)
        self.assertEqual(first.content_type, "application/zip")
        second = self.w.api.download_artifact(
            f"Bearer {self.w.owner_read}", "volmarr", "pub", artifact["id"])
        self.assertEqual(second.artifact.download_count, 2)
        got = self.w.api.get_artifact(None, "volmarr", "pub", artifact["id"])
        self.assertEqual(got["download_count"], 2)
        self.assertEqual(self._audit("repo.artifact.upload").__len__(), 1)

    def test_download_private_repo_is_uniform_missing(self):
        self.w.checks_api.post_check_run(
            self.owner_basic, "volmarr", "priv",
            {"oid": OID, "name": "ci/build", "status": "completed",
             "conclusion": "success"})
        session = self.w.api.begin_upload(
            self.owner_basic, "volmarr", "priv",
            {"oid": OID, "check_run": "ci/build", "name": "secret.zip"})
        self.w.api.upload_chunk(
            self.owner_basic, "volmarr", "priv", session["id"], 0, ZIP)
        artifact = self.w.api.complete_upload(
            self.owner_basic, "volmarr", "priv", session["id"])
        self.assertEqual(
            self._reason(self.w.api.download_artifact, None,
                         "volmarr", "priv", artifact["id"]),
            "repo_not_found")
        opened = self.w.api.download_artifact(
            self.owner_basic, "volmarr", "priv", artifact["id"])
        self.assertEqual(opened.read_all(), ZIP)

    def test_expiry_judged_on_download_and_listing(self):
        artifact = self._upload(retention_days=7)
        self.assertEqual(artifact["expires_at"], T0 + 7 * 86400)
        self.w.clock.now = T0 + 7 * 86400
        listed = self.w.api.list_artifacts(None, "volmarr", "pub")
        self.assertTrue(listed["artifacts"][0]["expired"])
        self.assertEqual(
            self._reason(self.w.api.download_artifact, None,
                         "volmarr", "pub", artifact["id"]),
            "artifact_expired")
        got = self.w.api.get_artifact(None, "volmarr", "pub", artifact["id"])
        self.assertEqual(got["download_count"], 0)

    def test_keep_forever_never_expires(self):
        artifact = self._upload(retention_days=0)
        self.assertIsNone(artifact["expires_at"])
        self.w.clock.now = T0 + 10 * 365 * 86400
        opened = self.w.api.download_artifact(
            None, "volmarr", "pub", artifact["id"])
        self.assertEqual(opened.read_all(), ZIP)

    def test_missing_bytes_refuse_uncounted(self):
        artifact = self._upload()
        repo_id = self.w.repos.get_repository("volmarr", "pub").id
        path = (self.w.root / "ci-artifacts" / str(repo_id)
                / f"{artifact['sha256']}.zip")
        self.assertTrue(path.is_file())
        path.unlink()
        self.assertEqual(
            self._reason(self.w.api.download_artifact, None,
                         "volmarr", "pub", artifact["id"]),
            "artifact_missing")
        got = self.w.api.get_artifact(None, "volmarr", "pub", artifact["id"])
        self.assertEqual(got["download_count"], 0)

    def test_delete_witnessed_and_bytes_removed(self):
        artifact = self._upload()
        self.assertEqual(
            self._reason(self.w.api.delete_artifact, self.reader_basic,
                         "volmarr", "pub", artifact["id"]),
            "repo_not_found")
        gone = self.w.api.delete_artifact(
            self.owner_basic, "volmarr", "pub", artifact["id"])
        self.assertEqual(gone["name"], "build.zip")
        self.assertEqual(self.w.api.list_artifacts(
            None, "volmarr", "pub")["total"], 0)
        entries = self._audit("repo.artifact.delete")
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0][2]["name"], "build.zip")
        repo_id = self.w.repos.get_repository("volmarr", "pub").id
        path = (self.w.root / "ci-artifacts" / str(repo_id)
                / f"{artifact['sha256']}.zip")
        self.assertFalse(path.exists())
        self.assertEqual(
            self._reason(self.w.api.get_artifact, None,
                         "volmarr", "pub", artifact["id"]),
            "artifact_not_found")

    # -- refusal shapes and the page -------------------
    def test_error_shape_registered(self):
        for reason in ("artifact_not_found", "artifact_taken",
                       "artifact_expired", "artifact_missing",
                       "artifact_name_required", "artifact_name_invalid",
                       "check_run_not_found", "retention_invalid",
                       "too_many_artifacts", "upload_not_found",
                       "upload_closed", "chunk_empty", "chunk_too_large",
                       "chunk_out_of_order", "size_invalid",
                       "size_mismatch", "too_large", "empty"):
            self.assertTrue(is_registered_reason(reason), reason)
        try:
            self.w.api.get_artifact(None, "volmarr", "pub", 999)
            self.fail("expected refusal")
        except CIArtifactsError as exc:
            problem = error_to_dict(exc)
        self.assertEqual(set(problem),
                         {"type", "title", "status", "detail", "error_id"})
        self.assertEqual(problem["status"], 404)
        self.assertTrue(problem["type"].endswith("/artifact_not_found"))
        expired = error_to_dict(CIArtifactsError("artifact_expired", "x"))
        self.assertEqual(expired["status"], 410)

    def test_page_states_the_law(self):
        page = render_ci_artifacts_page()
        self.assertIn("CI artifacts API", page)
        self.assertIn("retention", page)
        self.assertIn("90 days", page)
        self.assertIn("S-267", page)


if __name__ == "__main__":
    unittest.main()
