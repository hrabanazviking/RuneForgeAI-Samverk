"""S-107 acceptance battery: Markdown pipeline.

Acceptance (roadmap S-107): sanitised rendering (S-010 seam):
headings with anchors, task lists, tables, code fences; XSS
battery on every construct.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.markdown_pipeline import render_markdown, slugify


class MarkdownPipelineTests(unittest.TestCase):
    def test_headings_carry_deduplicated_anchors(self):
        html = render_markdown("# Hello World\n\n## Hello World\n\n# Hello, World!\n")
        self.assertIn('<h1 id="hello-world">Hello World', html)
        self.assertIn('href="#hello-world"', html)
        self.assertIn('<h2 id="hello-world-1">', html)
        self.assertIn('<h1 id="hello-world-2">', html)
        self.assertEqual(slugify("A  B_c", {}), "a-b-c")
        setext = render_markdown("Big Title\n===\n\nSub Title\n---\n")
        self.assertIn('<h1 id="big-title">', setext)
        self.assertIn('<h2 id="sub-title">', setext)

    def test_task_ordered_and_nested_lists(self):
        html = render_markdown(
            "- [ ] todo item\n- [x] done item\n- plain\n\n"
            "1. first\n2. second\n\n- outer\n  - inner\n")
        self.assertIn('<li class="task-list-item"><input type="checkbox" disabled> todo item</li>', html)
        self.assertIn('<input type="checkbox" disabled checked> done item', html)
        self.assertIn("<li>plain</li>", html)
        self.assertIn("<ol>", html); self.assertIn("<li>first</li>", html)
        self.assertIn("<li>outer\n<ul>", html); self.assertIn("<li>inner</li>", html)

    def test_tables_with_alignment_and_inline_cells(self):
        html = render_markdown(
            "| Name | Count | Side |\n|:-----|------:|:----:|\n"
            "| **a** | 3 | mid |\n| b |\n")
        self.assertIn("<table>", html)
        self.assertIn('<th align="left">Name</th>', html)
        self.assertIn('<th align="right">Count</th>', html)
        self.assertIn('<th align="center">Side</th>', html)
        self.assertIn("<td align=\"left\"><strong>a</strong></td>", html)
        self.assertIn('<td align="right">3</td>', html)
        # A short row is padded, never ragged.
        self.assertIn('<td align="center"></td>', html)

    def test_code_fences_quotes_rules_and_inline_marks(self):
        html = render_markdown(
            "```python\nx = \"<b>\"\n```\n\n"
            "> quoted **text**\n\n---\n\n"
            "Use `a<b` and *em* and ~~gone~~ and snake_case_words stay.\n")
        self.assertIn('<pre><code class="language-python">', html)
        self.assertIn("x = \"&lt;b&gt;\"", html)
        self.assertIn("<blockquote>", html); self.assertIn("<strong>text</strong>", html)
        self.assertIn("<hr>", html)
        self.assertIn("<code>a&lt;b</code>", html)
        self.assertIn("<em>em</em>", html); self.assertIn("<del>gone</del>", html)
        self.assertIn("snake_case_words", html); self.assertNotIn("snake<em>", html)
        plain = render_markdown("```\ncode\n")
        self.assertIn("<pre><code>code</code></pre>", plain)

    def test_links_images_and_reference_style(self):
        html = render_markdown(
            "See [the docs](https://example.com/d?a=1&b=2) and "
            "[mail](mailto:a@example.com).\n\n"
            "![a <cat>](https://example.com/cat.png)\n\n"
            "[ref link][d]\n\n[d]: https://example.com/ref\n\n"
            "Bare https://example.com/bare, ends.\n")
        self.assertIn('<a href="https://example.com/d?a=1&amp;b=2">the docs</a>', html)
        self.assertIn('<a href="mailto:a@example.com">mail</a>', html)
        self.assertIn('<img src="https://example.com/cat.png" alt="a &lt;cat&gt;">', html)
        self.assertIn('<a href="https://example.com/ref">ref link</a>', html)
        self.assertIn('<a href="https://example.com/bare">https://example.com/bare</a>, ends.', html)
        self.assertNotIn("[d]:", html)

    def test_xss_battery_on_every_construct(self):
        attacks = [
            "<script>alert(1)</script>",
            "# <script>alert(1)</script>",
            "- <img src=x onerror=alert(1)>",
            "> <svg onload=alert(1)>",
            "| <script>x</script> |\n|---|\n| <b>bold</b> |",
            "```\n<script>alert(1)</script>\n```",
            "[click](javascript:alert(1))",
            "[click](JaVaScRiPt:alert(1))",
            "[click](&#106;avascript:alert(1))",
            "[click](data:text/html,<script>alert(1)</script>)",
            "[click](//evil.example/x)",
            "![x](javascript:alert(1))",
            "![\" onerror=\"alert(1)](https://example.com/i.png)",
            "[a\" onclick=\"alert(1)](https://example.com)",
            "<a href=\"https://example.com\" onclick=\"alert(1)\">raw</a>",
            "- [ ] <script>alert(1)</script>",
            "**<script>alert(1)</script>**",
            "`<script>alert(1)</script>`",
        ]
        # Parse the output for real: no emitted tag may be a
        # dangerous element, no attribute may be an event
        # handler, and no href/src may carry a dangerous scheme.
        # (Attack words may survive as escaped, visible text —
        # that is the pipeline working, not a hole.)
        from html.parser import HTMLParser
        class Audit(HTMLParser):
            def __init__(self):
                super().__init__(); self.tags = []
            def handle_starttag(self, tag, attrs):
                self.tags.append((tag, dict(attrs)))
            handle_startendtag = handle_starttag
        allowed = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol",
                   "li", "pre", "code", "strong", "em", "del", "a", "img",
                   "table", "thead", "tbody", "tr", "th", "td",
                   "blockquote", "hr", "input"}
        for attack in attacks:
            html = render_markdown(attack)
            self.assertNotIn("<script", html, attack)
            audit = Audit(); audit.feed(html)
            for tag, attrs in audit.tags:
                self.assertIn(tag, allowed, (attack, tag))
                for name, value in attrs.items():
                    self.assertFalse(name.startswith("on"), (attack, name))
                    if name in ("href", "src") and value:
                        self.assertFalse(
                            value.lower().startswith(
                                ("javascript:", "data:", "vbscript:", "//")),
                            (attack, value))
        # An unsafe link degrades to its text; an unsafe image
        # degrades to its alt text — nothing vanishes, nothing
        # becomes clickable.
        self.assertIn("<p>click</p>", render_markdown("[click](javascript:alert(1))"))
        self.assertIn("<p>kitty</p>", render_markdown("![kitty](data:image/png;base64,AAAA)"))
        # A safe image's alt cannot break out of its attribute.
        html = render_markdown("![\" onerror=\"alert(1)](https://example.com/i.png)")
        self.assertIn("&quot;", html)

    def test_resolver_seams_for_s108_and_s109(self):
        seen = []
        def links(url, kind):
            seen.append((url, kind))
            if url == "docs/guide.md":
                return "/o/r/blob/main/docs/guide.md"
            return None
        html = render_markdown("[g](docs/guide.md) [x](https://example.com)",
                               link_resolver=links)
        self.assertIn('<a href="/o/r/blob/main/docs/guide.md">g</a>', html)
        self.assertIn(" x</p>", html)  # the refused link degrades to its text
        self.assertIn(("docs/guide.md", "link"), seen)
        self.assertIn(("https://example.com", "link"), seen)

        def refs(kind, value):
            return {("mention", "volmarr"): "/volmarr",
                    ("issue", "42"): "/o/r/issues/42",
                    ("commit", "abc1234"): "/o/r/commit/abc1234"}.get((kind, value))
        html = render_markdown(
            "Hi @volmarr, see #42 and abc1234, not deadbeef or a@b.example",
            reference_resolver=refs)
        self.assertIn('<a href="/volmarr">@volmarr</a>', html)
        self.assertIn('<a href="/o/r/issues/42">#42</a>', html)
        self.assertIn('<a href="/o/r/commit/abc1234">abc1234</a>', html)
        self.assertIn("deadbeef", html); self.assertNotIn('href="/o/r/commit/deadbeef"', html)
        self.assertNotIn('<a href="/b.example"', html)
        # Without a resolver, references stay plain text.
        plain = render_markdown("Hi @volmarr, see #42")
        self.assertNotIn("<a href", plain)

    def test_malformed_input_renders_as_text_never_raises(self):
        for odd in ("", "[unclosed](", "```", "#", "|\n|", "- ", ">>>", None):
            html = render_markdown(odd)
            self.assertIsInstance(html, str)
        self.assertEqual(render_markdown(None), "")
        self.assertEqual(render_markdown(""), "")


if __name__ == "__main__":
    unittest.main()
