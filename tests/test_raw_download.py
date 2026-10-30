"""S-100 acceptance battery: raw and download.

Acceptance (roadmap S-100): raw file bytes with correct
content types; large and LFS files show pointer + download,
never a silent truncation.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.blob_view import VIEW_MAX_BYTES
from samverk.lfs_store import LFSStore, make_pointer, oid_for
from samverk.raw_download import RawDownloadService, RawError, render_pointer_page
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32

class RawDownloadTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.service = RawDownloadService(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "app.py").write_text("print('hi')\n", encoding="utf-8")
        (work / "pic.png").write_bytes(PNG)
        (work / "data.unknownext").write_bytes(b"\x00\xff\x00\xfe")
        self.big_text = b"line\n" * (VIEW_MAX_BYTES // 5 + 1000)
        (work / "big.txt").write_bytes(self.big_text)
        self.lfs_payload = b"real bytes behind the pointer" * 10
        (work / "movie.bin").write_bytes(
            make_pointer(oid_for(self.lfs_payload), len(self.lfs_payload)))
        (work / "gone.bin").write_bytes(
            make_pointer(oid_for(b"not stored"), len(b"not stored")))
        (work / "icon.svg").write_text("<svg onload=alert(1)></svg>", encoding="utf-8")
        run_git(work, "add", "."); run_git(work, "commit", "-m", "files")
        run_git(work, "push", str(bare), "main")
        # The resolved LFS object lands in the repo's own store.
        LFSStore(bare).put(oid_for(self.lfs_payload), self.lfs_payload)

    def test_raw_bytes_and_content_types(self):
        raw = self.service.raw(self.owner, "volmarr", "samverk", path="app.py")
        self.assertEqual(raw.data, b"print('hi')\n")
        self.assertEqual(raw.content_type, "text/x-python; charset=utf-8")
        self.assertEqual(raw.filename, "app.py")
        png = self.service.raw(self.owner, "volmarr", "samverk", path="pic.png")
        self.assertEqual(png.data, PNG)
        self.assertEqual(png.content_type, "image/png")
        self.assertEqual(png.disposition, "inline")
        unknown = self.service.raw(self.owner, "volmarr", "samverk", path="data.unknownext")
        self.assertEqual(unknown.content_type, "application/octet-stream")
        self.assertTrue(unknown.disposition.startswith("attachment"))

    def test_svg_is_attachment_never_inline(self):
        raw = self.service.raw(self.owner, "volmarr", "samverk", path="icon.svg")
        self.assertEqual(raw.content_type, "image/svg+xml")
        self.assertTrue(raw.disposition.startswith("attachment"))

    def test_large_file_is_never_truncated(self):
        raw = self.service.raw(self.owner, "volmarr", "samverk", path="big.txt")
        self.assertEqual(raw.data, self.big_text)
        self.assertEqual(raw.size, len(self.big_text))
        self.assertGreater(raw.size, VIEW_MAX_BYTES)

    def test_lfs_resolved_serves_real_bytes(self):
        raw = self.service.raw(self.owner, "volmarr", "samverk", path="movie.bin")
        self.assertTrue(raw.is_lfs_pointer)
        self.assertEqual(raw.data, self.lfs_payload)
        self.assertTrue(raw.download_available)
        self.assertIn("can be downloaded", render_pointer_page(raw))

    def test_lfs_unresolved_shows_pointer_not_fake_bytes(self):
        raw = self.service.raw(self.owner, "volmarr", "samverk", path="gone.bin")
        self.assertTrue(raw.is_lfs_pointer)
        self.assertIsNone(raw.data)
        self.assertFalse(raw.download_available)
        self.assertEqual(raw.lfs_size, len(b"not stored"))
        page = render_pointer_page(raw)
        self.assertIn(oid_for(b"not stored"), page)
        self.assertIn("not stored on this instance", page)

    def test_permission_and_path_law(self):
        with self.assertRaises(RawError) as caught:
            self.service.raw(self.stranger, "volmarr", "samverk", path="app.py")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(RawError) as caught:
            self.service.raw(self.owner, "volmarr", "samverk", path="../app.py")
        self.assertEqual(caught.exception.reason, "path_invalid")
        with self.assertRaises(RawError) as caught:
            self.service.raw(self.owner, "volmarr", "samverk", path="nope.py")
        self.assertEqual(caught.exception.reason, "path_not_found")

if __name__ == "__main__":
    unittest.main()
