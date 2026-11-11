"""S-276 acceptance battery: wiki access policy.

Acceptance (roadmap S-276): Wiki access policy --
editable by collaborators or by all readers, owner's
choice, shown on the wiki home.

The centre is samverk/wiki_storage.py: the policy is
data (migration 107's wiki_access_policies; no row is
the default 'collaborators'), the pure decide_wiki_edit
judges in S-273's one writer door, only a repository
administrator (S-054 can_admin) sets it, and S-274's
face carries the standing choice onto the wiki home
(the index and the Home page view, in words). No new
taxonomy event -- 133 stand; schema 106 -> 107.

Counted with: python3 -m unittest tests.test_wiki_access -v
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
from samverk.wiki_storage import (
    WikiError, WikiStore, decide_wiki_edit, wiki_policy_words)
from samverk.wiki_web import (
    WikiWeb, WikiWebError, render_wiki_index_page,
    render_wiki_page_view)

PW = 'correct horse battery'
T0 = 1_700_000_000


class Clock:
    def __init__(self, now=T0):
        self.now = now
    def __call__(self):
        return self.now


class WikiAccessTests(unittest.TestCase):
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
        with self.assertRaises(WikiError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _web_reason(self, fn, *a, **k):
        with self.assertRaises(WikiWebError) as ctx:
            fn(*a, **k)
        return ctx.exception.reason

    def _rows(self):
        return self.conn.execute(
            'SELECT COUNT(*) FROM wiki_access_policies').fetchone()[0]

    def _audit_count(self):
        return self.conn.execute(
            'SELECT COUNT(*) FROM audit_log').fetchone()[0]

    def _set_readers(self, repo='pub'):
        return self.wiki.set_access_policy(
            self.owner, 'volmarr', repo, 'readers')

    # -- the standing choice -----------------------------

    def test_default_is_collaborators_with_no_row(self):
        access = self.wiki.access_policy(None, 'volmarr', 'pub')
        self.assertEqual(access.policy, 'collaborators')
        self.assertTrue(access.is_default)
        self.assertIsNone(access.updated_by)
        self.assertEqual(self._rows(), 0)

    def test_owner_sets_readers_and_it_persists(self):
        access = self._set_readers()
        self.assertEqual(access.policy, 'readers')
        self.assertFalse(access.is_default)
        self.assertEqual(access.updated_by, 'volmarr')
        self.assertEqual(access.updated_at, T0)
        fresh = WikiStore(self.conn, self.repos)
        self.assertEqual(
            fresh.access_policy(None, 'volmarr', 'pub').policy,
            'readers')

    def test_owner_can_set_back_to_collaborators(self):
        self._set_readers()
        access = self.wiki.set_access_policy(
            self.owner, 'volmarr', 'pub', 'collaborators')
        self.assertEqual(access.policy, 'collaborators')
        self.assertFalse(access.is_default)

    def test_policy_is_per_repository(self):
        self._set_readers('pub')
        self.assertEqual(
            self.wiki.access_policy(
                self.owner, 'volmarr', 'priv').policy,
            'collaborators')

    def test_reading_policy_creates_no_wiki(self):
        self.wiki.access_policy(None, 'volmarr', 'pub')
        self.assertFalse(
            (self.root / 'repos' / 'volmarr' / 'pub.wiki').exists())

    # -- who may choose -----------------------------------

    def test_reader_cannot_set_policy(self):
        self.assertEqual(
            self._reason(self.wiki.set_access_policy,
                         self.reader, 'volmarr', 'pub', 'readers'),
            'permission_denied')
        self.assertEqual(self._rows(), 0)

    def test_anonymous_cannot_set_policy(self):
        self.assertEqual(
            self._reason(self.wiki.set_access_policy,
                         None, 'volmarr', 'pub', 'readers'),
            'permission_denied')
        self.assertEqual(self._rows(), 0)

    def test_invalid_policy_refused_and_stores_nothing(self):
        for bad in ('everyone', '', None, 'READERS', 42):
            self.assertEqual(
                self._reason(self.wiki.set_access_policy,
                             self.owner, 'volmarr', 'pub', bad),
                'policy_invalid')
        self.assertEqual(self._rows(), 0)

    def test_missing_repo_answers_not_found(self):
        self.assertEqual(
            self._reason(self.wiki.access_policy,
                         None, 'volmarr', 'nope'), 'repo_not_found')
        self.assertEqual(
            self._reason(self.wiki.set_access_policy,
                         self.owner, 'volmarr', 'nope', 'readers'),
            'repo_not_found')

    def test_private_policy_invisible_to_strangers(self):
        self.assertEqual(
            self._reason(self.wiki.access_policy,
                         self.stranger, 'volmarr', 'priv'),
            'repo_not_found')
        self.assertEqual(
            self._reason(self.wiki.access_policy,
                         None, 'volmarr', 'priv'), 'repo_not_found')
        self.assertEqual(
            self._reason(self.wiki.set_access_policy,
                         self.stranger, 'volmarr', 'priv', 'readers'),
            'repo_not_found')

    def test_policy_acts_are_not_witnessed(self):
        before = self._audit_count()
        self._set_readers()
        self.wiki.access_policy(None, 'volmarr', 'pub')
        self.assertEqual(self._audit_count(), before)

    # -- the pure judgement --------------------------------

    def test_decide_wiki_edit_matrix(self):
        cases = [
            ('collaborators', True, True, True, True),
            ('collaborators', True, True, False, False),
            ('readers', True, True, False, True),
            ('readers', True, True, True, True),
            ('readers', False, True, False, False),
            ('readers', False, True, True, False),
            ('readers', True, False, False, False),
            ('collaborators', False, True, True, False),
            ('bogus', True, True, False, False),
            ('bogus', True, True, True, True),
        ]
        for policy, signed, readable, writable, want in cases:
            self.assertEqual(
                decide_wiki_edit(policy, signed_in=signed,
                                 readable=readable, writable=writable),
                want, (policy, signed, readable, writable))

    def test_policy_words(self):
        self.assertIn('collaborators', wiki_policy_words('collaborators'))
        self.assertIn('all readers', wiki_policy_words('readers'))
        self.assertIn('collaborators', wiki_policy_words('bogus'))

    # -- enforcement in the one writer door -----------------

    def test_default_policy_refuses_reader_edits(self):
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.reader, 'volmarr', 'pub',
                         'Home', '# Hi\n'),
            'permission_denied')
        self.assertFalse(self.wiki.can_edit_wiki(
            self.reader, 'volmarr', 'pub'))
        self.assertTrue(self.wiki.can_edit_wiki(
            self.owner, 'volmarr', 'pub'))

    def test_readers_policy_lets_a_reader_create_and_edit(self):
        self._set_readers()
        page = self.wiki.write_page(
            self.reader, 'volmarr', 'pub', 'Home', '# Ours\n')
        self.assertEqual(page.name, 'Home')
        self.wiki.write_page(
            self.owner, 'volmarr', 'pub', 'Guide', '# Steps\n')
        edited = self.wiki.write_page(
            self.reader, 'volmarr', 'pub', 'Guide', '# Steps v2\n')
        self.assertEqual(edited.content, '# Steps v2\n')
        self.assertTrue(self.wiki.can_edit_wiki(
            self.reader, 'volmarr', 'pub'))

    def test_readers_policy_lets_a_reader_delete(self):
        self.wiki.write_page(
            self.owner, 'volmarr', 'pub', 'Home', '# Hi\n')
        self._set_readers()
        gone = self.wiki.delete_page(
            self.reader, 'volmarr', 'pub', 'Home')
        self.assertEqual(gone.name, 'Home')
        self.assertEqual(
            self.wiki.list_pages(None, 'volmarr', 'pub'), [])

    def test_setting_back_restores_the_refusal(self):
        self._set_readers()
        self.wiki.set_access_policy(
            self.owner, 'volmarr', 'pub', 'collaborators')
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.reader, 'volmarr', 'pub',
                         'Home', '# Hi\n'),
            'permission_denied')

    def test_anonymous_never_edits_under_readers(self):
        self._set_readers()
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         None, 'volmarr', 'pub', 'Home', '# Hi\n'),
            'permission_denied')
        self.assertFalse(self.wiki.can_edit_wiki(None, 'volmarr', 'pub'))

    def test_readers_policy_never_widens_a_private_wiki(self):
        self.wiki.set_access_policy(
            self.owner, 'volmarr', 'priv', 'readers')
        self.assertEqual(
            self._reason(self.wiki.write_page,
                         self.stranger, 'volmarr', 'priv',
                         'Home', '# Hi\n'),
            'repo_not_found')
        self.assertEqual(
            self._reason(self.wiki.can_edit_wiki,
                         self.stranger, 'volmarr', 'priv'),
            'repo_not_found')

    # -- shown on the wiki home ------------------------------

    def test_index_carries_the_default_choice_in_words(self):
        index = self.web.index(None, 'volmarr', 'pub')
        self.assertEqual(index.access_policy, 'collaborators')
        html = render_wiki_index_page(index)
        self.assertIn('Wiki access', html)
        self.assertIn('Editable by collaborators', html)

    def test_index_and_home_show_readers_after_the_choice(self):
        self.web.save_page(
            self.owner, 'volmarr', 'pub', 'Home', '# Home\n')
        self.web.set_access_policy(
            self.owner, 'volmarr', 'pub', 'readers')
        index = self.web.index(None, 'volmarr', 'pub')
        self.assertEqual(index.access_policy, 'readers')
        self.assertIn('Editable by all readers',
                      render_wiki_index_page(index))
        view = self.web.view_page(None, 'volmarr', 'pub')
        self.assertEqual(view.access_policy, 'readers')
        html = render_wiki_page_view(view)
        self.assertIn('Wiki access', html)
        self.assertIn('Editable by all readers', html)

    def test_web_save_follows_the_policy(self):
        self.assertEqual(
            self._web_reason(self.web.save_page,
                             self.reader, 'volmarr', 'pub',
                             'Home', '# Hi\n'),
            'permission_denied')
        self.web.set_access_policy(
            self.owner, 'volmarr', 'pub', 'readers')
        page = self.web.save_page(
            self.reader, 'volmarr', 'pub', 'Home', '# Hi\n')
        self.assertEqual(page.name, 'Home')
        self.assertTrue(self.web.can_edit(self.reader, 'volmarr', 'pub'))
        self.assertFalse(self.web.can_edit(None, 'volmarr', 'pub'))

    def test_web_set_refusal_carries_the_reason(self):
        self.assertEqual(
            self._web_reason(self.web.set_access_policy,
                             self.reader, 'volmarr', 'pub', 'readers'),
            'permission_denied')
        self.assertEqual(
            self.web.access_policy(None, 'volmarr', 'pub').policy,
            'collaborators')

    # -- pins ---------------------------------------------------

    def test_schema_and_taxonomy_pins(self):
        self.assertEqual(schema_version(self.conn), 111)
        self.assertEqual(db.MIGRATIONS[-1][0], 111)
        names = [n for n, in self.conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")]
        self.assertIn('wiki_access_policies', names)


if __name__ == '__main__':
    unittest.main()
