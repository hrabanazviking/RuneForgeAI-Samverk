"""S-012 acceptance battery: upload handling law.

Acceptance (roadmap S-012): content sniffing beats declared type,
size caps, quarantine path — *a disguised payload is rejected in
test.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.uploads import (
    UploadPolicy,
    UploadRejected,
    inspect_upload,
    save_to_quarantine,
    sniff_content_type,
)

PNG_BYTES = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
JPEG_BYTES = b"\xff\xd8\xff\xe0" + b"\x00" * 64
GIF_BYTES = b"GIF89a" + b"\x00" * 64
PDF_BYTES = b"%PDF-1.7\n" + b"%\x00" * 8
SCRIPT_BYTES = b"#!/bin/sh\nrm -rf / # totally an image, trust me\n"
EXE_BYTES = b"MZ\x90\x00" + b"\x00" * 128
HTML_BYTES = b"<html><script>alert(1)</script></html>\n"
TEXT_BYTES = "A perfectly ordinary release note.\n".encode("utf-8")


class SniffTests(unittest.TestCase):
    def test_magic_numbers_identify_real_types(self):
        self.assertEqual(sniff_content_type(PNG_BYTES), "image/png")
        self.assertEqual(sniff_content_type(JPEG_BYTES), "image/jpeg")
        self.assertEqual(sniff_content_type(GIF_BYTES), "image/gif")
        self.assertEqual(sniff_content_type(PDF_BYTES), "application/pdf")

    def test_unknown_binary_is_octet_stream_never_upgraded(self):
        self.assertEqual(sniff_content_type(EXE_BYTES), "application/octet-stream")
        self.assertEqual(sniff_content_type(b"\x01\x02\x03\xff"), "application/octet-stream")


class InspectTests(unittest.TestCase):
    def test_disguised_payload_is_rejected(self):
        """The acceptance in its literal form: a shell script and an
        executable, each declaring itself an image, are refused —
        the sniff, not the claim, decides."""
        for payload in (SCRIPT_BYTES, EXE_BYTES, HTML_BYTES):
            with self.assertRaises(UploadRejected):
                inspect_upload(payload, declared_type="image/png")

    def test_disguise_reason_is_named(self):
        # Script bytes sniff as text; text is allowed, but claiming
        # to be a PNG makes the upload a disguise, not a text file.
        with self.assertRaises(UploadRejected) as caught:
            inspect_upload(SCRIPT_BYTES, declared_type="image/png")
        self.assertEqual(caught.exception.reason, "type_mismatch")
        # The executable sniffs as a type the policy does not allow.
        with self.assertRaises(UploadRejected) as caught:
            inspect_upload(EXE_BYTES, declared_type="application/octet-stream")
        self.assertEqual(caught.exception.reason, "type_not_allowed")

    def test_honest_uploads_are_accepted_with_sniffed_type(self):
        info = inspect_upload(PNG_BYTES, declared_type="image/png")
        self.assertEqual(info.detected_type, "image/png")
        self.assertEqual(info.size, len(PNG_BYTES))
        self.assertEqual(len(info.sha256), 64)

    def test_generic_declared_type_defers_to_the_sniff(self):
        info = inspect_upload(JPEG_BYTES, declared_type="application/octet-stream")
        self.assertEqual(info.detected_type, "image/jpeg")

    def test_size_cap_and_empty_are_refused(self):
        policy = UploadPolicy(max_bytes=16, allowed_types=frozenset({"image/png"}))
        with self.assertRaises(UploadRejected) as caught:
            inspect_upload(PNG_BYTES, declared_type="image/png", policy=policy)
        self.assertEqual(caught.exception.reason, "too_large")
        with self.assertRaises(UploadRejected) as caught:
            inspect_upload(b"")
        self.assertEqual(caught.exception.reason, "empty")

    def test_policy_can_refuse_a_type_the_default_allows(self):
        policy = UploadPolicy(allowed_types=frozenset({"text/plain"}))
        with self.assertRaises(UploadRejected):
            inspect_upload(PNG_BYTES, declared_type="image/png", policy=policy)
        self.assertEqual(
            inspect_upload(TEXT_BYTES, declared_type="text/plain", policy=policy).detected_type,
            "text/plain",
        )


class QuarantineTests(unittest.TestCase):
    def test_accepted_upload_lands_in_quarantine_content_addressed(self):
        with tempfile.TemporaryDirectory() as td:
            path = save_to_quarantine(Path(td), PNG_BYTES, declared_type="image/png")
            self.assertEqual(path.parent, Path(td) / "quarantine")
            self.assertTrue(path.name.endswith(".png"))
            self.assertEqual(path.read_bytes(), PNG_BYTES)
            # Content-addressed: the name is the digest, so the same
            # bytes always land at the same path.
            again = save_to_quarantine(Path(td), PNG_BYTES, declared_type="image/png")
            self.assertEqual(again, path)

    def test_rejected_upload_writes_nothing(self):
        with tempfile.TemporaryDirectory() as td:
            with self.assertRaises(UploadRejected):
                save_to_quarantine(Path(td), SCRIPT_BYTES, declared_type="image/png")
            self.assertFalse((Path(td) / "quarantine").exists())


if __name__ == "__main__":
    unittest.main()
