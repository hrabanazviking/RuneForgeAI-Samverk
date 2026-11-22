"""S-361 battery — the seam contract, frozen and judged."""
import importlib
import unittest

from samverk import seam_contract as sc


def assertion(**over):
    a = {"provider": "samtal", "audience": "samverk", "consent": True,
         "issued_at": 1000, "expires_at": 1200, "nonce": "n-1",
         "principal": "seat-astrid"}
    a.update(over)
    return a


class ContractShapeTests(unittest.TestCase):
    def test_version_and_sections_frozen(self):
        self.assertEqual(sc.CONTRACT_VERSION, 1)
        self.assertEqual(sc.CONTRACT_SECTIONS,
                         ("identity_link", "embed", "event_bridge", "sovereignty"))
        self.assertEqual(sc.SEAM_PROVIDER, "samtal")
        self.assertEqual(sc.LINK_ASSERTION_MAX_AGE_SECONDS, 300)

    def test_kinds_frozen(self):
        self.assertEqual(sc.EMBED_KINDS, ("repo", "file", "pull_request", "issue", "gist", "release"))
        self.assertEqual(sc.EVENT_KINDS, ("push", "pull_request", "issue", "release"))

    def test_anchors_exist_in_codebase(self):
        for section, modules in sc.ratification_anchors().items():
            self.assertIn(section, sc.CONTRACT_SECTIONS)
            for name in modules:
                self.assertIsNotNone(importlib.import_module(name), name)

    def test_identity_anchor_is_s045_shape(self):
        from samverk import identity_linking
        self.assertEqual(identity_linking.PROVIDER_SAMTAL, sc.SEAM_PROVIDER)

    def test_disabled_by_default(self):
        self.assertFalse(sc.seam_enabled(None))
        self.assertFalse(sc.seam_enabled({}))
        self.assertFalse(sc.seam_enabled({"seam.samtal.enabled": "yes"}))
        self.assertTrue(sc.seam_enabled({"seam.samtal.enabled": True}))


class LinkAssertionTests(unittest.TestCase):
    def test_good_assertion_cleans(self):
        out = sc.validate_link_assertion(assertion(), now=1100, seen_nonces=set())
        self.assertEqual(out["principal"], "seat-astrid")

    def test_wrong_audience_refused(self):
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.validate_link_assertion(assertion(audience="other"), now=1100, seen_nonces=set())
        self.assertEqual(cm.exception.reason, "audience_mismatch")

    def test_consent_required(self):
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.validate_link_assertion(assertion(consent=False), now=1100, seen_nonces=set())
        self.assertEqual(cm.exception.reason, "consent_required")

    def test_expired_and_overlong_refused(self):
        for over in ({"expires_at": 900}, {"expires_at": 2000}):
            with self.assertRaises(sc.SeamContractError) as cm:
                sc.validate_link_assertion(assertion(**over), now=1100, seen_nonces=set())
            self.assertEqual(cm.exception.reason, "assertion_expired")

    def test_replay_refused(self):
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.validate_link_assertion(assertion(), now=1100, seen_nonces={"n-1"})
        self.assertEqual(cm.exception.reason, "assertion_replay")

    def test_provider_mismatch_refused(self):
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.validate_link_assertion(assertion(provider="other"), now=1100, seen_nonces=set())
        self.assertEqual(cm.exception.reason, "provider_mismatch")


class EventAndEmbedTests(unittest.TestCase):
    def test_event_envelope_good(self):
        out = sc.validate_event_envelope({"kind": "push", "idempotency_key": "k1"})
        self.assertEqual(out["kind"], "push")

    def test_event_requires_idempotency(self):
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.validate_event_envelope({"kind": "push"})
        self.assertEqual(cm.exception.reason, "idempotency_required")

    def test_private_event_cannot_leak(self):
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.validate_event_envelope({"kind": "push", "idempotency_key": "k",
                                        "repo_private": True})
        self.assertEqual(cm.exception.reason, "privacy_leak")
        out = sc.validate_event_envelope({"kind": "push", "idempotency_key": "k",
                                          "repo_private": True, "hall_restricted": True})
        self.assertEqual(out["kind"], "push")

    def test_embed_decided_by_viewer_rights(self):
        self.assertEqual(sc.decide_embed("repo", viewer_may_view=True)["decided_by"], "samverk")
        with self.assertRaises(sc.SeamContractError) as cm:
            sc.decide_embed("repo", viewer_may_view=False)
        self.assertEqual(cm.exception.reason, "permission_denied")
        with self.assertRaises(sc.SeamContractError):
            sc.decide_embed("unknown", viewer_may_view=True)


if __name__ == "__main__":
    unittest.main()
