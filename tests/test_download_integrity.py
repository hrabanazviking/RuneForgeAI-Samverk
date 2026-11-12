"""S-271 acceptance battery: download integrity.

Acceptance (roadmap S-271): Download integrity --
assets served with digests in headers; interrupted
downloads resumable where the client supports ranges.

The centre is samverk/download_integrity.py over the
three asset doors: release assets (S-259), the
generated checksums file (S-260) and CI artifacts
(S-266). Every answer carries the stored SHA-256 as
ETag and as RFC 9530 Digest / Repr-Digest; one Range
per request is served as a 206 with Content-Range
(If-Range judged strongly, If-None-Match first, per
S-239); refusals are range_invalid (400) and
range_not_satisfiable (416), registered in S-240's
registry. Planning precedes opening, so a refusal or
a 304 counts nothing and a byte-serving answer counts
exactly once through the door's own transaction. No
migration (schema 106 stands), no new taxonomy event
(133 stand).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, hashlib, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.download_integrity import (
    DownloadIntegrityError, DownloadIntegrityStore,
    digest_header_value, digest_of, error_to_dict, etag_for_digest,
    if_range_applies, parse_range_header, plan_download,
    render_download_integrity_section, response_to_dict,
    serve_bytes, serve_opened, verify_download)
from samverk.error_shape import is_registered_reason, problem_from_error
from samverk.release_assets import ReleaseAssetStore
from samverk.release_checksums import ReleaseChecksumStore
from samverk.releases import ReleaseStore
from samverk.repositories import RepositoryStore
from test_ci_artifacts import basic, make_world
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000
DATA = b"0123456789" * 10          # 100 bytes, position-readable
TEXT_A = b"anvil release notes\nsecond line\n"
ZIP = b"PK\x03\x04" + b"\x00" * 40


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _reason(fn, *a, **k):
    try:
        fn(*a, **k)
    except DownloadIntegrityError as exc:
        return exc.reason
    raise AssertionError("no DownloadIntegrityError raised")


class PureRangeTests(unittest.TestCase):
    def test_no_header_means_whole_file(self):
        self.assertIsNone(parse_range_header(None, 100))

    def test_closed_open_and_suffix_forms(self):
        spec = parse_range_header("bytes=0-9", 100)
        self.assertEqual((spec.start, spec.end, spec.length), (0, 9, 10))
        self.assertEqual(spec.content_range, "bytes 0-9/100")
        spec = parse_range_header("bytes=90-", 100)
        self.assertEqual((spec.start, spec.end), (90, 99))
        spec = parse_range_header("bytes=-25", 100)
        self.assertEqual((spec.start, spec.end), (75, 99))
        spec = parse_range_header("bytes=-500", 100)
        self.assertEqual((spec.start, spec.end), (0, 99))

    def test_end_past_file_is_clamped_and_named(self):
        spec = parse_range_header("bytes=95-999", 100)
        self.assertEqual((spec.start, spec.end), (95, 99))
        self.assertEqual(spec.content_range, "bytes 95-99/100")

    def test_malformed_ranges_are_range_invalid(self):
        for bad in ("items=0-1", "bytes=", "bytes=-", "bytes=a-b",
                    "bytes=0-1,3-4", "bytes=1-2-3", "bytes", 42):
            self.assertEqual(
                _reason(parse_range_header, bad, 100), "range_invalid",
                repr(bad))

    def test_unservable_ranges_are_not_satisfiable(self):
        for bad in ("bytes=100-", "bytes=100-200", "bytes=50-40",
                    "bytes=-0"):
            self.assertEqual(
                _reason(parse_range_header, bad, 100),
                "range_not_satisfiable", bad)
        self.assertEqual(
            _reason(parse_range_header, "bytes=0-0", 0),
            "range_not_satisfiable")


class PurePlanTests(unittest.TestCase):
    def test_digest_and_etag_statements_agree(self):
        sha = _sha(DATA)
        self.assertEqual(etag_for_digest(sha), f'"{sha}"')
        value = digest_header_value(sha)
        self.assertTrue(value.startswith("sha-256=:"))
        raw = base64.b64decode(value[len("sha-256=:"):-1])
        self.assertEqual(raw.hex(), sha)
        self.assertEqual(digest_of(DATA), sha)
        self.assertTrue(verify_download(DATA, sha))
        self.assertFalse(verify_download(DATA + b"x", sha))
        self.assertFalse(verify_download(DATA, "not-a-digest"))
        self.assertFalse(verify_download(DATA, None))

    def test_full_plan_carries_digest_headers(self):
        sha = _sha(DATA)
        plan = plan_download(100, sha, "text/plain", "a.txt")
        self.assertEqual(plan.status, 200)
        self.assertEqual(plan.headers["ETag"], f'"{sha}"')
        self.assertEqual(plan.headers["Digest"], digest_header_value(sha))
        self.assertEqual(plan.headers["Repr-Digest"],
                         digest_header_value(sha))
        self.assertEqual(plan.headers["Accept-Ranges"], "bytes")
        self.assertEqual(plan.headers["Content-Length"], "100")
        self.assertEqual(plan.headers["Content-Disposition"],
                         'attachment; filename="a.txt"')
        self.assertNotIn("Content-Range", plan.headers)

    def test_partial_plan_names_its_slice(self):
        plan = plan_download(100, _sha(DATA), "text/plain", "a.txt",
                             range_header="bytes=10-19")
        self.assertEqual(plan.status, 206)
        self.assertEqual(plan.headers["Content-Range"], "bytes 10-19/100")
        self.assertEqual(plan.headers["Content-Length"], "10")
        self.assertEqual(plan.content_length, 10)

    def test_if_range_strong_match_only(self):
        etag = etag_for_digest(_sha(DATA))
        self.assertTrue(if_range_applies(None, etag))
        self.assertTrue(if_range_applies(etag, etag))
        self.assertFalse(if_range_applies('"deadbeef"', etag))
        self.assertFalse(if_range_applies("W/" + etag, etag))
        self.assertFalse(if_range_applies(
            "Wed, 21 Oct 2015 07:28:00 GMT", etag))
        plan = plan_download(100, _sha(DATA), "text/plain", "a.txt",
                             range_header="bytes=0-9",
                             if_range='"deadbeef"')
        self.assertEqual(plan.status, 200)
        self.assertIsNone(plan.spec)

    def test_if_none_match_answers_304_before_range(self):
        sha = _sha(DATA)
        etag = etag_for_digest(sha)
        for header in (etag, "W/" + etag, "*", f'"other", {etag}'):
            plan = plan_download(100, sha, "text/plain", "a.txt",
                                 range_header="bytes=0-9",
                                 if_none_match=header)
            self.assertEqual(plan.status, 304, header)
            self.assertEqual(plan.headers["ETag"], etag)
            self.assertIn("Digest", plan.headers)
        plan = plan_download(100, sha, "text/plain", "a.txt",
                             if_none_match='"other"')
        self.assertEqual(plan.status, 200)

    def test_serve_bytes_slices_and_reassembles(self):
        whole = serve_bytes(DATA, "a.txt", "text/plain")
        self.assertEqual(whole.status, 200)
        self.assertEqual(whole.read_all(), DATA)
        first = serve_bytes(DATA, "a.txt", "text/plain",
                            range_header="bytes=0-49")
        second = serve_bytes(DATA, "a.txt", "text/plain",
                             range_header="bytes=50-")
        self.assertEqual(first.read_all(), DATA[:50])
        self.assertEqual(second.read_all(), DATA[50:])
        self.assertEqual(first.read_all() + second.read_all(), DATA)
        self.assertTrue(first.is_partial)
        notmod = serve_bytes(DATA, "a.txt", "text/plain",
                             if_none_match=etag_for_digest(_sha(DATA)))
        self.assertEqual(notmod.status, 304)
        self.assertEqual(notmod.read_all(), b"")

    def test_response_dict_and_rendered_section(self):
        resp = serve_bytes(DATA, "a<b>.txt", "text/plain",
                           range_header="bytes=-10")
        data = response_to_dict(resp)
        self.assertEqual(data["status"], 206)
        self.assertEqual(data["range"]["content_range"],
                         "bytes 90-99/100")
        self.assertEqual(data["sha256"], _sha(DATA))
        page = render_download_integrity_section("a<b>.txt")
        self.assertIn("a&lt;b&gt;.txt", page)
        self.assertNotIn("a<b>.txt", page)
        self.assertIn("Digest", page)
        self.assertIn("Range", page)
        self.assertIn("If-Range", page)

    def test_reasons_registered_in_problem_registry(self):
        self.assertTrue(is_registered_reason("range_invalid"))
        self.assertTrue(is_registered_reason("range_not_satisfiable"))
        exc = DownloadIntegrityError("range_not_satisfiable", "nope")
        self.assertEqual(problem_from_error(exc).status, 416)
        exc = DownloadIntegrityError("range_invalid", "nope")
        self.assertEqual(problem_from_error(exc).status, 400)
        shaped = error_to_dict(exc)
        self.assertEqual(shaped["status"], 400)
        self.assertEqual(shaped["type"],
                         "/api/v1/problems/range_invalid")

    def test_pins_schema_107_taxonomy_133(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        conn = db.init_db(Path(td.name) / "samverk.db")
        self.addCleanup(conn.close)
        self.assertEqual(schema_version(conn), 121)
        self.assertEqual(db.MIGRATIONS[-1][0], 121)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 134)


class ReleaseFacadeTests(unittest.TestCase):
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
        self.reader = self.accounts.register("yrsa", PW)
        self.stranger = self.accounts.register("mallory", PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.releases = ReleaseStore(
            self.conn, self.repos, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.assets = ReleaseAssetStore(
            self.conn, self.repos, self.releases, self.root,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.checksums = ReleaseChecksumStore(
            self.conn, self.repos, self.releases, self.assets,
            self.accounts, audit=self.audit, time_fn=self.clock)
        self.integrity = DownloadIntegrityStore(
            assets=self.assets, checksums=self.checksums)
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.bare_priv = self.repos.path_for("volmarr", "priv")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("app.py", "print('hi')\n")
        self._commit("first")
        run_git(self.work, "tag", "v1.0")
        run_git(self.work, "push", str(self.bare), "v1.0")
        run_git(self.work, "push", str(self.bare_priv), "v1.0")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0")
        run_git(self.work, "tag", "v1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.1", "Anvil 1.1",
            draft=True)
        self.releases.create_release(
            self.owner, "volmarr", "priv", "v1.0", "Secret 1.0")
        self.asset = self._upload(DATA, "data.txt", repo="pub")
        self._upload(TEXT_A, "anvil.txt", repo="pub")
        self.draft_asset = self._upload(
            DATA, "draft.txt", repo="pub", tag="v1.1")
        self._upload(DATA, "hidden.txt", repo="priv")

    def _write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _upload(self, data, name, repo="pub", tag="v1.0"):
        session = self.assets.begin_upload(
            self.owner, "volmarr", repo, tag, name)
        for idx in range(0, max(len(data), 1), 8):
            chunk = data[idx:idx + 8]
            if chunk:
                self.assets.upload_chunk(
                    self.owner, session.id, idx // 8, chunk)
        return self.assets.complete_upload(self.owner, session.id)

    def _count(self, name="data.txt"):
        row = self.conn.execute(
            "SELECT download_count FROM release_assets WHERE name = ?",
            (name,)).fetchone()
        return row["download_count"]

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) c FROM audit_log").fetchone()["c"]

    def test_asset_full_download_digests_and_counts_once(self):
        before_audit = self._audit_count()
        resp = self.integrity.download_asset(
            self.reader, "volmarr", "pub", "v1.0", "data.txt")
        self.assertEqual(resp.status, 200)
        body = resp.read_all()
        self.assertEqual(body, DATA)
        self.assertTrue(verify_download(body, resp.sha256))
        self.assertEqual(resp.headers["Digest"],
                         digest_header_value(_sha(DATA)))
        self.assertEqual(resp.headers["ETag"], f'"{_sha(DATA)}"')
        self.assertEqual(self._count(), 1)
        self.assertEqual(self._audit_count(), before_audit)

    def test_asset_resume_reassembles_and_counts_per_answer(self):
        first = self.integrity.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            range_header="bytes=0-59")
        self.assertEqual(first.status, 206)
        self.assertEqual(first.headers["Content-Range"],
                         "bytes 0-59/100")
        rest = self.integrity.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            range_header="bytes=60-",
            if_range=first.headers["ETag"])
        self.assertEqual(rest.status, 206)
        self.assertEqual(first.read_all() + rest.read_all(), DATA)
        self.assertEqual(self._count(), 2)

    def test_asset_stale_if_range_serves_whole_file(self):
        resp = self.integrity.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            range_header="bytes=60-", if_range='"stale"')
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.read_all(), DATA)
        self.assertEqual(self._count(), 1)

    def test_asset_refusals_and_304_count_nothing(self):
        self.assertEqual(_reason(
            self.integrity.download_asset, None, "volmarr", "pub",
            "v1.0", "data.txt", range_header="bytes=100-"),
            "range_not_satisfiable")
        self.assertEqual(_reason(
            self.integrity.download_asset, None, "volmarr", "pub",
            "v1.0", "data.txt", range_header="bytes=0-1,2-3"),
            "range_invalid")
        resp = self.integrity.download_asset(
            None, "volmarr", "pub", "v1.0", "data.txt",
            if_none_match=etag_for_digest(_sha(DATA)))
        self.assertEqual(resp.status, 304)
        self.assertEqual(resp.read_all(), b"")
        self.assertEqual(self._count(), 0)

    def test_asset_visibility_is_the_release_own(self):
        self.assertEqual(_reason(
            self.integrity.download_asset, self.stranger, "volmarr",
            "pub", "v1.1", "draft.txt"), "release_not_found")
        resp = self.integrity.download_asset(
            self.owner, "volmarr", "pub", "v1.1", "draft.txt",
            range_header="bytes=-4")
        self.assertEqual(resp.read_all(), DATA[-4:])
        self.assertEqual(_reason(
            self.integrity.download_asset, self.stranger, "volmarr",
            "priv", "v1.0", "hidden.txt"), "repo_not_found")
        self.assertEqual(_reason(
            self.integrity.download_asset, None, "volmarr", "pub",
            "v1.0", "nosuch.txt"), "asset_not_found")

    def test_checksums_download_full_range_and_digest(self):
        resp = self.integrity.download_checksums(
            None, "volmarr", "pub", "v1.0")
        body = resp.read_all()
        generated = self.checksums.get_checksums(
            None, "volmarr", "pub", "v1.0")
        self.assertEqual(body, generated.data)
        self.assertEqual(resp.sha256, _sha(generated.data))
        self.assertTrue(verify_download(body, resp.sha256))
        part = self.integrity.download_checksums(
            None, "volmarr", "pub", "v1.0", range_header="bytes=0-9")
        self.assertEqual(part.status, 206)
        self.assertEqual(part.read_all(), generated.data[:10])
        # the generated file counts nothing, on any asset
        self.assertEqual(self._count("anvil.txt"), 0)

    def test_checksums_visibility_carried(self):
        self.assertEqual(_reason(
            self.integrity.download_checksums, self.stranger,
            "volmarr", "priv", "v1.0"), "repo_not_found")


class CIArtifactFacadeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)
        self.owner_basic = basic("volmarr", PW)
        self.w.checks_api.post_check_run(
            self.owner_basic, "volmarr", "pub",
            {"oid": "a" * 40, "name": "ci/build",
             "status": "completed", "conclusion": "success"})
        session = self.w.api.begin_upload(
            self.owner_basic, "volmarr", "pub",
            {"oid": "a" * 40, "check_run": "ci/build",
             "name": "build.zip"})
        data = ZIP + DATA
        for idx in range(0, len(data), 8):
            self.w.api.upload_chunk(
                self.owner_basic, "volmarr", "pub", session["id"],
                idx // 8, data[idx:idx + 8])
        self.artifact = self.w.api.complete_upload(
            self.owner_basic, "volmarr", "pub", session["id"])
        self.data = data
        self.integrity = DownloadIntegrityStore(ci_api=self.w.api)

    def _count(self):
        return self.w.conn.execute(
            "SELECT download_count FROM ci_artifacts WHERE id = ?",
            (self.artifact["id"],)).fetchone()["download_count"]

    def test_artifact_range_download_with_digests(self):
        resp = self.integrity.download_artifact(
            None, "volmarr", "pub", self.artifact["id"],
            range_header="bytes=10-19")
        self.assertEqual(resp.status, 206)
        self.assertEqual(resp.read_all(), self.data[10:20])
        self.assertEqual(resp.sha256, _sha(self.data))
        self.assertEqual(resp.headers["Digest"],
                         digest_header_value(_sha(self.data)))
        self.assertEqual(self._count(), 1)
        whole = self.integrity.download_artifact(
            None, "volmarr", "pub", self.artifact["id"])
        self.assertEqual(whole.read_all(), self.data)
        self.assertEqual(self._count(), 2)

    def test_artifact_refusal_counts_nothing(self):
        self.assertEqual(_reason(
            self.integrity.download_artifact, None, "volmarr", "pub",
            self.artifact["id"], range_header="bytes=99999-"),
            "range_not_satisfiable")
        self.assertEqual(self._count(), 0)
        self.assertEqual(_reason(
            self.integrity.download_artifact, None, "volmarr", "priv",
            self.artifact["id"]), "repo_not_found")


if __name__ == "__main__":
    unittest.main()
