"""S-259 acceptance battery: release assets.

Acceptance (roadmap S-259): Release assets — chunked
upload under S-012 law, per-asset size caps,
content-type by sniffing, download with counts.

The centre is samverk/release_assets.py:
ReleaseAssetStore over migration 102 (schema 101 to
102; release_assets + release_upload_sessions).
Upload is a session: begin_upload fixes the name (and
a declared expected size, judged against the cap at
the door), upload_chunk appends strictly in order
under a per-chunk cap with the running total judged
against the per-asset cap as it flows into
quarantine staging, and complete_upload promotes
under S-012 — samverk.uploads.inspect_upload under
the asset policy, so the stored type is the sniffed
type and a disguised declared type is refused.
Downloads are gated by the release's visibility
(S-258 drafts private to writers) and counted on the
row. No new taxonomy event — 131 stand.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.release_assets import (
    ASSET_POLICY, CHUNK_MAX_BYTES, ReleaseAssetError,
    ReleaseAssetStore, asset_to_dict, render_assets_page,
    validate_asset_name, validate_expected_size)
from samverk.releases import ReleaseStore
from samverk.repositories import RepositoryStore
from samverk.uploads import UploadPolicy
from test_repo_home import run_git

PW = "correct horse battery"
T0 = 1_700_000_000
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
ZIP = b"PK\x03\x04" + b"\x00" * 40
TEXT = b"anvil release notes\nsecond line\n"


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class ReleaseAssetTests(unittest.TestCase):
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
        self.repos.create_repository(
            self.owner.id, "volmarr", "pub", visibility="public")
        self.repos.create_repository(
            self.owner.id, "volmarr", "priv", visibility="private")
        self.bare = self.repos.path_for("volmarr", "pub")
        self.work = self.root / "work"; self.work.mkdir()
        run_git(self.work, "init", "-b", "main")
        self._write("app.py", "print('hi')\n")
        self._commit("first")
        run_git(self.work, "tag", "v1.0")
        run_git(self.work, "push", str(self.bare), "v1.0")
        self._write("app.py", "print('ho')\n")
        self._commit("second")
        run_git(self.work, "tag", "v1.1")
        run_git(self.work, "push", str(self.bare), "v1.1")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.0", "Anvil 1.0")
        self.releases.create_release(
            self.owner, "volmarr", "pub", "v1.1", "Anvil 1.1",
            draft=True)

    def _write(self, rel, text):
        p = self.work / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    def _commit(self, msg):
        run_git(self.work, "add", "-A")
        run_git(self.work, "commit", "-m", msg)
        run_git(self.work, "push", str(self.bare), "main")
        return run_git(self.work, "rev-parse", "HEAD")

    def _reason(self, fn, *a, **k):
        with self.assertRaises(ReleaseAssetError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _upload(self, data, name="notes.txt", tag="v1.0",
                store=None, **begin_kw):
        store = store or self.assets
        chunks = [data[i:i + 8] for i in range(0, len(data), 8)] or [b""]
        session = store.begin_upload(
            self.owner, "volmarr", "pub", tag, name, **begin_kw)
        for idx, chunk in enumerate(chunks):
            if chunk:
                store.upload_chunk(self.owner, session.id, idx, chunk)
        return store.complete_upload(self.owner, session.id)

    # -- pins ------------------------------------------
    def test_pins_schema_102_taxonomy_133(self):
        self.assertEqual(schema_version(self.conn), 106)
        self.assertEqual(db.MIGRATIONS[-1][0], 106)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 133)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 87)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        tables = {r["name"] for r in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("release_assets", tables)
        self.assertIn("release_upload_sessions", tables)

    def test_upgrade_from_101_creates_asset_tables(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "old.db"
            conn = db.connect(path)
            for target, statements in db.MIGRATIONS:
                if target > 101:
                    continue
                with conn:
                    for stmt in statements:
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT OR REPLACE INTO schema_meta"
                        " (key, value) VALUES ('version', ?)",
                        (str(target),))
            self.assertEqual(schema_version(conn), 101)
            db.migrate(conn)
            self.assertEqual(schema_version(conn), 106)
            tables = {r["name"] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("release_assets", tables)
            self.assertIn("release_upload_sessions", tables)
            conn.close()

    # -- pure law ---------------------------------------
    def test_validate_asset_name(self):
        self.assertEqual(validate_asset_name(" anvil.tar.gz "),
                         "anvil.tar.gz")
        self.assertEqual(self._reason(validate_asset_name, "  "),
                         "asset_name_required")
        self.assertEqual(self._reason(validate_asset_name, "../evil"),
                         "asset_name_invalid")
        self.assertEqual(self._reason(validate_asset_name, "a/b"),
                         "asset_name_invalid")
        self.assertEqual(self._reason(validate_asset_name, "a\\b"),
                         "asset_name_invalid")
        self.assertEqual(self._reason(validate_asset_name, ".."),
                         "asset_name_invalid")
        self.assertEqual(self._reason(validate_asset_name, "x" * 256),
                         "asset_name_invalid")
        self.assertEqual(self._reason(validate_asset_name, 7),
                         "asset_name_required")

    def test_validate_expected_size(self):
        self.assertIsNone(validate_expected_size(None, ASSET_POLICY))
        self.assertEqual(validate_expected_size(10, ASSET_POLICY), 10)
        self.assertEqual(
            self._reason(validate_expected_size, True, ASSET_POLICY),
            "size_invalid")
        self.assertEqual(
            self._reason(validate_expected_size, 0, ASSET_POLICY),
            "size_invalid")
        self.assertEqual(
            self._reason(validate_expected_size,
                         ASSET_POLICY.max_bytes + 1, ASSET_POLICY),
            "too_large")

    # -- begin gates -------------------------------------
    def test_begin_is_writer_only_and_release_must_stand(self):
        self.assertEqual(
            self._reason(self.assets.begin_upload, self.reader,
                         "volmarr", "pub", "v1.0", "a.bin"),
            "permission_denied")
        self.assertEqual(
            self._reason(self.assets.begin_upload, self.stranger,
                         "volmarr", "priv", "v1.0", "a.bin"),
            "repo_not_found")
        self.assertEqual(
            self._reason(self.assets.begin_upload, self.owner,
                         "volmarr", "pub", "v9.9", "a.bin"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.assets.begin_upload, self.owner,
                         "volmarr", "pub", "v1.0", "a.bin",
                         expected_size=ASSET_POLICY.max_bytes + 1),
            "too_large")

    # -- chunk law ----------------------------------------
    def test_chunks_must_be_in_order_and_nonempty(self):
        s = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "a.txt")
        self.assertEqual(
            self._reason(self.assets.upload_chunk, self.owner,
                         s.id, 1, b"ab"), "chunk_out_of_order")
        self.assertEqual(
            self._reason(self.assets.upload_chunk, self.owner,
                         s.id, 0, b""), "chunk_empty")
        self.assertEqual(
            self._reason(self.assets.upload_chunk, self.reader,
                         s.id, 0, b"ab"), "permission_denied")
        self.assets.upload_chunk(self.owner, s.id, 0, b"ab")
        done = self.assets.upload_chunk(self.owner, s.id, 1, b"cd")
        self.assertEqual((done.received, done.chunks), (4, 2))

    def test_chunk_over_single_cap_refused(self):
        s = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "big.bin")
        self.assertEqual(
            self._reason(self.assets.upload_chunk, self.owner,
                         s.id, 0, b"x" * (CHUNK_MAX_BYTES + 1)),
            "chunk_too_large")

    def test_running_total_over_cap_aborts_session(self):
        small = ReleaseAssetStore(
            self.conn, self.repos, self.releases, self.root,
            self.accounts, audit=self.audit, time_fn=self.clock,
            policy=UploadPolicy(
                max_bytes=10,
                allowed_types=ASSET_POLICY.allowed_types))
        s = small.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "a.txt")
        small.upload_chunk(self.owner, s.id, 0, b"12345678")
        self.assertEqual(
            self._reason(small.upload_chunk, self.owner,
                         s.id, 1, b"901"), "too_large")
        self.assertEqual(
            self._reason(small.upload_chunk, self.owner,
                         s.id, 1, b"9"), "upload_closed")
        staging = (self.root / "quarantine"
                   / f"release-asset-{s.id}.part")
        self.assertFalse(staging.exists())

    def test_expected_size_mismatch_refused(self):
        s = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "a.txt",
            expected_size=10)
        self.assets.upload_chunk(self.owner, s.id, 0, b"abc")
        self.assertEqual(
            self._reason(self.assets.complete_upload,
                         self.owner, s.id), "size_mismatch")
        s2 = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "b.txt",
            expected_size=2)
        self.assertEqual(
            self._reason(self.assets.upload_chunk, self.owner,
                         s2.id, 0, b"abc"), "size_mismatch")

    def test_complete_empty_refused_and_abort_discards(self):
        s = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "a.txt")
        self.assertEqual(
            self._reason(self.assets.complete_upload,
                         self.owner, s.id), "empty")
        s2 = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "b.txt")
        self.assets.upload_chunk(self.owner, s2.id, 0, b"data")
        aborted = self.assets.abort_upload(self.owner, s2.id)
        self.assertEqual(aborted.state, "aborted")
        self.assertEqual(
            self._reason(self.assets.complete_upload,
                         self.owner, s2.id), "upload_closed")
        self.assertEqual(
            self.assets.list_assets(None, "volmarr", "pub", "v1.0"),
            [])

    # -- sniffing (S-012) ----------------------------------
    def test_chunked_upload_sniffs_text_and_stores(self):
        asset = self._upload(TEXT)
        self.assertEqual(asset.content_type, "text/plain")
        self.assertEqual(asset.size, len(TEXT))
        self.assertEqual(
            asset.sha256, hashlib.sha256(TEXT).hexdigest())
        self.assertEqual(asset.download_count, 0)
        stored = (self.root / "release-assets"
                  / str(asset.repo_id) / str(asset.release_id)
                  / f"{asset.sha256}.txt")
        self.assertTrue(stored.is_file())
        self.assertEqual(stored.read_bytes(), TEXT)

    def test_sniffed_type_beats_generic_declared(self):
        asset = self._upload(
            ZIP, name="anvil.zip",
            declared_type="application/octet-stream")
        self.assertEqual(asset.content_type, "application/zip")
        binary = self._upload(b"\x7fELF" + b"\x01" * 30,
                              name="anvil")
        self.assertEqual(binary.content_type,
                         "application/octet-stream")

    def test_disguised_declared_type_refused_at_complete(self):
        s = self.assets.begin_upload(
            self.owner, "volmarr", "pub", "v1.0", "fake.pdf",
            declared_type="application/pdf")
        data = PNG
        for idx in range(0, len(data), 8):
            self.assets.upload_chunk(
                self.owner, s.id, idx // 8, data[idx:idx + 8])
        self.assertEqual(
            self._reason(self.assets.complete_upload,
                         self.owner, s.id), "type_mismatch")
        self.assertEqual(
            self.assets.list_assets(None, "volmarr", "pub", "v1.0"),
            [])
        honest = self._upload(PNG, name="shot.png",
                              declared_type="image/png")
        self.assertEqual(honest.content_type, "image/png")

    def test_duplicate_name_refused(self):
        self._upload(TEXT, name="notes.txt")
        self.assertEqual(
            self._reason(self.assets.begin_upload, self.owner,
                         "volmarr", "pub", "v1.0", "notes.txt"),
            "asset_taken")

    def test_asset_count_cap(self):
        import samverk.release_assets as module
        old = module.MAX_ASSETS_PER_RELEASE
        module.MAX_ASSETS_PER_RELEASE = 2
        try:
            self._upload(b"one\n", name="a.txt")
            self._upload(b"two\n", name="b.txt")
            self.assertEqual(
                self._reason(self.assets.begin_upload, self.owner,
                             "volmarr", "pub", "v1.0", "c.txt"),
                "too_many_assets")
        finally:
            module.MAX_ASSETS_PER_RELEASE = old

    # -- download with counts ------------------------------
    def test_download_counts_and_serves_bytes(self):
        self._upload(TEXT)
        first = self.assets.download_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(first.read_all(), TEXT)
        self.assertEqual(first.content_type, "text/plain")
        self.assertEqual(first.filename, "notes.txt")
        self.assertEqual(first.asset.download_count, 1)
        second = self.assets.download_asset(
            self.reader, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(second.asset.download_count, 2)
        got = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(got.download_count, 2)

    def test_download_missing_bytes_not_counted(self):
        asset = self._upload(TEXT)
        stored = (self.root / "release-assets"
                  / str(asset.repo_id) / str(asset.release_id)
                  / f"{asset.sha256}.txt")
        stored.unlink()
        self.assertEqual(
            self._reason(self.assets.download_asset, None,
                         "volmarr", "pub", "v1.0", "notes.txt"),
            "asset_missing")
        got = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        self.assertEqual(got.download_count, 0)

    def test_draft_assets_private_to_writers(self):
        self._upload(TEXT, name="draft.txt", tag="v1.1")
        self.assertEqual(
            [a.name for a in self.assets.list_assets(
                self.owner, "volmarr", "pub", "v1.1")],
            ["draft.txt"])
        self.assertEqual(
            self._reason(self.assets.list_assets, self.reader,
                         "volmarr", "pub", "v1.1"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.assets.download_asset, None,
                         "volmarr", "pub", "v1.1", "draft.txt"),
            "release_not_found")
        self.assertEqual(
            self._reason(self.assets.get_asset, self.stranger,
                         "volmarr", "pub", "v9.9", "x"),
            "release_not_found")

    def test_unknown_asset_is_uniform(self):
        self.assertEqual(
            self._reason(self.assets.get_asset, None,
                         "volmarr", "pub", "v1.0", "nope.bin"),
            "asset_not_found")
        self.assertEqual(
            self._reason(self.assets.download_asset,
                         self.stranger, "volmarr", "priv",
                         "v1.0", "x"), "repo_not_found")

    # -- delete, dict, render --------------------------------
    def test_delete_removes_row_and_file_and_shared_bytes_stay(self):
        a = self._upload(TEXT, name="a.txt")
        b = self._upload(TEXT, name="b.txt")
        self.assertEqual(a.sha256, b.sha256)
        self.assertEqual(
            self._reason(self.assets.delete_asset, self.reader,
                         "volmarr", "pub", "v1.0", "a.txt"),
            "permission_denied")
        gone = self.assets.delete_asset(
            self.owner, "volmarr", "pub", "v1.0", "a.txt")
        self.assertEqual(gone.name, "a.txt")
        still = self.assets.download_asset(
            None, "volmarr", "pub", "v1.0", "b.txt")
        self.assertEqual(still.read_all(), TEXT)
        self.assets.delete_asset(
            self.owner, "volmarr", "pub", "v1.0", "b.txt")
        stored = (self.root / "release-assets"
                  / str(a.repo_id) / str(a.release_id)
                  / f"{a.sha256}.txt")
        self.assertFalse(stored.exists())
        self.assertEqual(
            self._reason(self.assets.get_asset, None,
                         "volmarr", "pub", "v1.0", "b.txt"),
            "asset_not_found")

    def test_dict_and_render_carry_count_in_words(self):
        asset = self._upload(TEXT)
        self.assets.download_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        got = self.assets.get_asset(
            None, "volmarr", "pub", "v1.0", "notes.txt")
        d = asset_to_dict(got, "volmarr/pub", "v1.0")
        self.assertEqual(
            set(d), {"repository", "tag", "name", "size", "sha256",
                     "content_type", "download_count",
                     "uploader_id", "created_at"})
        self.assertEqual(d["download_count"], 1)
        self.assertEqual(d["content_type"], "text/plain")
        page = render_assets_page("volmarr/pub", "v1.0", [got])
        self.assertIn("notes.txt", page)
        self.assertIn("text/plain", page)
        self.assertIn("Downloaded 1 time", page)
        self.assertIn("No assets yet.",
                      render_assets_page("volmarr/pub", "v1.0", []))
        evil = self._upload(TEXT, name="a<b>.txt")
        page2 = render_assets_page("volmarr/pub", "v1.0", [evil])
        self.assertIn("a&lt;b&gt;.txt", page2)
        self.assertNotIn("a<b>.txt", page2)


if __name__ == "__main__":
    unittest.main()
