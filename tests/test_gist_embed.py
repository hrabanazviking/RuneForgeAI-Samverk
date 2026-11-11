"""S-281 acceptance battery: gist embedding.

Acceptance (roadmap S-281): Gist embedding -- a
script-free embed snippet (iframe-free by default,
CSP-safe) for blogs and Samtal posts.

The embed is a pure read over S-277's GistStore, in
samverk/gist_embed.py with the face in
samverk/gist_web.py. The default HTML snippet is a
static section -- description, honest visibility
words, every file body as S-010-escaped plain text,
footer link -- with no script, no iframe, no event
handler, no inline style and no javascript: URL, so
it survives S-016's CSP. The Markdown form serves
Samtal posts (its fence grows past any fence in a
body); the iframe form exists only when named and
frames a standalone document declaring default-src
'none', granting no scripts. Links ride a judged
base (S-010's safe_url; base_url_invalid otherwise);
a caller may pin one revision of the gist's own
history or embed one named file. Reading follows
S-278: public and secret alike embeddable by link,
signed in or not; an unknown gist is the uniform
gist_not_found. No storage, no migration: the
schema stands at 111.

No new taxonomy event -- 133 stand (33 auth /
87 repo / 13 admin); gist acts unwitnessed, as
S-277's law, proven here against the audit log.

Counted with: python3 -m unittest tests.test_gist_embed
"""
from __future__ import annotations
import dataclasses, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.gist_embed import (
    GistEmbedStore, embed_to_dict, render_embed_panel,
    validate_base_url, validate_embed_form)
from samverk.gist_web import GistWeb, GistWebError
from samverk.gists import GistError, GistStore

PW = "correct horse battery"
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class GistEmbedTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db")
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register("volmarr", PW)
        self.other = self.accounts.register("yrsa", PW)
        self.gists = GistStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.embeds = GistEmbedStore(
            self.conn, self.root, self.accounts, gists=self.gists,
            audit=self.audit, time_fn=self.clock)
        self.web = GistWeb(
            self.conn, self.root, self.accounts,
            gists=self.gists, audit=self.audit,
            time_fn=self.clock)
        self.gist = self.gists.create_gist(
            self.owner, "demo gist",
            {"hello.py": "print('hi')\n",
             "notes.md": "# Notes\n"}, visibility="public")
        self.secret = self.gists.create_gist(
            self.owner, "quiet gist",
            {"notes.md": "# Quiet\n"}, visibility="secret")

    def _reason(self, fn, *a, **k):
        with self.assertRaises((GistError, GistWebError)) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _audit_count(self):
        return self.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    # -- schema / taxonomy pins ---------------------------

    def test_schema_and_taxonomy_stand(self):
        self.assertEqual(schema_version(self.conn), 111)
        self.assertEqual(db.MIGRATIONS[-1][0], 111)
        self.assertEqual(db.migrate(self.conn), 111)
        from samverk.taxonomy import AUDIT_EVENTS
        self.assertEqual(len(AUDIT_EVENTS), 133)

    def test_embed_acts_are_unwitnessed(self):
        before = self._audit_count()
        self.embeds.snippet(None, self.gist.id)
        self.embeds.snippet(None, self.gist.id, form="markdown")
        self.embeds.snippet(None, self.gist.id, form="iframe")
        self.embeds.embed_document(None, self.gist.id)
        self.assertEqual(self._audit_count(), before)

    def test_embed_writes_nothing(self):
        tables = ("gists", "gist_stars", "gist_comments",
                  "gist_comment_edits", "audit_log")
        before = {t: self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in tables}
        self.embeds.snippet(self.other, self.gist.id)
        after = {t: self.conn.execute(
            f"SELECT COUNT(*) AS n FROM {t}").fetchone()["n"]
            for t in tables}
        self.assertEqual(before, after)
        self.assertEqual(
            self.gists.get_gist(None, self.gist.id).revision_count, 1)

    # -- the default HTML snippet ---------------------------

    def test_html_snippet_shape(self):
        html = self.embeds.snippet(None, self.gist.id)
        self.assertIn('class="gist-embed"', html)
        self.assertIn(f'data-gist="{self.gist.id}"', html)
        self.assertIn("demo gist", html)
        self.assertIn("hello.py", html)
        self.assertIn("notes.md", html)
        self.assertIn("print(&#x27;hi&#x27;)" if "&#x27;" in html
                      else "print('hi')", html)
        self.assertIn(f'href="/gists/{self.gist.id}"', html)
        self.assertIn("Public", html)

    def test_html_snippet_is_script_and_iframe_free(self):
        html = self.embeds.snippet(None, self.gist.id).lower()
        for banned in ("<script", "<iframe", "style=",
                       "javascript:", "onclick", "onerror",
                       "onload"):
            self.assertNotIn(banned, html)

    def test_html_snippet_escapes_hostile_content(self):
        evil = self.gists.create_gist(
            self.owner, '<script>alert(1)</script>',
            {"x.html": "<img src=x onerror=alert(1)>\n"},
            visibility="public")
        html = self.embeds.snippet(None, evil.id)
        self.assertNotIn("<script", html)
        self.assertNotIn("<img", html)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", html)
        self.assertIn("&lt;img src=x onerror=alert(1)&gt;", html)

    def test_html_snippet_absolute_base(self):
        html = self.embeds.snippet(
            None, self.gist.id,
            base_url="https://forge.example/samverk/")
        self.assertIn(
            f'href="https://forge.example/samverk/gists/'
            f'{self.gist.id}"', html)

    def test_secret_snippet_carries_not_private_words(self):
        html = self.embeds.snippet(None, self.secret.id)
        self.assertIn("not private", html)
        self.assertIn("anyone who has the link can read", html)
        md = self.embeds.snippet(
            None, self.secret.id, form="markdown")
        self.assertIn("not private", md)

    # -- markdown form ---------------------------------------

    def test_markdown_snippet_shape(self):
        md = self.embeds.snippet(None, self.gist.id, form="markdown")
        self.assertIn(f"> **Gist {self.gist.id}** by volmarr", md)
        self.assertIn("demo gist", md)
        self.assertIn("**hello.py**", md)
        self.assertIn("print('hi')", md)
        self.assertIn(f"(/gists/{self.gist.id})", md)
        self.assertNotIn("<script", md.lower())
        self.assertNotIn("<section", md)

    def test_markdown_fence_grows_past_body_fence(self):
        tricky = self.gists.create_gist(
            self.owner, "fences", {"a.md": "x\n```\ny\n"},
            visibility="public")
        md = self.embeds.snippet(None, tricky.id, form="markdown")
        self.assertIn("````", md)
        self.assertIn("x\n```\ny", md)

    def test_markdown_description_stays_one_line(self):
        g = self.gists.create_gist(
            self.owner, "one\ntwo", {"a.txt": "b\n"},
            visibility="public")
        md = self.embeds.snippet(None, g.id, form="markdown")
        first = md.splitlines()[0]
        self.assertIn("one two", first)

    # -- iframe form (opt-in only) ----------------------------

    def test_iframe_only_when_named(self):
        framed = self.embeds.snippet(None, self.gist.id, form="iframe")
        self.assertIn("<iframe", framed)
        self.assertIn(
            f'src="/gists/{self.gist.id}/embed"', framed)
        self.assertIn('sandbox="allow-same-origin"', framed)
        self.assertNotIn("allow-scripts", framed)
        self.assertIn('loading="lazy"', framed)
        self.assertIn("title=", framed)
        self.assertIn(f'href="/gists/{self.gist.id}"', framed)
        for form in ("html", "markdown"):
            out = self.embeds.snippet(None, self.gist.id, form=form)
            self.assertNotIn("<iframe", out)

    def test_embed_document_is_self_denying(self):
        doc = self.embeds.embed_document(None, self.gist.id)
        self.assertTrue(doc.startswith("<!DOCTYPE html>"))
        self.assertIn("default-src 'none'", doc)
        self.assertIn('class="gist-embed"', doc)
        self.assertIn("print('hi')", doc)
        lowered = doc.lower()
        self.assertNotIn("<script", lowered)
        self.assertNotIn("<iframe", lowered)

    # -- forms and bases are judged -----------------------------

    def test_form_judged(self):
        self.assertEqual(validate_embed_form("html"), "html")
        self.assertEqual(
            self._reason(self.embeds.snippet, None,
                         self.gist.id, form="script"),
            "embed_form_invalid")
        self.assertEqual(
            self._reason(validate_embed_form, None),
            "embed_form_invalid")

    def test_base_judged(self):
        self.assertEqual(validate_base_url(None), "")
        self.assertEqual(validate_base_url(""), "")
        self.assertEqual(
            validate_base_url("https://forge.example/"),
            "https://forge.example")
        self.assertEqual(validate_base_url("/samverk"), "/samverk")
        for bad in ("javascript:alert(1)", "data:text/html,x",
                    "//evil.example", "mailto:a@b.example",
                    "ftp://forge.example", "https://exa mple"):
            self.assertEqual(
                self._reason(validate_base_url, bad),
                "base_url_invalid", bad)
        self.assertEqual(
            self._reason(self.embeds.snippet, None, self.gist.id,
                         base_url="javascript:alert(1)"),
            "base_url_invalid")

    # -- read law ------------------------------------------------

    def test_unknown_gist_uniform(self):
        for form in ("html", "markdown", "iframe"):
            self.assertEqual(
                self._reason(self.embeds.snippet, None, 999999,
                             form=form),
                "gist_not_found")
        self.assertEqual(
            self._reason(self.embeds.embed_document, None, 999999),
            "gist_not_found")
        self.assertEqual(
            self._reason(self.embeds.snippet, None, "1"),
            "gist_not_found")

    def test_anonymous_and_stranger_may_embed(self):
        self.assertIn("demo gist",
                      self.embeds.snippet(None, self.gist.id))
        self.assertIn("demo gist",
                      self.embeds.snippet(self.other, self.gist.id))
        self.assertIn("quiet gist",
                      self.embeds.snippet(None, self.secret.id))

    # -- single file and pinned revision --------------------------

    def test_single_file_embed(self):
        html = self.embeds.snippet(
            None, self.gist.id, file="notes.md")
        self.assertIn("notes.md", html)
        self.assertNotIn("hello.py", html)
        embed = self.embeds.build_embed(
            None, self.gist.id, file="NOTES.MD")
        self.assertEqual(embed.single_file, "notes.md")
        self.assertEqual([f.name for f in embed.files], ["notes.md"])
        self.assertEqual(
            self._reason(self.embeds.snippet, None, self.gist.id,
                         file="missing.py"),
            "file_not_found")
        self.assertEqual(
            self._reason(self.embeds.snippet, None, self.gist.id,
                         file="../secret"),
            "filename_invalid")

    def test_pinned_revision_quotes_the_past(self):
        first = self.gists.get_gist(self.owner, self.gist.id)
        self.gists.update_gist(
            self.owner, self.gist.id,
            files={"hello.py": "print('bye')\n",
                   "notes.md": "# Notes\n"})
        standing = self.embeds.snippet(None, self.gist.id)
        self.assertIn("print('bye')", standing)
        self.assertNotIn("Pinned at revision", standing)
        pinned = self.embeds.snippet(
            None, self.gist.id, revision=first.head_oid)
        self.assertIn("print('hi')", pinned)
        self.assertNotIn("print('bye')", pinned)
        self.assertIn(f"Pinned at revision {first.head_oid}", pinned)
        md = self.embeds.snippet(
            None, self.gist.id, form="markdown",
            revision=first.head_oid)
        self.assertIn(f"Pinned at revision {first.head_oid}.", md)
        self.assertEqual(
            self._reason(self.embeds.snippet, None, self.gist.id,
                         revision="0" * 40),
            "revision_not_found")

    def test_embed_record_and_dict(self):
        embed = self.embeds.build_embed(
            self.other, self.gist.id,
            base_url="https://forge.example")
        self.assertIsNone(embed.revision)
        self.assertFalse(embed.is_pinned)
        self.assertIsNone(embed.single_file)
        self.assertEqual([f.name for f in embed.files],
                         ["hello.py", "notes.md"])
        d = embed_to_dict(embed)
        self.assertEqual(d["gist_id"], self.gist.id)
        self.assertEqual(d["owner"], "volmarr")
        self.assertEqual(d["visibility"], "public")
        self.assertEqual(
            d["url"], f"https://forge.example/gists/{self.gist.id}")
        self.assertEqual(
            d["document_url"],
            f"https://forge.example/gists/{self.gist.id}/embed")
        self.assertEqual(d["files"], ["hello.py", "notes.md"])

    # -- the web face ----------------------------------------------

    def test_web_embed_doors(self):
        html = self.web.embed_snippet(None, self.gist.id)
        self.assertIn('class="gist-embed"', html)
        doc = self.web.embed_document(None, self.gist.id)
        self.assertIn("default-src 'none'", doc)
        self.assertEqual(
            self._reason(self.web.embed_snippet, None, 999999),
            "gist_not_found")
        self.assertEqual(
            self._reason(self.web.embed_snippet, None, self.gist.id,
                         form="script"),
            "embed_form_invalid")

    def test_view_page_carries_embed_panel(self):
        from samverk.gist_web import render_gist_view_page
        page = render_gist_view_page(
            self.web.view_gist(None, self.gist.id))
        self.assertIn('class="gist-embed-panel"', page)
        self.assertIn("no script and no iframe", page)
        self.assertIn("&lt;section", page)
        self.assertIn('class="gist-embed-snippet"', page)

    def test_render_panel_escapes_snippet_as_text(self):
        panel = render_embed_panel('<section data-x="1">body</section>')
        self.assertIn("&lt;section", panel)
        self.assertNotIn('<section data-x="1">body</section>', panel)
        self.assertIn('class="gist-embed-panel"', panel)


if __name__ == "__main__":
    unittest.main()
