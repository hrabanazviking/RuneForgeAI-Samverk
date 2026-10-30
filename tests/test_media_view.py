"""S-114 acceptance battery: binary and image files.

Acceptance (roadmap S-114): images render with alt text;
binaries show size/type/download, never a hex dump
surprise.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import struct, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.lfs_store import make_pointer, oid_for
from samverk.media_view import (MediaError, MediaViewer, image_dimensions,
                                render_media_page, sniff_image)
from samverk.repositories import RepositoryStore
from test_repo_home import run_git

PNG = (b"\x89PNG\r\n\x1a\n" + struct.pack(">I", 13) + b"IHDR"
       + struct.pack(">II", 3, 2) + b"\x08\x02\x00\x00\x00" + b"rest")
GIF = b"GIF89a" + struct.pack("<HH", 4, 5) + b"\x00\x00\x00;"
JPEG = (b"\xff\xd8\xff\xc0" + struct.pack(">H", 17) + b"\x08"
        + struct.pack(">HH", 7, 9) + b"\x03" + b"\x00" * 9)
BINARY = bytes(range(256))

class MediaViewTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "samverk", visibility="private")
        self.viewer = MediaViewer(self.repos)
        bare = self.repos.path_for("volmarr", "samverk")
        work = self.root / "work"; work.mkdir()
        run_git(work, "init", "-b", "main")
        (work / "pic.png").write_bytes(PNG)
        (work / "anim.gif").write_bytes(GIF)
        (work / "photo.jpg").write_bytes(JPEG)
        (work / "blob.bin").write_bytes(BINARY)
        (work / "sneaky.txt").write_bytes(PNG)          # magic beats the name
        (work / "icon.svg").write_text(
            '<svg xmlns="http://www.w3.org/2000/svg"><script>x</script></svg>',
            encoding="utf-8")
        (work / "app.py").write_text("print('hi')\n", encoding="utf-8")
        payload = b"real lfs bytes"
        (work / "big.dat").write_bytes(make_pointer(oid_for(payload), len(payload)))
        run_git(work, "add", "."); run_git(work, "commit", "-m", "media")
        run_git(work, "push", str(bare), "main")
        self.commit = run_git(work, "rev-parse", "main")

    def test_images_render_with_real_alt_text(self):
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="pic.png")
        self.assertEqual(view.kind, "image")
        self.assertEqual(view.image_format, "png")
        self.assertEqual((view.width, view.height), (3, 2))
        self.assertEqual(view.commit_oid, self.commit)
        self.assertIn("/raw/" + self.commit + "/pic.png", view.raw_href)
        self.assertIn("pic.png", view.alt_text)
        self.assertIn("3 by 2", view.alt_text)
        page = render_media_page(view)
        self.assertIn("<img ", page)
        self.assertIn(f'alt="{view.alt_text}"', page)
        self.assertIn("Download the original file", page)

    def test_dimensions_come_from_headers(self):
        self.assertEqual(sniff_image(GIF), "gif")
        self.assertEqual(image_dimensions("gif", GIF), (4, 5))
        self.assertEqual(image_dimensions("jpeg", JPEG), (9, 7))
        self.assertIsNone(image_dimensions("png", b"\x89PNG truncated"))
        gif_view = self.viewer.view(self.owner, "volmarr", "samverk", path="anim.gif")
        self.assertEqual((gif_view.width, gif_view.height), (4, 5))
        jpg_view = self.viewer.view(self.owner, "volmarr", "samverk", path="photo.jpg")
        self.assertEqual((jpg_view.width, jpg_view.height), (9, 7))

    def test_magic_bytes_decide_not_the_name(self):
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="sneaky.txt")
        self.assertEqual(view.kind, "image")
        self.assertEqual(view.image_format, "png")

    def test_binary_is_described_never_dumped(self):
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="blob.bin")
        self.assertEqual(view.kind, "binary")
        self.assertEqual(view.size, 256)
        self.assertEqual(view.content_type, "application/octet-stream")
        page = render_media_page(view)
        self.assertIn("binary file", page)
        self.assertIn("Download this file", page)
        self.assertNotIn("00010203", page)          # no hex dump
        self.assertNotIn("AAECAwQF", page)          # no base64 dump
        self.assertNotIn("<img", page)

    def test_svg_is_described_not_rendered_inline(self):
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="icon.svg")
        self.assertEqual(view.kind, "binary")
        self.assertEqual(view.content_type, "image/svg+xml")
        page = render_media_page(view)
        self.assertNotIn("<img", page)
        self.assertNotIn("<script>", page)

    def test_text_and_lfs_and_permission_law(self):
        with self.assertRaises(MediaError) as caught:
            self.viewer.view(self.owner, "volmarr", "samverk", path="app.py")
        self.assertEqual(caught.exception.reason, "text_file")
        view = self.viewer.view(self.owner, "volmarr", "samverk", path="big.dat")
        self.assertEqual(view.kind, "lfs_pointer")
        self.assertEqual(view.lfs_size, len(b"real lfs bytes"))
        self.assertIn("Git LFS", render_media_page(view))
        with self.assertRaises(MediaError) as caught:
            self.viewer.view(self.stranger, "volmarr", "samverk", path="pic.png")
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(MediaError) as caught:
            self.viewer.view(self.owner, "volmarr", "samverk", path="../pic.png")
        self.assertEqual(caught.exception.reason, "path_invalid")

if __name__ == "__main__":
    unittest.main()
