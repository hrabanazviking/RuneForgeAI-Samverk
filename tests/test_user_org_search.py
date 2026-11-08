"""S-211 acceptance battery: user and org search.

Acceptance (roadmap S-211): User and org search —
by name and username, with profile cards.

The planted secrets are deliberate bait, in the
S-209/S-210 shape: a suspended account whose bio
carries the unique word `zorblax`, a pending
account, a secret team inside a public
organization whose name and description carry
`zorblax`, and an active account whose *email*
domain carries `zorblaxmail` — so any leak
channel (status-blind listing, profile read
before the filter, team data on a card, email
matched or rendered) moves a string or a number
this battery watches. The centre is the
equivalence proof: a stranger's hits and counts
over a world WITH the hidden accounts equal,
exactly, the same search over a world where
they were never registered.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from samverk import db, taxonomy
from samverk.accounts import AccountStore
from samverk.db import schema_version
from samverk.organizations import OrganizationStore
from samverk.teams import TeamStore
from samverk.user_org_search import (
    PeopleSearch, PeopleSearchError, matched_org_fields,
    matched_user_fields, org_matches_query, parse_people_query,
    render_people_directory_page, render_people_search_page,
    render_profile_card, user_matches_query, user_visible_to)

PW = "correct horse battery"


def make_world(root: Path, with_hidden: bool) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    accounts = AccountStore(conn)
    orgs = OrganizationStore(conn, accounts)
    volmarr = accounts.register("volmarr", PW)
    sigrun = accounts.register("sigrun", PW)
    mallory = accounts.register("mallory", PW)
    admina = accounts.register("admina", PW)
    elin = accounts.register("elin", PW, "elin@zorblaxmail.example")
    conn.execute(
        "UPDATE users SET is_admin = 1 WHERE username_lower = 'admina'")
    conn.commit()
    admina = accounts.get_by_id(admina.id)

    def profile(user, display, bio):
        conn.execute(
            "INSERT INTO profiles (user_id, display_name, bio,"
            " updated_at) VALUES (?, ?, ?, 0)",
            (user.id, display, bio))
        conn.commit()

    profile(volmarr, "Volmarr Wyrd", "Forge keeper and hall skald")
    profile(sigrun, "Sigrun Halvorsen", "Weaver of the great hall")
    profile(mallory, "Mallory Quinn", "Wandering cartographer")
    profile(admina, "Admina Root", "Keeper of the instance gates")
    profile(elin, "Elin Mar", "Archivist of tide charts")

    guild = orgs.create_organization(
        volmarr.id, "ForgeGuild", display_name="The Forge Guild",
        bio="Smiths and builders of the hall",
        website="https://forge.example.com")
    loom = orgs.create_organization(
        sigrun.id, "LoomCircle", display_name="Loom Circle",
        bio="Weavers and spinners of wool")

    def member(org, user, role):
        conn.execute(
            "INSERT INTO organization_members (org_id, user_id,"
            " role, added_by, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 100, 100)",
            (org.id, user.id, role, user.id))
        conn.commit()

    member(guild, volmarr, "owner")
    member(guild, sigrun, "member")
    member(loom, sigrun, "owner")

    hidden = {}
    if with_hidden:
        pete = accounts.register("pendingpete", PW)
        profile(pete, "Pending Pete", "Waiting at the gate")
        conn.execute(
            "UPDATE users SET status = 'pending_approval'"
            " WHERE username_lower = 'pendingpete'")
        bart = accounts.register("badbart", PW)
        profile(bart, "Bad Bart", "zorblax henchman for hire")
        conn.execute(
            "UPDATE users SET status = 'suspended'"
            " WHERE username_lower = 'badbart'")
        conn.commit()
        hidden = {"pete": accounts.get_by_id(pete.id),
                  "bart": accounts.get_by_id(bart.id)}
    w = SimpleNamespace(
        conn=conn, accounts=accounts, orgs=orgs, volmarr=volmarr,
        sigrun=sigrun, mallory=mallory, admina=admina, elin=elin,
        guild=guild, loom=loom, hidden=hidden,
        search=PeopleSearch(conn, orgs))
    return w


def handles(hits):
    return [(h.kind, h.handle) for h in hits]


class PureLawTests(unittest.TestCase):
    def test_parse_terms_and_qualifiers(self):
        q = parse_people_query("hall type:user sort:created-desc")
        self.assertEqual(q.terms, ("hall",))
        self.assertEqual(q.kinds, ("user",))
        self.assertEqual(q.sort, "created-desc")
        self.assertFalse(q.is_empty)

    def test_parse_quoted_phrase_and_type_spellings(self):
        q = parse_people_query('"forge guild" type:organizations')
        self.assertEqual(q.terms, ("forge guild",))
        self.assertEqual(q.kinds, ("org",))
        q2 = parse_people_query("type:users")
        self.assertEqual(q2.kinds, ("user",))

    def test_parse_negation(self):
        q = parse_people_query("-type:org hall")
        self.assertEqual(q.not_kinds, ("org",))
        self.assertEqual(q.terms, ("hall",))

    def test_parse_empty_is_the_directory_query(self):
        self.assertTrue(parse_people_query("").is_empty)
        self.assertTrue(parse_people_query(None).is_empty)

    def test_parse_unknown_qualifier_refused_by_name(self):
        with self.assertRaises(PeopleSearchError) as ctx:
            parse_people_query("hello language:python")
        self.assertEqual(ctx.exception.reason, "query_invalid")
        self.assertIn("language", str(ctx.exception))

    def test_parse_bad_values_refused(self):
        for bad in ("type:robot", "sort:size", "type:", '"unterminated',
                    "-sort:name-asc", "sort:name-asc sort:name-desc"):
            with self.assertRaises(PeopleSearchError) as ctx:
                parse_people_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid", bad)

    def test_parse_overlong_and_control_refused(self):
        for bad in ("x" * 501, "a\x01b"):
            with self.assertRaises(PeopleSearchError) as ctx:
                parse_people_query(bad)
            self.assertEqual(ctx.exception.reason, "query_invalid")

    def test_matches_and_fields_pure(self):
        user = SimpleNamespace(
            username_lower="volmarr", display_name="Volmarr Wyrd",
            bio="Forge keeper", email="v@zorblaxmail.example")
        hit = parse_people_query("forge")
        self.assertTrue(user_matches_query(user, hit))
        self.assertEqual(matched_user_fields(user, hit), ("bio",))
        self.assertEqual(
            matched_user_fields(user, parse_people_query("volmarr")),
            ("handle", "name"))
        # The email is never a field: its words match nothing.
        self.assertFalse(user_matches_query(
            user, parse_people_query("zorblaxmail")))
        self.assertFalse(user_matches_query(
            user, parse_people_query("type:org")))
        org = SimpleNamespace(
            name_lower="forgeguild", display_name="The Forge Guild",
            bio="Smiths of the hall")
        self.assertTrue(org_matches_query(
            org, parse_people_query("smiths type:org")))
        self.assertEqual(
            matched_org_fields(org, parse_people_query("forge")),
            ("handle", "name"))
        self.assertFalse(org_matches_query(
            org, parse_people_query("-type:org")))

    def test_visibility_pure(self):
        admin = SimpleNamespace(id=9, is_admin=True)
        member = SimpleNamespace(id=3, is_admin=False)
        self.assertTrue(user_visible_to(None, 3, "active"))
        self.assertFalse(user_visible_to(None, 3, "suspended"))
        self.assertFalse(user_visible_to(member, 4, "suspended"))
        self.assertTrue(user_visible_to(member, 3, "pending_approval"))
        self.assertTrue(user_visible_to(admin, 4, "suspended"))


class PeopleSearchTests(unittest.TestCase):
    def setUp(self):
        self._tds = [tempfile.TemporaryDirectory(),
                     tempfile.TemporaryDirectory()]
        for td in self._tds:
            self.addCleanup(td.cleanup)
        self.a = make_world(Path(self._tds[0].name), with_hidden=True)
        self.b = make_world(Path(self._tds[1].name), with_hidden=False)
        self.addCleanup(self.a.conn.close)
        self.addCleanup(self.b.conn.close)

    def test_pins_schema_84_taxonomy_123(self):
        self.assertEqual(schema_version(self.a.conn), 84)
        self.assertEqual(db.MIGRATIONS[-1][0], 84)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 123)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 31)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 79)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)

    def test_search_by_username_case_insensitive(self):
        hits = self.a.search.search(self.a.mallory, "VOLMARR")
        self.assertEqual(handles(hits), [("user", "volmarr")])
        self.assertEqual(hits[0].matched_fields, ("handle", "name"))

    def test_search_by_display_name(self):
        hits = self.a.search.search(None, "halvorsen")
        self.assertEqual(handles(hits), [("user", "sigrun")])
        self.assertEqual(hits[0].matched_fields, ("name",))

    def test_search_by_org_name_and_display_name(self):
        hits = self.a.search.search(None, "forgeguild")
        self.assertEqual(handles(hits), [("org", "ForgeGuild")])
        hits = self.a.search.search(None, '"loom circle"')
        self.assertEqual(handles(hits), [("org", "LoomCircle")])

    def test_search_by_bio_across_kinds(self):
        hits = self.a.search.search(None, "weaver")
        self.assertEqual(
            handles(hits), [("org", "LoomCircle"), ("user", "sigrun")])

    def test_terms_compose_by_and(self):
        hits = self.a.search.search(None, "hall skald")
        self.assertEqual(handles(hits), [("user", "volmarr")])
        hits = self.a.search.search(None, "hall")
        self.assertEqual(
            handles(hits),
            [("org", "ForgeGuild"), ("user", "sigrun"),
             ("user", "volmarr")])

    def test_type_qualifiers_and_negation(self):
        hall_org = self.a.search.search(None, "hall type:org")
        self.assertEqual(handles(hall_org), [("org", "ForgeGuild")])
        hall_user = self.a.search.search(None, "hall -type:org")
        self.assertEqual(
            handles(hall_user),
            [("user", "sigrun"), ("user", "volmarr")])
        contra = self.a.search.search(None, "hall type:user type:org")
        self.assertEqual(contra, [])

    def test_kind_kwarg_ands_with_text(self):
        hits = self.a.search.search(None, "hall", kind="user")
        self.assertEqual(
            handles(hits), [("user", "sigrun"), ("user", "volmarr")])
        self.assertEqual(
            self.a.search.search(None, "hall type:org", kind="user"),
            [])
        with self.assertRaises(PeopleSearchError):
            self.a.search.search(None, "hall", kind="robot")

    def test_membership_is_display_not_a_search_field(self):
        hits = self.a.search.search(None, "forgeguild")
        self.assertEqual(handles(hits), [("org", "ForgeGuild")])
        card = self.a.search.search(None, "volmarr")[0]
        self.assertEqual(card.org_names, ("ForgeGuild",))
        self.assertEqual(card.member_count, None)

    def test_org_card_facts(self):
        card = self.a.search.search(None, "forgeguild")[0]
        self.assertEqual(card.member_count, 2)
        self.assertEqual(card.website, "https://forge.example.com")
        self.assertEqual(card.effective_name, "The Forge Guild")
        page = render_profile_card(card)
        self.assertIn("The Forge Guild", page)
        self.assertIn("2 members", page)
        self.assertIn("Organization", page)

    def test_sorts(self):
        asc = self.a.search.directory(None)
        desc = self.a.search.directory(None, sort="name-desc")
        self.assertEqual(
            [h.handle for h in desc],
            [h.handle for h in reversed(asc)])
        with self.assertRaises(PeopleSearchError):
            self.a.search.search(None, "x", sort="size")

    def test_bad_limit_refused(self):
        for bad in (0, 501, "10", True):
            with self.assertRaises(PeopleSearchError):
                self.a.search.search(None, "hall", limit=bad)

    def test_limit_caps_display_never_the_count(self):
        counted = self.a.search.directory_counted(None, limit=2)
        self.assertEqual(len(counted.hits), 2)
        self.assertEqual(counted.total, 7)

    def test_counted_faces_agree(self):
        counted = self.a.search.search_counted(None, "hall")
        self.assertEqual(counted.total, 3)
        self.assertEqual(self.a.search.count(None, "hall"), 3)
        self.assertEqual(len(counted.hits), 3)

    def test_directory_for_anonymous_lists_public_world(self):
        counted = self.a.search.directory_counted(None)
        self.assertEqual(counted.total, 7)
        self.assertEqual(
            handles(counted.hits),
            [("user", "admina"), ("user", "elin"),
             ("org", "ForgeGuild"), ("org", "LoomCircle"),
             ("user", "mallory"), ("user", "sigrun"),
             ("user", "volmarr")])

    def test_hidden_accounts_invisible_to_strangers_and_anon(self):
        for viewer in (None, self.a.mallory, self.a.sigrun):
            self.assertEqual(self.a.search.search(viewer, "pete"), [])
            self.assertEqual(self.a.search.search(viewer, "bart"), [])
            self.assertEqual(self.a.search.count(viewer, "zorblax"), 0)

    def test_hidden_accounts_visible_to_self_and_admin(self):
        pete = self.a.hidden["pete"]
        bart = self.a.hidden["bart"]
        self.assertEqual(
            handles(self.a.search.search(pete, "pendingpete")),
            [("user", "pendingpete")])
        self.assertEqual(
            handles(self.a.search.search(self.a.admina, "badbart")),
            [("user", "badbart")])
        self.assertEqual(
            handles(self.a.search.search(self.a.admina, "zorblax")),
            [("user", "badbart")])
        self.assertEqual(self.a.search.directory_counted(
            self.a.admina).total, 9)
        self.assertEqual(bart.status, "suspended")

    def test_equivalence_with_and_without_hidden_accounts(self):
        for query in ("", "a", "hall", "weaver", "zorblax", "pete",
                      "bart", "gate"):
            left = self.a.search.search_counted(self.a.mallory, query)
            right = self.b.search.search_counted(self.b.mallory, query)
            self.assertEqual(handles(left.hits), handles(right.hits),
                             query)
            self.assertEqual(left.total, right.total, query)

    def test_email_is_never_matched_nor_rendered(self):
        self.assertEqual(self.a.search.search(None, "zorblaxmail"), [])
        self.assertEqual(
            self.a.search.search(None, "elin@zorblaxmail.example"), [])
        page = render_people_directory_page(
            self.a.search.directory(None))
        self.assertNotIn("zorblaxmail", page)
        self.assertNotIn("elin@", page)

    def test_secret_team_never_leaks_through_org_card(self):
        before = self.a.search.search(None, "forgeguild")[0]
        before_page = render_people_directory_page(
            self.a.search.directory(self.a.mallory),
            total=self.a.search.directory_counted(
                self.a.mallory).total)
        teams = TeamStore(self.a.conn, self.a.accounts)
        teams.create_team(
            self.a.volmarr.id, self.a.guild.id, "zorblax-council",
            description="zorblax secret plans", privacy="secret")
        after = self.a.search.search(None, "forgeguild")[0]
        self.assertEqual(before, after)
        after_page = render_people_directory_page(
            self.a.search.directory(self.a.mallory),
            total=self.a.search.directory_counted(
                self.a.mallory).total)
        self.assertEqual(before_page, after_page)
        self.assertEqual(self.a.search.search(None, "zorblax"), [])
        self.assertNotIn("zorblax", after_page)

    def test_rendered_pages_carry_no_hidden_people(self):
        page = render_people_search_page(
            "hall", self.a.search.search(self.a.mallory, "hall"),
            total=self.a.search.count(self.a.mallory, "hall"))
        self.assertIn("3 matches", page)
        self.assertIn("only people and organizations you may see",
                      page)
        directory = render_people_directory_page(
            self.a.search.directory(None),
            total=self.a.search.directory_counted(None).total)
        self.assertNotIn("pendingpete", directory)
        self.assertNotIn("badbart", directory)
        self.assertNotIn("zorblax", directory)

    def test_avatar_card_carries_alt_text(self):
        sha = "a" * 64
        self.a.conn.execute(
            "UPDATE profiles SET avatar_sha256 = ?,"
            " avatar_content_type = 'image/png', avatar_alt = ?"
            " WHERE user_id = ?",
            (sha, "A raven emblem", self.a.sigrun.id))
        self.a.conn.commit()
        card = self.a.search.search(None, "sigrun")[0]
        self.assertEqual(card.avatar_filename, sha + ".png")
        page = render_profile_card(card)
        self.assertIn('alt="A raven emblem"', page)
        self.assertIn(f'src="/avatars/{sha}.png"', page)

    def test_stored_markup_renders_as_text(self):
        self.a.conn.execute(
            "UPDATE profiles SET display_name = '<b>Mallory</b>'"
            " WHERE user_id = ?", (self.a.mallory.id,))
        self.a.conn.commit()
        page = render_people_search_page(
            "mallory", self.a.search.search(None, "mallory"))
        self.assertIn("&lt;b&gt;Mallory&lt;/b&gt;", page)
        self.assertNotIn("<b>Mallory</b>", page)

    def test_searches_write_nothing(self):
        def counts():
            out = {}
            for table in ("users", "profiles", "organizations",
                          "organization_members", "audit_log"):
                out[table] = self.a.conn.execute(
                    f"SELECT COUNT(*) AS n FROM {table}"
                ).fetchone()["n"]
            return out
        before = counts()
        self.a.search.search(self.a.mallory, "hall")
        self.a.search.directory_counted(None)
        self.a.search.search(self.a.admina, "zorblax")
        render_people_directory_page(self.a.search.directory(None))
        self.assertEqual(counts(), before)


if __name__ == "__main__":
    unittest.main()
