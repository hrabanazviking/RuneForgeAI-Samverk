"""S-409 battery — path and encoding discipline. Real runs only.

The canonical form is pure string/byte law, platform-independent
by construction, so the battery proves it directly. The on-disk
checks are real file writes and reads on this host. The source
tree audit is run against synthetic trees (every dirt kind
planted and caught) and against the real package tree, whose
measured result is asserted only for the byte facts verified at
build time (no CR bytes, all valid UTF-8, all NFC — see
docs/PATH_ENCODING.md); a future non-NFC source file fails this
battery loudly, which is the law working, not a flake.
"""
import subprocess, sys, tempfile, unicodedata, unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.path_encoding import (PathEncodingError, audit_source_tree,
    canonical_bytes, canonical_path, canonical_text, check_stored_path,
    check_wire_bytes, is_canonical_text, stored_form, write_canonical_text)

DECOMPOSED = "cafe\u0301"     # e + combining acute (2 codepoints)
COMPOSED = "caf\u00e9"          # single codepoint e-acute


class CanonicalTextTests(unittest.TestCase):
    def test_crlf_and_cr_become_lf(self):
        self.assertEqual(canonical_text("a\r\nb\rc\nd"), "a\nb\nc\nd")

    def test_nfc_composes(self):
        self.assertEqual(canonical_text(DECOMPOSED), COMPOSED)
        self.assertNotEqual(DECOMPOSED, COMPOSED)

    def test_idempotent(self):
        once = canonical_text("x\r\n" + DECOMPOSED)
        self.assertEqual(canonical_text(once), once)

    def test_nul_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_text("a\x00b")
        self.assertEqual(cm.exception.reason, "nul_character")

    def test_control_character_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_text("a\x07b")
        self.assertEqual(cm.exception.reason, "control_character")

    def test_is_canonical_text(self):
        self.assertTrue(is_canonical_text("plain\n" + COMPOSED))
        self.assertFalse(is_canonical_text("a\r\nb"))
        self.assertFalse(is_canonical_text(DECOMPOSED))
        self.assertFalse(is_canonical_text("a\x00b"))


class CanonicalPathTests(unittest.TestCase):
    def test_forward_slash_passthrough(self):
        self.assertEqual(canonical_path("refs/heads/main"), "refs/heads/main")

    def test_backslashes_normalised(self):
        self.assertEqual(canonical_path("refs\\heads\\main"), "refs/heads/main")

    def test_nfc_in_path(self):
        self.assertEqual(canonical_path("docs/" + DECOMPOSED + ".md"),
                         "docs/" + COMPOSED + ".md")

    def test_absolute_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("/etc/passwd")
        self.assertEqual(cm.exception.reason, "absolute_path")

    def test_drive_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("C:\\repos\\x")
        self.assertEqual(cm.exception.reason, "drive_path")

    def test_dotdot_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("a/../b")
        self.assertEqual(cm.exception.reason, "dotdot_component")

    def test_dot_component_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("a/./b")
        self.assertEqual(cm.exception.reason, "dot_component")

    def test_empty_component_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("a//b")
        self.assertEqual(cm.exception.reason, "empty_component")

    def test_trailing_separator_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("a/b/")
        self.assertEqual(cm.exception.reason, "trailing_separator")

    def test_trailing_dot_component_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("a/name./b")
        self.assertEqual(cm.exception.reason, "trailing_dot_or_space")

    def test_empty_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_path("")
        self.assertEqual(cm.exception.reason, "empty_path")

    def test_check_stored_path_accepts_canonical(self):
        self.assertEqual(check_stored_path("a/b.txt"), "a/b.txt")

    def test_check_stored_path_refuses_backslash_form(self):
        with self.assertRaises(PathEncodingError) as cm:
            check_stored_path("a\\b.txt")
        self.assertEqual(cm.exception.reason, "not_canonical")

    def test_check_stored_path_refuses_decomposed(self):
        with self.assertRaises(PathEncodingError) as cm:
            check_stored_path(DECOMPOSED + ".md")
        self.assertEqual(cm.exception.reason, "not_canonical")

    def test_stored_form_from_host_path(self):
        host = Path("repos") / "owner" / "repo.git"
        self.assertEqual(stored_form(host), "repos/owner/repo.git")
        self.assertNotIn("\\", stored_form(host))


class WireBytesTests(unittest.TestCase):
    def test_canonical_bytes_normalises(self):
        raw = ("a\r\n" + DECOMPOSED).encode("utf-8")
        self.assertEqual(canonical_bytes(raw),
                         ("a\n" + COMPOSED).encode("utf-8"))

    def test_invalid_utf8_refused(self):
        with self.assertRaises(PathEncodingError) as cm:
            canonical_bytes(b"\xff\xfe")
        self.assertEqual(cm.exception.reason, "invalid_utf8")

    def test_check_wire_bytes(self):
        good = "a\nb".encode("utf-8")
        self.assertEqual(check_wire_bytes(good), good)
        with self.assertRaises(PathEncodingError) as cm:
            check_wire_bytes(b"a\r\nb")
        self.assertEqual(cm.exception.reason, "not_canonical")


class RealFileTests(unittest.TestCase):
    def test_write_canonical_text_lands_lf_utf8_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            p = write_canonical_text(Path(td) / "out.txt",
                                     "a\r\n" + DECOMPOSED + "\r\n")
            data = p.read_bytes()
            self.assertNotIn(b"\r", data)
            self.assertEqual(data.decode("utf-8"), "a\n" + COMPOSED + "\n")

    def test_audit_catches_planted_dirt(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "clean.py").write_bytes(b"x = 1\n")
            (d / "crlf.py").write_bytes(b"x = 1\r\n")
            (d / "bad.py").write_bytes(b"\xff\xfe")
            (d / "decomp.py").write_bytes(
                ("x = '" + DECOMPOSED + "'\n").encode("utf-8"))
            r = audit_source_tree(d)
            self.assertEqual(r["files_scanned"], 4)
            self.assertEqual(r["crlf_files"], ["crlf.py"])
            self.assertEqual(r["non_utf8_files"], ["bad.py"])
            self.assertEqual(r["non_nfc_files"], ["decomp.py"])
            self.assertFalse(r["clean"])

    def test_audit_clean_tree(self):
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a.py").write_bytes(b"x = 1\n")
            r = audit_source_tree(td)
            self.assertTrue(r["clean"])
            self.assertEqual(r["files_scanned"], 1)

    def test_real_package_tree_is_canonical(self):
        r = audit_source_tree(ROOT / "samverk")
        self.assertGreater(r["files_scanned"], 100)
        self.assertEqual(r["crlf_files"], [])
        self.assertEqual(r["non_utf8_files"], [])
        self.assertEqual(r["non_nfc_files"], [])

    def test_tool_exits_zero(self):
        out = subprocess.run([sys.executable, "tools/run_path_encoding.py"],
                             cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stdout + out.stderr)
        self.assertIn("VERDICT: CLEAN", out.stdout)


if __name__ == "__main__":
    unittest.main()
