"""S-400 acceptance battery: release packaging.

Acceptance (roadmap S-400): source tarball with
checksums (S-260 machinery), signed by the maintainer
key, notes written in plain words first. This battery
keeps the packaging honest mechanically: the tarball is
deterministic, the checksums round-trip through S-260's
own parser and verifier and name tampering, the signing
verdict never invents a key, and the notes open in
plain words with the signing state said there.

Counted with: python3 -m unittest tests.test_release_packaging -v
"""
from __future__ import annotations

import gzip, hashlib, io, sys, tarfile, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.release_checksums import parse_checksums
from samverk.release_packaging import (
    CHECKSUMS_NAME, RELEASE_NAME, TARBALL_NAME, PackagingError,
    build_checksums, build_tarball_bytes, judge_signing,
    package_files, render_release_notes, select_source_files,
    verify_package)

FILES = {"samverk/__init__.py": b"x = 1\n",
    "docs/NOTE.md": b"# hi\n", "README.md": b"readme\n"}


class SelectionTests(unittest.TestCase):
    def test_machinery_is_never_source(self):
        picked = select_source_files(["a.py", ".git/config",
            "pkg/__pycache__/m.pyc", "pkg/m.pyc", "b.py", "a.py"])
        self.assertEqual(picked, ("a.py", "b.py"))

    def test_empty_source_is_refused(self):
        with self.assertRaises(PackagingError) as ctx:
            build_tarball_bytes({".git/config": b"x"})
        self.assertEqual(ctx.exception.reason, "packaging_empty")


class TarballTests(unittest.TestCase):
    def test_deterministic_bytes(self):
        self.assertEqual(build_tarball_bytes(FILES),
            build_tarball_bytes(dict(reversed(list(FILES.items())))))

    def test_members_prefixed_sorted_and_stamped(self):
        raw = gzip.decompress(build_tarball_bytes(FILES))
        with tarfile.open(fileobj=io.BytesIO(raw)) as tar:
            members = tar.getmembers()
            self.assertEqual([m.name for m in members],
                [f"{RELEASE_NAME}/README.md",
                 f"{RELEASE_NAME}/docs/NOTE.md",
                 f"{RELEASE_NAME}/samverk/__init__.py"])
            for m in members:
                self.assertEqual((m.mtime, m.uid, m.gid), (0, 0, 0))
            self.assertEqual(
                tar.extractfile(members[0]).read(), b"readme\n")


class ChecksumsTests(unittest.TestCase):
    def test_s260_format_round_trip(self):
        audit = package_files(FILES)
        entries = parse_checksums(audit["checksums"])
        self.assertEqual([e.name for e in entries], [TARBALL_NAME])
        self.assertEqual(entries[0].sha256, audit["tarball_sha256"])
        self.assertEqual(audit["checksums"],
            build_checksums({TARBALL_NAME:
                build_tarball_bytes(FILES)}))

    def test_verification_names_tampering(self):
        audit = package_files(FILES)
        good = verify_package(audit["checksums"],
            {TARBALL_NAME: build_tarball_bytes(FILES)})
        self.assertTrue(good["ok"])
        bad = verify_package(audit["checksums"],
            {TARBALL_NAME: b"tampered"})
        self.assertFalse(bad["ok"])
        self.assertEqual(bad["mismatched"], [TARBALL_NAME])
        gone = verify_package(audit["checksums"], {})
        self.assertEqual(gone["missing"], [TARBALL_NAME])


class SigningTests(unittest.TestCase):
    def test_no_key_is_the_named_remainder(self):
        verdict = judge_signing([])
        self.assertEqual(verdict.status, "unsigned_remainder")
        self.assertEqual(verdict.owner, "Volmarr")
        self.assertIn("S-263", verdict.detail)

    def test_a_held_key_signs_and_is_named(self):
        verdict = judge_signing(["ABC123"])
        self.assertEqual(verdict.status, "signed")
        self.assertIn("ABC123", verdict.detail)


class NotesTests(unittest.TestCase):
    def test_plain_words_first_and_signing_said(self):
        notes = render_release_notes(package_files(FILES))
        self.assertLess(notes.index("## In plain words"),
            notes.index("## What is in the package"))
        self.assertIn("not signed yet", notes)
        self.assertIn("sha256sum -c SHA256SUMS.txt", notes)
        self.assertIn(CHECKSUMS_NAME, notes)

    def test_notes_carry_the_honest_remainders(self):
        notes = render_release_notes(package_files(FILES))
        for marker in ("F-02", "F-10", "F-11", "F-17"):
            self.assertIn(marker, notes)


if __name__ == "__main__":
    unittest.main()
