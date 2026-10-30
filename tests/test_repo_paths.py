"""S-013 acceptance battery: repository path resolution.

Acceptance (roadmap S-013): traversal-proof mapping from names to
disk paths — *the `..`/symlink escape battery passes.*

Counted with: python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk.repo_paths import (
    RepoPathError,
    owner_dir,
    repo_path,
    validate_owner_name,
    validate_repo_name,
)


class NameLawTests(unittest.TestCase):
    def test_ordinary_names_pass_and_resolve_inside_the_root(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "repos"
            path = repo_path(Path(td), "volmarr", "samverk")
            self.assertEqual(path, (root / "volmarr" / "samverk.git").resolve())
            self.assertEqual(validate_owner_name("yrsa-2"), "yrsa-2")
            self.assertEqual(validate_repo_name("my.repo_v2"), "my.repo_v2")

    def test_dot_git_suffix_is_canonicalised(self):
        self.assertEqual(validate_repo_name("samverk.git"), "samverk")
        self.assertEqual(validate_repo_name("samverk.GIT"), "samverk")
        with tempfile.TemporaryDirectory() as td:
            self.assertEqual(
                repo_path(Path(td), "o", "r.git"),
                repo_path(Path(td), "o", "r"),
            )

    def test_traversal_and_separator_names_are_refused(self):
        bad = ["..", "../escape", "a/../../b", "a/b", "a\\b", "/abs",
               "a b", "", ".", ".hidden", "a..b", "...", "name.",
               "na\x00me", "café", "-leading-dash-ok-but-not-this--.."]
        for name in bad:
            with self.assertRaises(RepoPathError, msg=name):
                validate_repo_name(name)
            with self.assertRaises(RepoPathError, msg=name):
                validate_owner_name(name)

    def test_escape_reasons_are_named(self):
        with self.assertRaises(RepoPathError) as caught:
            validate_repo_name("../escape")
        self.assertIn(caught.exception.reason,
                      {"path_separator", "dotdot", "bad_characters"})

    def test_windows_device_names_are_refused_everywhere(self):
        for name in ("CON", "con", "PRN", "AUX", "NUL.txt", "COM1",
                     "lpt9.repo"):
            with self.assertRaises(RepoPathError, msg=name) as caught:
                validate_repo_name(name)
            self.assertEqual(caught.exception.reason, "reserved_name")

    def test_length_caps_are_enforced(self):
        self.assertEqual(validate_owner_name("a" * 39), "a" * 39)
        with self.assertRaises(RepoPathError):
            validate_owner_name("a" * 40)
        with self.assertRaises(RepoPathError):
            validate_repo_name("a" * 101)


class ContainmentTests(unittest.TestCase):
    def test_symlinked_owner_dir_escaping_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside"
            outside.mkdir()
            root = base / "repos"
            root.mkdir()
            (root / "mallory").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RepoPathError) as caught:
                repo_path(base, "mallory", "loot")
            self.assertEqual(caught.exception.reason, "escapes_root")
            with self.assertRaises(RepoPathError):
                owner_dir(base, "mallory")

    def test_symlinked_repo_path_escaping_the_root_is_refused(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            outside = base / "outside.git"
            outside.mkdir()
            owner = base / "repos" / "volmarr"
            owner.mkdir(parents=True)
            (owner / "samverk.git").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(RepoPathError) as caught:
                repo_path(base, "volmarr", "samverk")
            self.assertEqual(caught.exception.reason, "escapes_root")

    def test_symlink_staying_inside_the_root_is_allowed(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            real_owner = base / "repos" / "real"
            real_owner.mkdir(parents=True)
            (base / "repos" / "alias").symlink_to(
                real_owner, target_is_directory=True)
            path = repo_path(base, "alias", "samverk")
            self.assertEqual(
                path, (real_owner / "samverk.git").resolve())

    def test_not_yet_created_repositories_resolve(self):
        """Creation (S-049) resolves paths for repos that do not
        exist yet; the resolution must still be contained."""
        with tempfile.TemporaryDirectory() as td:
            path = repo_path(Path(td), "newowner", "newrepo")
            self.assertTrue(
                str(path).startswith(str((Path(td) / "repos").resolve())))


if __name__ == "__main__":
    unittest.main()
