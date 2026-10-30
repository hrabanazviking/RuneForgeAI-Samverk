"""S-112 acceptance battery: permission-aware chrome.

Acceptance (roadmap S-112): tabs and buttons a user
cannot use are absent, not greyed-out teasers; the API
enforces regardless (S-054).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db
from samverk.accounts import AccountStore
from samverk.permissions import PermissionDeniedError, require_role
from samverk.repo_chrome import ChromeError, chrome_for, render_repo_chrome
from samverk.repositories import RepositoryStore

class RepoChromeTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory(); self.addCleanup(self._td.cleanup)
        self.root = Path(self._td.name)
        self.conn = db.init_db(self.root / "samverk.db"); self.addCleanup(self.conn.close)
        self.accounts = AccountStore(self.conn)
        self.owner = self.accounts.register("volmarr", "correct horse battery")
        self.stranger = self.accounts.register("yrsa", "correct horse battery")
        self.repos = RepositoryStore(self.conn, self.root, self.accounts)
        self.repos.create_repository(self.owner.id, "volmarr", "priv", visibility="private")
        self.repos.create_repository(self.owner.id, "volmarr", "pub", visibility="public")
        self.priv = self.repos.get_repository("volmarr", "priv")
        self.pub = self.repos.get_repository("volmarr", "pub")

    def test_owner_sees_settings_and_write_actions(self):
        chrome = chrome_for(self.owner, self.priv)
        labels = [i.label for i in chrome.tabs] + [i.label for i in chrome.actions]
        self.assertIn("Settings", labels)
        self.assertIn("Upload files", labels)
        self.assertIn("Edit repository settings", labels)
        self.assertEqual(chrome.role, "admin")

    def test_reader_chrome_omits_what_it_cannot_use(self):
        chrome = chrome_for(self.stranger, self.pub)
        labels = [i.label for i in chrome.tabs] + [i.label for i in chrome.actions]
        self.assertIn("Code", labels); self.assertIn("Issues", labels)
        self.assertIn("Find a file", labels); self.assertIn("Fork", labels)
        self.assertNotIn("Settings", labels)
        self.assertNotIn("Upload files", labels)
        self.assertNotIn("Edit repository settings", labels)
        html = render_repo_chrome(chrome)
        self.assertNotIn("Settings", html)
        self.assertNotIn("Upload files", html)
        self.assertNotIn("disabled", html)

    def test_collaborator_write_gets_write_not_admin(self):
        chrome = chrome_for(self.stranger, self.priv, collaborator_role="write")
        labels = [i.label for i in chrome.tabs] + [i.label for i in chrome.actions]
        self.assertIn("Upload files", labels)
        self.assertNotIn("Settings", labels)
        self.assertEqual(chrome.role, "write")

    def test_private_repo_chrome_is_not_found_for_strangers(self):
        with self.assertRaises(ChromeError) as caught:
            chrome_for(self.stranger, self.priv)
        self.assertEqual(caught.exception.reason, "repo_not_found")
        with self.assertRaises(ChromeError):
            chrome_for(None, self.priv)
        anon = chrome_for(None, self.pub)
        self.assertEqual(anon.role, "read")

    def test_api_enforces_regardless_of_chrome(self):
        # Chrome hiding is not the gate: the S-054 guard the
        # handlers call refuses the same viewers directly.
        with self.assertRaises(PermissionDeniedError):
            require_role(self.stranger, self.priv, minimum="read")
        with self.assertRaises(PermissionDeniedError):
            require_role(self.stranger, self.pub, minimum="write")
        self.assertEqual(require_role(self.owner, self.priv, minimum="admin"), "admin")

if __name__ == "__main__":
    unittest.main()
