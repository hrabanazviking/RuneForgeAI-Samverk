"""S-274 acceptance battery: wiki web experience.

Acceptance (roadmap S-274): Wiki web experience --
page list, sidebar and footer pages, edit-in-browser
with preview, history via the wiki repo's own log.

The centre is samverk/wiki_web.py: WikiWeb over
S-273's WikiStore. Storage stays the only writer;
this face adds the index (ordinary pages listed,
Sidebar / Footer named apart -- the underscore
forms GitHub uses cannot be stored under S-273's
one-name law, so Samverk's convention drops the
underscore, recorded in the module), page views
rendered through S-107's pipeline with the standing
sidebar and footer rendered beside the body, a
preview that renders a draft and writes nothing
(no wiki created, no tip moved), the save door with
S-273's page_conflict for a tip that moved under
the editor, and history read from git log in the
wiki repository itself -- never the parent repo's
log. No new taxonomy event -- 133 stand; no
migration -- schema 106 stands.

Counted with: python3 -m unittest tests.test_wiki_web -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.repositories import RepositoryStore
from samverk.wiki_storage import WikiStore
from samverk.wiki_web import (
    WikiWeb, WikiWebError, render_wiki_edit_form,
    render_wiki_history_page, render_wiki_index_page,
    render_wiki_page_view, render_wiki_preview)

PW = 'correct horse battery'
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class WikiWebTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / 'samverk.db')
        self.addCleanup(self.conn.close)
        self.clock = Clock()
        self.audit = AuditLog(self.conn, time_fn=self.clock)
        self.accounts = AccountStore(
            self.conn, audit=self.audit, time_fn=self.clock)
        self.owner = self.accounts.register('volmarr', PW)
        self.reader = self.accounts.register('yrsa', PW)
        self.stranger = self.accounts.register('mallory', PW)
        self.repos = RepositoryStore(
            self.conn, self.root, self.accounts,
            audit=self.audit, time_fn=self.clock)
        self.wiki = WikiStore(
            self.conn, self.repos,
            audit=self.audit, time_fn=self.clock)
        self.web = WikiWeb(
            self.conn, self.repos, wiki=self.wiki,
            audit=self.audit, time_fn=self.clock)
        self.repos.create_repository(
            self.owner.id, 'volmarr', 'pub', visibility='public')
        self.repos.create_repository(
            self.owner.id, 'volmarr', 'priv', visibility='private')

    def _reason(self, fn, *a, **k):
        with self.assertRaises(WikiWebError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _wiki_path(self, repo='pub'):
        return self.root / 'repos' / 'volmarr' / (repo + '.wiki')

    def _audit_count(self):
        return self.conn.execute(
            'SELECT COUNT(*) FROM audit_log').fetchone()[0]

    def _seed(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home',
            '# Home\n\nWelcome to the wiki.\n')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Guide',
            '# Guide\n\nSteps.\n')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Sidebar',
            '## Pages\n\n- Home\n- Guide\n')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Footer',
            'Kept by the village.\n')

    # -- page list --------------------------------------

    def test_index_empty_before_any_page_creates_nothing(self):
        index = self.web.index(None, 'volmarr', 'pub')
        self.assertEqual(index.pages, ())
        self.assertIsNone(index.sidebar)
        self.assertIsNone(index.footer)
        self.assertFalse(index.has_pages)
        self.assertFalse(self._wiki_path().exists())
        html = render_wiki_index_page(index)
        self.assertIn('no pages yet', html)

    def test_index_lists_ordinary_pages_and_names_specials_apart(self):
        self._seed()
        index = self.web.index(None, 'volmarr', 'pub')
        self.assertEqual(
            [p.name for p in index.pages], ['Guide', 'Home'])
        self.assertEqual(index.sidebar.name, 'Sidebar')
        self.assertEqual(index.footer.name, 'Footer')
        self.assertTrue(index.has_pages)
        html = render_wiki_index_page(index)
        self.assertIn('wiki-page-list', html)
        self.assertIn('/volmarr/pub/wiki/Guide', html)
        self.assertIn('Sidebar page:', html)
        self.assertIn('Footer page:', html)

    def test_special_pages_match_case_insensitively(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'sidebar', 'links\n')
        index = self.web.index(None, 'volmarr', 'pub')
        self.assertEqual(index.pages, ())
        self.assertEqual(index.sidebar.name, 'sidebar')
        view = self.web.view_page(
            None, 'volmarr', 'pub', 'sidebar')
        self.assertIsNotNone(view.sidebar)

    # -- viewing ------------------------------------------

    def test_view_defaults_to_home_and_renders_markdown(self):
        self._seed()
        view = self.web.view_page(None, 'volmarr', 'pub')
        self.assertEqual(view.page.name, 'Home')
        self.assertIn('<h1', view.body_html)
        self.assertIn('Welcome to the wiki.', view.body_html)
        named = self.web.view_page(None, 'volmarr', 'pub', 'Guide')
        self.assertEqual(named.page.name, 'Guide')
        self.assertIn('Steps.', named.body_html)

    def test_view_renders_sidebar_and_footer_beside_body(self):
        self._seed()
        view = self.web.view_page(None, 'volmarr', 'pub', 'Guide')
        self.assertIn('Pages', view.sidebar_html)
        self.assertIn('Kept by the village.', view.footer_html)
        html = render_wiki_page_view(view)
        self.assertIn('<aside class="wiki-sidebar">', html)
        self.assertIn('<footer class="wiki-footer">', html)
        self.assertIn('wiki-pages', html)

    def test_view_without_specials_has_no_furniture(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# Home\n')
        view = self.web.view_page(None, 'volmarr', 'pub')
        self.assertIsNone(view.sidebar)
        self.assertIsNone(view.footer)
        self.assertEqual(view.sidebar_html, '')
        self.assertEqual(view.footer_html, '')
        html = render_wiki_page_view(view)
        self.assertNotIn('wiki-sidebar', html)
        self.assertNotIn('wiki-footer', html)

    def test_view_missing_page_and_missing_home(self):
        self.assertEqual(
            self._reason(self.web.view_page,
                         None, 'volmarr', 'pub'),
            'page_not_found')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Guide', '# Guide\n')
        self.assertEqual(
            self._reason(self.web.view_page,
                         None, 'volmarr', 'pub'),
            'page_not_found')
        self.assertEqual(
            self._reason(self.web.view_page,
                         None, 'volmarr', 'pub', 'Nope'),
            'page_not_found')

    def test_view_escapes_raw_html_in_body(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home',
            '# Home\n\n<script>alert(1)</script>\n')
        view = self.web.view_page(None, 'volmarr', 'pub')
        self.assertNotIn('<script>', view.body_html)
        self.assertIn('&lt;script&gt;', view.body_html)
        html = render_wiki_page_view(view)
        self.assertNotIn('<script>', html)

    # -- permissions ---------------------------------------

    def test_private_wiki_invisible_on_every_face(self):
        self.web.save_page(
            self.owner, 'volmarr', 'priv', 'Home', '# Secret\n')
        for fn, args in (
                (self.web.index, (self.stranger, 'volmarr', 'priv')),
                (self.web.view_page,
                 (self.stranger, 'volmarr', 'priv')),
                (self.web.history,
                 (self.stranger, 'volmarr', 'priv')),
                (self.web.preview_page,
                 (self.stranger, 'volmarr', 'priv', 'Home', 'x')),
                (self.web.save_page,
                 (self.stranger, 'volmarr', 'priv', 'Home', 'x'))):
            self.assertEqual(self._reason(fn, *args), 'repo_not_found')
        owner_view = self.web.view_page(self.owner, 'volmarr', 'priv')
        self.assertEqual(owner_view.page.name, 'Home')

    # -- preview: renders, writes nothing -------------------

    def test_preview_renders_and_creates_nothing(self):
        preview = self.web.preview_page(
            self.reader, 'volmarr', 'pub', 'Draft Page',
            '# Draft\n\nUnsaved.\n')
        self.assertEqual(preview.name, 'Draft-Page')
        self.assertIn('Unsaved.', preview.body_html)
        self.assertFalse(self._wiki_path().exists())
        self.assertEqual(
            self.web.index(None, 'volmarr', 'pub').pages, ())
        html = render_wiki_preview(preview)
        self.assertIn('nothing has been saved', html)

    def test_preview_does_not_move_a_standing_tip(self):
        self._seed()
        before = self.wiki.list_pages(None, 'volmarr', 'pub')
        tip_before = before[0].commit_oid
        self.web.preview_page(
            self.owner, 'volmarr', 'pub', 'Home',
            '# Changed in draft only\n')
        after = self.wiki.list_pages(None, 'volmarr', 'pub')
        self.assertEqual(after[0].commit_oid, tip_before)
        self.assertEqual(
            self.wiki.read_page(
                None, 'volmarr', 'pub', 'Home').content,
            '# Home\n\nWelcome to the wiki.\n')
        hist = self.web.history(None, 'volmarr', 'pub')
        self.assertEqual(hist.total_commits, 4)

    def test_preview_validation_matches_the_save_law(self):
        self.assertEqual(
            self._reason(self.web.preview_page,
                         self.owner, 'volmarr', 'pub',
                         'bad/title', 'x'),
            'page_title_invalid')
        self.assertEqual(
            self._reason(self.web.preview_page,
                         self.owner, 'volmarr', 'pub',
                         'Home', 'x' * (1024 * 1024 + 1)),
            'page_too_large')
        self.assertEqual(
            self._reason(self.web.preview_page,
                         self.owner, 'volmarr', 'pub',
                         'Home', b'bytes'),
            'page_invalid')

    def test_preview_escapes_a_dangerous_draft(self):
        preview = self.web.preview_page(
            self.reader, 'volmarr', 'pub', 'Draft',
            '# Hi\n\n<script>alert(1)</script>\n\n'
            '[x](javascript:alert(1))\n')
        self.assertNotIn('<script>', preview.body_html)
        self.assertNotIn('javascript:', preview.body_html)

    # -- saving: the write door ------------------------------

    def test_save_round_trip_and_conflict(self):
        page = self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# Home v1\n')
        updated = self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# Home v2\n',
            expected_oid=page.commit_oid)
        self.assertNotEqual(updated.commit_oid, page.commit_oid)
        self.assertEqual(
            self._reason(self.web.save_page,
                         self.owner, 'volmarr', 'pub', 'Home',
                         '# Home v3\n',
                         expected_oid=page.commit_oid),
            'page_conflict')
        self.assertEqual(
            self.wiki.read_page(
                None, 'volmarr', 'pub', 'Home').content,
            '# Home v2\n')

    def test_save_requires_a_writer(self):
        self.assertEqual(
            self._reason(self.web.save_page,
                         self.reader, 'volmarr', 'pub', 'Home', 'x'),
            'permission_denied')
        self.assertEqual(
            self._reason(self.web.save_page,
                         None, 'volmarr', 'pub', 'Home', 'x'),
            'permission_denied')
        self.assertFalse(self._wiki_path().exists())

    def test_edit_form_carries_tip_and_escapes_content(self):
        page = self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home',
            '</textarea><script>alert(1)</script>\n')
        form = render_wiki_edit_form(
            'volmarr/pub', 'Home', page.content, page.commit_oid)
        self.assertIn(page.commit_oid, form)
        self.assertNotIn('<script>', form)
        self.assertIn('&lt;/textarea&gt;', form)
        self.assertIn('value="preview"', form)
        self.assertIn('value="save"', form)

    # -- history: the wiki repo's own log ----------------------

    def test_history_empty_before_wiki_and_creates_nothing(self):
        hist = self.web.history(None, 'volmarr', 'pub')
        self.assertEqual(hist.total_commits, 0)
        self.assertEqual(hist.entries, ())
        self.assertEqual(hist.total_pages, 0)
        self.assertFalse(self._wiki_path().exists())
        html = render_wiki_history_page(hist)
        self.assertIn('No commits on this page.', html)

    def test_history_reads_the_wiki_log_newest_first(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# v1\n',
            message='Open the wiki')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Guide', '# Guide\n',
            message='Add the guide')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# v2\n',
            message='Revise home')
        hist = self.web.history(None, 'volmarr', 'pub')
        self.assertEqual(hist.total_commits, 3)
        self.assertEqual(
            [e.subject for e in hist.entries],
            ['Revise home', 'Add the guide', 'Open the wiki'])
        self.assertTrue(
            all(e.author_name == 'volmarr' for e in hist.entries))
        self.assertEqual(hist.entries[0].pages, ('Home',))
        self.assertEqual(hist.entries[1].pages, ('Guide',))
        self.assertIn('Revise home', hist.entries[0].message)

    def test_history_filter_by_page_including_deleted(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# v1\n')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Guide', '# Guide\n')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# v2\n')
        home = self.web.history(None, 'volmarr', 'pub', 'home')
        self.assertEqual(home.page_title, 'home')
        self.assertEqual(home.total_commits, 2)
        self.assertTrue(
            all(e.pages == ('Home',) for e in home.entries))
        self.wiki.delete_page(self.owner, 'volmarr', 'pub', 'Guide')
        guide = self.web.history(None, 'volmarr', 'pub', 'Guide')
        self.assertEqual(guide.total_commits, 2)
        self.assertEqual(
            guide.entries[0].subject, 'Delete page Guide.md')

    def test_history_pagination_is_honest(self):
        for i in range(5):
            self.web.save_page(
                self.owner, 'volmarr', 'pub', 'Page' + str(i),
                '# Page\n')
        first = self.web.history(
            None, 'volmarr', 'pub', page=1, per_page=2)
        self.assertEqual(first.total_commits, 5)
        self.assertEqual(first.total_pages, 3)
        self.assertEqual(len(first.entries), 2)
        self.assertTrue(first.has_next)
        self.assertFalse(first.has_previous)
        third = self.web.history(
            None, 'volmarr', 'pub', page=3, per_page=2)
        self.assertEqual(len(third.entries), 1)
        self.assertTrue(third.has_previous)
        self.assertFalse(third.has_next)
        past = self.web.history(
            None, 'volmarr', 'pub', page=4, per_page=2)
        self.assertEqual(past.entries, ())
        self.assertEqual(past.total_commits, 5)

    def test_history_bad_title_and_render_escaping(self):
        self.assertEqual(
            self._reason(self.web.history,
                         None, 'volmarr', 'pub', 'bad/title'),
            'page_title_invalid')
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# Home\n',
            message='<script>alert(1)</script>')
        hist = self.web.history(None, 'volmarr', 'pub')
        html = render_wiki_history_page(hist)
        self.assertNotIn('<script>', html)
        self.assertIn('&lt;script&gt;', html)
        self.assertIn('1 commits', html)

    # -- standing invariants -----------------------------------

    def test_schema_and_taxonomy_stand_and_nothing_is_witnessed(self):
        self.assertEqual(schema_version(self.conn), 114)
        before = self._audit_count()
        self._seed()
        self.web.index(None, 'volmarr', 'pub')
        self.web.view_page(None, 'volmarr', 'pub')
        self.web.preview_page(
            self.owner, 'volmarr', 'pub', 'Draft', '# Draft\n')
        self.web.history(None, 'volmarr', 'pub')
        self.assertEqual(self._audit_count(), before)
        self.assertEqual(schema_version(self.conn), 114)


if __name__ == '__main__':
    unittest.main()
