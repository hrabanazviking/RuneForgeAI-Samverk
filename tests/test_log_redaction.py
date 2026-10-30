"""S-018 acceptance battery: log redaction.

Acceptance (roadmap S-018): tokens, passwords, and secrets are
filtered before any log write — *seeded secrets never appear in
captured logs.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import io
import logging
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.log_redaction import (
    REDACTED,
    RedactingFilter,
    clear_registered_secrets,
    install_redaction,
    redact_text,
    register_secret,
)

SEEDED = "seeded-secret-value-9f27"
SESSION = "session-token-abcdef0123456789"


def _capture() -> tuple[logging.Logger, io.StringIO]:
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    logger = logging.getLogger(f"test-redaction-{id(stream)}")
    logger.handlers = [handler]
    logger.filters = [RedactingFilter()]
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    return logger, stream


class SeededSecretTests(unittest.TestCase):
    def setUp(self):
        clear_registered_secrets()

    def tearDown(self):
        clear_registered_secrets()

    def test_seeded_secret_never_reaches_a_captured_log(self):
        """The acceptance in its literal form."""
        register_secret(SEEDED)
        register_secret(SESSION)
        logger, stream = _capture()
        logger.info("login attempt with password %s", SEEDED)
        logger.info("stored value is %s in the row", SEEDED)
        logger.info("cookie session=%s presented", SESSION)
        logger.info('payload {"api_key": "%s"}', SEEDED)
        out = stream.getvalue()
        self.assertNotIn(SEEDED, out)
        self.assertNotIn(SESSION, out)
        self.assertIn(REDACTED, out)

    def test_too_short_values_are_not_registered(self):
        self.assertFalse(register_secret("abc"))
        self.assertFalse(register_secret(12345))
        self.assertTrue(register_secret("abcd"))


class ShapeTests(unittest.TestCase):
    def test_credential_shapes_are_struck_by_shape(self):
        cases = [
            "password=hunter2-and-more",
            "token: abcdef0123456789",
            '"session": "abcdef0123456789"',
            "csrf_token='abcdef0123456789'",
            "Authorization: Bearer abcdef0123456789",
            "send Bearer abcdef0123456789 now",
            "Cookie: session=abcdef0123456789; theme=dark",
            "GET /cb?token=abcdef0123456789&next=/home HTTP/1.1",
        ]
        for text in cases:
            out = redact_text(text)
            self.assertNotIn("abcdef0123456789", out, msg=text)
            self.assertNotIn("hunter2-and-more", out, msg=text)

    def test_keys_survive_so_logs_stay_debuggable(self):
        out = redact_text("login failed password=whatever123")
        self.assertIn("password=", out)
        self.assertIn(REDACTED, out)

    def test_compound_keys_strike_but_mere_substrings_do_not(self):
        # csrf_token / auth_token: the sensitive word is a whole
        # _-separated segment — struck. author: "auth" is only a
        # substring of its single segment — untouched.
        self.assertNotIn(
            "abcdef0123456789",
            redact_text("csrf_token='abcdef0123456789'"))
        self.assertNotIn(
            "abcdef0123456789",
            redact_text("auth_token=abcdef0123456789"))
        self.assertEqual(
            redact_text("author=volmarr pushed"), "author=volmarr pushed")

    def test_ordinary_text_and_git_shas_are_untouched(self):
        text = ("user volmarr pushed commit "
                "9a30e80f1b2c3d4e5f60718293a4b5c6d7e8f901 "
                "from 127.0.0.1 in 42 ms")
        self.assertEqual(redact_text(text), text)


class InstallTests(unittest.TestCase):
    def test_install_redaction_is_idempotent(self):
        logger = logging.getLogger("test-redaction-install")
        logger.filters = [
            f for f in logger.filters
            if not isinstance(f, RedactingFilter)]
        first = install_redaction(logger)
        second = install_redaction(logger)
        self.assertIs(first, second)
        self.assertEqual(
            sum(isinstance(f, RedactingFilter) for f in logger.filters), 1)


if __name__ == "__main__":
    unittest.main()
