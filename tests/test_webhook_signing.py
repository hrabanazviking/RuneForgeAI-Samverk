"""S-249 acceptance battery: webhook signing.

Acceptance (roadmap S-249): Webhook signing --
HMAC-SHA256 over the raw body, signature header,
verification documented with examples.

The centre is samverk/webhook_signing.py: the
signature covers exactly the delivered bytes
(S-247's payload_json for an event), the header is
X-Samverk-Signature-256 with a sha256= value, and
the HMAC key is the secret's SHA-256 digest -- the
only form S-248 stores -- so the sender signs from
the stored digest and the receiver verifies from
the raw secret it holds, the two roads proven to
agree byte for byte. Written by the keeper after
the team-07 lead relaunch stopped mid-transfer
(2026-11-09 21:5x EST tick).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import hashlib, hmac, sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.event_store import CanonicalEvent
from samverk.webhook_events import payload_json
from samverk.webhook_signing import (
    SIGNATURE_ALGORITHM, SIGNATURE_HEADER, SIGNATURE_PREFIX,
    WebhookSigningError, audit_webhook_signing, body_bytes,
    delivery_headers, parse_signature_header,
    render_webhook_signing_page, sign_event, sign_event_with_digest,
    sign_payload, sign_payload_with_digest, signature_header,
    signature_header_with_digest, signing_key,
    signing_key_from_digest, verify_event_signature,
    verify_event_signature_with_digest, verify_signature,
    verify_signature_with_digest)
from samverk.webhook_subscriptions import secret_digest

SECRET = "a very secret hook secret"
BODY = b'{"event":"repo.issue.create","number":1}'


def independent_signature(body: bytes, secret: str) -> str:
    """The expected signature, recomputed from
    first principles -- hashlib/hmac only, no
    samverk signing code."""
    key = hashlib.sha256(secret.encode("utf-8")).digest()
    return hmac.new(key, body, hashlib.sha256).hexdigest()


def synthetic(verb, **over):
    base = dict(
        id=7, audit_seq=7, actor_kind="user", actor_id=3,
        actor="yrsa", verb=verb, target_kind="repo",
        target_id="volmarr/pub#1",
        refs=("repo:volmarr/pub", "number:1"),
        detail={"number": 1}, outcome="success",
        created_at=1_700_000_000)
    base.update(over)
    return CanonicalEvent(**base)


class HeaderLawTests(unittest.TestCase):
    def test_header_name_prefix_algorithm(self):
        self.assertEqual(SIGNATURE_HEADER, "X-Samverk-Signature-256")
        self.assertEqual(SIGNATURE_PREFIX, "sha256=")
        self.assertEqual(SIGNATURE_ALGORITHM, "HMAC-SHA256")


class BodyBytesTests(unittest.TestCase):
    def test_bytes_are_themselves(self):
        self.assertIs(body_bytes(BODY), BODY)

    def test_bytearray_becomes_bytes(self):
        self.assertEqual(body_bytes(bytearray(BODY)), BODY)

    def test_str_is_utf8_verbatim(self):
        self.assertEqual(body_bytes("abc"), b"abc")
        self.assertEqual(body_bytes("þæö"), "þæö".encode("utf-8"))

    def test_other_shapes_refused_by_name(self):
        for bad in (None, 7, {"a": 1}, ["x"]):
            with self.assertRaises(WebhookSigningError) as cm:
                body_bytes(bad)
            self.assertEqual(cm.exception.reason, "webhook_body_invalid")


class KeyRoadTests(unittest.TestCase):
    def test_signing_key_is_raw_digest(self):
        key = signing_key(SECRET)
        self.assertEqual(len(key), 32)
        self.assertEqual(
            key, hashlib.sha256(SECRET.encode("utf-8")).digest())

    def test_no_secret_refused_by_name(self):
        with self.assertRaises(WebhookSigningError) as cm:
            signing_key(None)
        self.assertEqual(
            cm.exception.reason, "webhook_signing_secret_required")

    def test_digest_road_reads_stored_form(self):
        self.assertEqual(
            signing_key_from_digest(secret_digest(SECRET)),
            signing_key(SECRET))

    def test_bad_digest_refused_by_name(self):
        for bad in ("", "ab", "z" * 64, None, 42):
            with self.assertRaises(WebhookSigningError) as cm:
                signing_key_from_digest(bad)
            self.assertEqual(
                cm.exception.reason, "webhook_signing_digest_invalid")


class SigningTests(unittest.TestCase):
    def test_known_answer(self):
        self.assertEqual(
            sign_payload(BODY, SECRET),
            independent_signature(BODY, SECRET))

    def test_signature_shape(self):
        sig = sign_payload(BODY, SECRET)
        self.assertEqual(len(sig), 64)
        self.assertTrue(all(c in "0123456789abcdef" for c in sig))

    def test_two_roads_agree(self):
        self.assertEqual(
            sign_payload(BODY, SECRET),
            sign_payload_with_digest(BODY, secret_digest(SECRET)))

    def test_header_value_shape(self):
        self.assertEqual(
            signature_header(BODY, SECRET),
            "sha256=" + independent_signature(BODY, SECRET))
        self.assertEqual(
            signature_header_with_digest(BODY, secret_digest(SECRET)),
            signature_header(BODY, SECRET))

    def test_body_and_secret_both_matter(self):
        base = sign_payload(BODY, SECRET)
        self.assertNotEqual(sign_payload(BODY + b" ", SECRET), base)
        self.assertNotEqual(sign_payload(BODY, SECRET + "x"), base)


class DeliveryHeadersTests(unittest.TestCase):
    def test_unsigned_carries_no_header(self):
        self.assertEqual(delivery_headers(BODY, ""), {})
        self.assertEqual(delivery_headers(BODY, None), {})

    def test_signed_carries_exactly_one_header(self):
        headers = delivery_headers(BODY, secret_digest(SECRET))
        self.assertEqual(list(headers), [SIGNATURE_HEADER])
        self.assertEqual(
            headers[SIGNATURE_HEADER],
            "sha256=" + independent_signature(BODY, SECRET))

    def test_malformed_stored_digest_refused(self):
        with self.assertRaises(WebhookSigningError):
            delivery_headers(BODY, "not-a-digest")


class ParseTests(unittest.TestCase):
    def test_parse_round_trip(self):
        value = signature_header(BODY, SECRET)
        self.assertEqual(
            parse_signature_header(value), sign_payload(BODY, SECRET))

    def test_parse_lowercases_hex(self):
        sig = sign_payload(BODY, SECRET)
        self.assertEqual(
            parse_signature_header("sha256=" + sig.upper()), sig)

    def test_missing_by_name(self):
        for missing in (None, "", "   "):
            with self.assertRaises(WebhookSigningError) as cm:
                parse_signature_header(missing)
            self.assertEqual(
                cm.exception.reason, "webhook_signature_missing")

    def test_malformed_by_name(self):
        for bad in ("sha256=xyz", "md5=" + "a" * 64,
                    "sha256=" + "a" * 63, "sha256=" + "g" * 64, 42):
            with self.assertRaises(WebhookSigningError) as cm:
                parse_signature_header(bad)
            self.assertEqual(
                cm.exception.reason, "webhook_signature_malformed")


class VerifyTests(unittest.TestCase):
    def test_accepts_its_own_signature(self):
        self.assertTrue(verify_signature(
            BODY, signature_header(BODY, SECRET), SECRET))

    def test_rejects_tampered_body(self):
        good = signature_header(BODY, SECRET)
        self.assertFalse(verify_signature(BODY + b" ", good, SECRET))
        self.assertFalse(verify_signature(BODY[:-1], good, SECRET))

    def test_rejects_wrong_secret(self):
        good = signature_header(BODY, SECRET)
        self.assertFalse(verify_signature(BODY, good, "other secret"))

    def test_failures_answer_false_never_raise(self):
        good = signature_header(BODY, SECRET)
        self.assertFalse(verify_signature(BODY, None, SECRET))
        self.assertFalse(verify_signature(BODY, "junk", SECRET))
        self.assertFalse(verify_signature(BODY, good, None))
        self.assertFalse(verify_signature(12345, good, SECRET))

    def test_digest_twin_agrees(self):
        good = signature_header_with_digest(BODY, secret_digest(SECRET))
        self.assertTrue(verify_signature_with_digest(
            BODY, good, secret_digest(SECRET)))
        self.assertFalse(verify_signature_with_digest(
            BODY + b"x", good, secret_digest(SECRET)))


class EventRoadTests(unittest.TestCase):
    def test_event_signs_canonical_bytes(self):
        event = synthetic("repo.issue.create")
        self.assertEqual(
            sign_event(event, SECRET),
            signature_header(payload_json(event), SECRET))

    def test_event_verify_round_trip(self):
        event = synthetic("repo.issue.create")
        header = sign_event(event, SECRET)
        self.assertTrue(verify_event_signature(event, header, SECRET))
        changed = synthetic("repo.issue.create", detail={"number": 2})
        self.assertFalse(verify_event_signature(changed, header, SECRET))

    def test_event_digest_twin_agrees(self):
        event = synthetic("repo.issue.create")
        self.assertEqual(
            sign_event_with_digest(event, secret_digest(SECRET)),
            sign_event(event, SECRET))
        header = sign_event(event, SECRET)
        self.assertTrue(verify_event_signature_with_digest(
            event, header, secret_digest(SECRET)))

    def test_unknown_verb_answers_false_on_verify(self):
        event = synthetic("repo.bogus.thing")
        self.assertFalse(verify_event_signature(
            event, signature_header(BODY, SECRET), SECRET))


class AuditAndFaceTests(unittest.TestCase):
    def test_audit_ratified_against_live_docs(self):
        audit = audit_webhook_signing()
        self.assertEqual(audit.problems, ())
        self.assertTrue(audit.ratified)
        self.assertGreaterEqual(audit.checks, 9)

    def test_rendered_page_states_the_law(self):
        page = render_webhook_signing_page(audit_webhook_signing())
        self.assertIn("Webhook signing", page)
        self.assertIn(SIGNATURE_HEADER, page)
        self.assertIn("HMAC-SHA256", page)
        self.assertIn("no signature header", page)
        self.assertIn("Checked, not just claimed", page)
        self.assertNotIn(SECRET, page)


if __name__ == "__main__":
    unittest.main()
