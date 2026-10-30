"""S-010 acceptance battery: output-escaping and sanitisation.

Acceptance (roadmap S-010): one escaping seam for all templates —
*the stored-XSS battery passes.* "Stored" is the shape that matters:
payloads below are the values an attacker saves into a profile, a
repo description, a comment; the battery renders them through the
seam exactly as a page would and asserts no payload survives as
markup, as an attribute breakout, or as a live link.

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.escaping import escape_html_attr, escape_html_text, safe_url

STORED_PAYLOADS = [
    "<script>alert(1)</script>",
    "<img src=x onerror=alert(1)>",
    "<svg onload=alert(1)>",
    "</title><script>alert(1)</script>",
    "<a href='javascript:alert(1)'>click</a>",
    "<details open ontoggle=alert(1)>x",
    "<<script>script>alert(1)<</script>/script>",
]

ATTR_PAYLOADS = [
    '"><script>alert(1)</script>',
    '" onerror="alert(1)',
    "' onmouseover='alert(1)",
    'x" autofocus onfocus="alert(1)',
]

BAD_URLS = [
    "javascript:alert(1)",
    "JaVaScRiPt:alert(1)",
    "  javascript:alert(1)  ",
    "java\tscript:alert(1)",
    "java\nscript:alert(1)",
    "data:text/html;base64,PHNjcmlwdD5hbGVydCgxKTwvc2NyaXB0Pg==",
    "vbscript:msgbox(1)",
    "file:///etc/passwd",
    "//evil.example/phish",
    "&#106;avascript:alert(1)",
    "&#x6a;avascript:alert(1)",
    "javascript&colon;alert(1)",
    "java script:alert(1)",
    "",
    "   ",
]

GOOD_URLS = [
    "https://example.com/repo?x=1&y=2",
    "http://127.0.0.1:8737/healthz",
    "mailto:volmarr@example.invalid",
    "/repos/owner/name",
    "./sibling-page",
    "../up-one",
    "#a-heading",
    "?page=2",
    "docs/page.md",
]


def _render_profile_snippet(name: object, bio: object, website: object) -> str:
    """A page fragment built the way every later template must be:
    user text through the seam, user URL sanitised then attr-escaped,
    no link at all when the URL is refused."""
    url = safe_url(website)
    link = (
        f'<a href="{escape_html_attr(url)}">website</a>' if url else "<span>no website</span>"
    )
    return (
        f"<h1>{escape_html_text(name)}</h1>"
        f'<p class="bio">{escape_html_text(bio)}</p>'
        f'<span data-name="{escape_html_attr(name)}">{link}</span>'
    )


class TextEscapingTests(unittest.TestCase):
    def test_stored_xss_battery(self):
        for payload in STORED_PAYLOADS:
            out = escape_html_text(payload)
            self.assertNotIn("<script", out, payload)
            self.assertNotIn("<img", out, payload)
            self.assertNotIn("<svg", out, payload)
            self.assertNotIn("<details", out, payload)
            # Nothing tag-shaped survives at all.
            self.assertNotIn("<", out, payload)
            self.assertNotIn(">", out, payload)

    def test_plain_text_and_unicode_pass_through(self):
        self.assertEqual(escape_html_text("Hrafn & Sons — café þ ð"), "Hrafn &amp; Sons — café þ ð")

    def test_ampersand_is_escaped_first_not_double(self):
        self.assertEqual(escape_html_text("&lt;"), "&amp;lt;")
        self.assertEqual(escape_html_text("a & b < c"), "a &amp; b &lt; c")

    def test_none_and_non_string_values(self):
        self.assertEqual(escape_html_text(None), "")
        self.assertEqual(escape_html_text(42), "42")


class AttrEscapingTests(unittest.TestCase):
    def test_attribute_breakout_battery(self):
        for payload in ATTR_PAYLOADS:
            out = escape_html_attr(payload)
            self.assertNotIn('"', out, payload)
            self.assertNotIn("'", out, payload)
            self.assertNotIn("<", out, payload)

    def test_quotes_become_entities(self):
        self.assertEqual(escape_html_attr('a"b\'c'), "a&quot;b&#x27;c")


class SafeUrlTests(unittest.TestCase):
    def test_dangerous_urls_are_refused(self):
        for url in BAD_URLS:
            self.assertIsNone(safe_url(url), url)

    def test_legitimate_urls_survive_unchanged(self):
        for url in GOOD_URLS:
            self.assertEqual(safe_url(url), url, url)

    def test_none_is_refused(self):
        self.assertIsNone(safe_url(None))


class StoredProfileBatteryTests(unittest.TestCase):
    def test_rendered_snippet_neutralises_stored_payloads(self):
        for payload in STORED_PAYLOADS:
            page = _render_profile_snippet(payload, payload, "javascript:alert(1)")
            self.assertNotIn("<script", page, payload)
            self.assertNotIn("<img", page, payload)
            self.assertNotIn("<svg", page, payload)
            # The word may survive as inert visible text in the bio —
            # that is escaping working. What must never survive is a
            # *link* carrying it, and the refused website must fall
            # back to the no-link rendering.
            self.assertNotIn('<a href="javascript:', page, payload)
            self.assertNotIn("<a href='javascript:", page, payload)
            self.assertIn("no website", page, payload)

    def test_rendered_snippet_keeps_an_honest_profile_working(self):
        page = _render_profile_snippet("Volmarr & Yrsa", "We build <together>.", "https://example.com/?a=1&b=2")
        self.assertIn("Volmarr &amp; Yrsa", page)
        self.assertIn("We build &lt;together&gt;.", page)
        self.assertIn('href="https://example.com/?a=1&amp;b=2"', page)


class OneSeamTests(unittest.TestCase):
    def test_no_other_module_escapes_directly(self):
        """The seam law, checked mechanically (as S-002 checks the
        platform seam): no samverk module outside escaping.py may
        reach for a direct escaping call."""
        pkg = Path(__file__).resolve().parent.parent / "samverk"
        offenders = []
        for py in pkg.glob("*.py"):
            if py.name == "escaping.py":
                continue
            text = py.read_text(encoding="utf-8")
            if "html.escape" in text or "markupsafe" in text:
                offenders.append(py.name)
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
