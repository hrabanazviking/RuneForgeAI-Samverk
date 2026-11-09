"""S-238 acceptance battery: API authentication.

Acceptance (roadmap S-238): API authentication --
tokens (S-032/S-033) and session-free Basic for
scripts; every API call resolves through S-190.

The centre is the two-part proof: credentials are
resolved only by their own stores (a revoked,
expired, or deactivated-owner token is the same
`credentials_invalid` as an unknown one, and a
session token is not an API credential at all),
and permission is resolved only by S-190 (its
`resolve` is counted under every authorisation,
its internal-visibility contribution -- which
S-054 does not have -- decides a case, and an
unreadable repository is indistinguishable from
a missing one in reason and rendered detail).

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import base64, json, sys, tempfile, unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk import db, taxonomy
from samverk.access_tokens import AccessTokenStore
from samverk.accounts import AccountStore, User
from samverk.api_auth import (
    AUTH_HELP_PATH, ApiAuthError, ApiAuthenticator, ApiIdentity,
    decide_token_scope, error_to_dict, identity_to_dict,
    parse_bearer_token, render_api_auth_page, scope_requirement)
from samverk.api_contract import CURRENT_ERROR_FIELDS
from samverk.audit import AuditLog
from samverk.db import schema_version
from samverk.fine_grained_tokens import FineTokenStore
from samverk.permission_engine import PermissionEngine
from samverk.repositories import RepositoryStore
from samverk.sessions import SessionStore

PW = "correct horse battery"


class Clock:
    def __init__(self, now=1_700_000_000):
        self.now = now
    def __call__(self):
        return self.now


def basic(username, credential):
    raw = base64.b64encode(
        f"{username}:{credential}".encode("utf-8"))
    return "Basic " + raw.decode("ascii")


def make_world(root: Path) -> SimpleNamespace:
    conn = db.init_db(root / "samverk.db")
    clock = Clock()
    audit = AuditLog(conn, time_fn=clock)
    accounts = AccountStore(conn, audit=audit, time_fn=clock)
    owner = accounts.register("volmarr", PW)
    reader = accounts.register("yrsa", PW)
    stranger = accounts.register("mallory", PW)
    repos = RepositoryStore(conn, root, accounts, audit=audit)
    repos.create_repository(owner.id, "volmarr", "pub", visibility="public")
    repos.create_repository(owner.id, "volmarr", "priv", visibility="private")
    repos.create_repository(owner.id, "volmarr", "int", visibility="internal")
    classic = AccessTokenStore(conn, accounts, audit=audit, time_fn=clock)
    fine = FineTokenStore(conn, accounts, audit=audit, time_fn=clock)
    expiry = clock.now + 3600
    _, owner_read = classic.create_token(
        owner.id, "read token", {"repo:read"}, expiry)
    _, owner_write = classic.create_token(
        owner.id, "write token", {"repo:write"}, expiry)
    _, stranger_read = classic.create_token(
        stranger.id, "stranger token", {"repo:read"}, expiry)
    _, fine_priv = fine.create_token(
        owner.id, "volmarr", "priv", "fine priv",
        {"contents:read", "issues:read"}, expiry)
    api = ApiAuthenticator(conn, accounts, repos, time_fn=clock)
    return SimpleNamespace(
        conn=conn, clock=clock, audit=audit, accounts=accounts,
        owner=owner, reader=reader, stranger=stranger, repos=repos,
        classic=classic, fine=fine, api=api, expiry=expiry,
        owner_read=owner_read, owner_write=owner_write,
        stranger_read=stranger_read, fine_priv=fine_priv)


class ApiAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.w = make_world(Path(self._td.name))
        self.addCleanup(self.w.conn.close)

    def _reason(self, fn, *args, **kwargs):
        with self.assertRaises(ApiAuthError) as ctx:
            fn(*args, **kwargs)
        return ctx.exception

    def _audit_count(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM audit_log").fetchone()["n"]

    def _session_count(self):
        return self.w.conn.execute(
            "SELECT COUNT(*) AS n FROM sessions").fetchone()["n"]

    # -- pins ------------------------------------------------
    def test_pins_schema_and_taxonomy(self):
        self.assertEqual(schema_version(self.w.conn), 94)
        self.assertEqual(db.MIGRATIONS[-1][0], 94)
        self.assertEqual(len(taxonomy.AUTH_EVENTS), 33)
        self.assertEqual(len(taxonomy.REPO_EVENTS), 83)
        self.assertEqual(len(taxonomy.ADMIN_EVENTS), 13)
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 129)
        self.assertEqual(AUTH_HELP_PATH, "/api/authentication")

    def test_error_dict_matches_s237_current_shape(self):
        exc = self._reason(self.w.api.authenticate, None)
        rendered = error_to_dict(exc)
        self.assertEqual(tuple(rendered.keys()), CURRENT_ERROR_FIELDS)
        self.assertEqual(rendered["error"], "authentication_required")
        self.assertTrue(rendered["detail"])
        self.assertEqual(json.loads(json.dumps(rendered)), rendered)

    # -- Bearer: tokens ---------------------------------------
    def test_bearer_classic_token_resolves_owner(self):
        identity = self.w.api.authenticate("Bearer " + self.w.owner_read)
        self.assertTrue(identity.authenticated)
        self.assertEqual(identity.user.id, self.w.owner.id)
        self.assertEqual(identity.kind, "classic_token")
        self.assertEqual(identity.scopes, frozenset({"repo:read"}))
        data = identity_to_dict(identity)
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(data["username"], "volmarr")
        self.assertEqual(data["scopes"], ["repo:read"])
        blob = json.dumps(data)
        self.assertNotIn(self.w.owner_read, blob)
        stored_hash = self.w.conn.execute(
            "SELECT token_hash FROM access_tokens WHERE id = ?",
            (identity.token_id,)).fetchone()["token_hash"]
        self.assertNotIn(stored_hash, blob)

    def test_bearer_fine_token_resolves_with_binding(self):
        identity = self.w.api.authenticate("Bearer " + self.w.fine_priv)
        self.assertEqual(identity.kind, "fine_token")
        self.assertEqual(identity.user.id, self.w.owner.id)
        self.assertIn("contents:read", identity.permissions)
        self.assertIn("metadata:read", identity.permissions)
        data = identity_to_dict(identity)
        self.assertEqual(data["bound_repository"], "volmarr/priv")
        self.assertNotIn(self.w.fine_priv, json.dumps(data))

    def test_missing_credential_is_authentication_required(self):
        for header in (None, "", "   "):
            exc = self._reason(self.w.api.authenticate, header)
            self.assertEqual(exc.reason, "authentication_required", header)

    def test_invalid_credentials_are_one_refusal(self):
        session = SessionStore(self.w.conn, time_fn=self.w.clock)
        session_token = session.create(self.w.owner.id)
        bad = [
            "Bearer", "Bearer ", "Bearer two tokens",
            "Bearer not-a-token", "Bearer svk_unknownunknown",
            "Bearer " + session_token,
            "Bearer " + self.w.owner_read + "extra",
            42, b"Bearer x",
        ]
        for header in bad:
            exc = self._reason(self.w.api.authenticate, header)
            self.assertEqual(exc.reason, "credentials_invalid", header)

    def test_revoked_and_expired_tokens_match_unknown(self):
        _, doomed = self.w.classic.create_token(
            self.w.owner.id, "doomed", {"repo:read"}, self.w.expiry)
        token_id = self.w.classic.list_tokens(self.w.owner.id)[-1].id
        self.assertTrue(self.w.classic.revoke_token(self.w.owner.id, token_id))
        revoked = self._reason(
            self.w.api.authenticate, "Bearer " + doomed)
        unknown = self._reason(
            self.w.api.authenticate, "Bearer svk_neverexisted")
        self.assertEqual(revoked.reason, "credentials_invalid")
        self.assertEqual(error_to_dict(revoked), error_to_dict(unknown))
        _, short = self.w.classic.create_token(
            self.w.owner.id, "short", {"repo:read"}, self.w.clock.now + 50)
        self.w.clock.now += 100
        expired = self._reason(self.w.api.authenticate, "Bearer " + short)
        self.assertEqual(expired.reason, "credentials_invalid")
        self.assertEqual(error_to_dict(expired), error_to_dict(unknown))

    def test_deactivated_owner_token_authenticates_to_nothing(self):
        ghost = self.w.accounts.register("ghost", PW)
        _, ghost_token = self.w.classic.create_token(
            ghost.id, "ghost token", {"repo:read"}, self.w.expiry)
        with self.w.conn:
            self.w.conn.execute(
                "UPDATE users SET status = 'suspended' WHERE id = ?",
                (ghost.id,))
        exc = self._reason(
            self.w.api.authenticate, "Bearer " + ghost_token)
        self.assertEqual(exc.reason, "credentials_invalid")

    def test_unknown_scheme_is_scheme_unsupported(self):
        exc = self._reason(self.w.api.authenticate, "Digest abc")
        self.assertEqual(exc.reason, "scheme_unsupported")

    # -- Basic: session-free for scripts -----------------------
    def test_basic_password_resolves_without_a_session(self):
        self.assertEqual(self._session_count(), 0)
        identity = self.w.api.authenticate(basic("volmarr", PW))
        self.assertEqual(identity.kind, "password")
        self.assertEqual(identity.user.id, self.w.owner.id)
        self.assertEqual(self._session_count(), 0)

    def test_basic_wrong_password_and_unknown_user_agree(self):
        wrong = self._reason(
            self.w.api.authenticate, basic("volmarr", "wrong password"))
        unknown = self._reason(
            self.w.api.authenticate, basic("nosuchuser", PW))
        self.assertEqual(wrong.reason, "credentials_invalid")
        self.assertEqual(error_to_dict(wrong), error_to_dict(unknown))
        malformed = self._reason(self.w.api.authenticate, "Basic !!!")
        self.assertEqual(malformed.reason, "credentials_invalid")

    def test_basic_token_in_password_slot(self):
        by_name = self.w.api.authenticate(
            basic("volmarr", self.w.owner_read))
        self.assertEqual(by_name.kind, "classic_token")
        by_alias = self.w.api.authenticate(
            basic("x-access-token", self.w.fine_priv))
        self.assertEqual(by_alias.kind, "fine_token")
        wrong_name = self._reason(
            self.w.api.authenticate, basic("yrsa", self.w.owner_read))
        self.assertEqual(wrong_name.reason, "credentials_invalid")

    def test_resolve_caller_optional_never_downgrades(self):
        anon = self.w.api.resolve_caller(None, required=False)
        self.assertFalse(anon.authenticated)
        self.assertEqual(anon.kind, "anonymous")
        exc = self._reason(
            self.w.api.resolve_caller, "Bearer svk_wrong", required=False)
        self.assertEqual(exc.reason, "credentials_invalid")
        exc = self._reason(self.w.api.resolve_caller, None)
        self.assertEqual(exc.reason, "authentication_required")

    # -- pure law ----------------------------------------------
    def test_parse_bearer_token_pure(self):
        self.assertEqual(parse_bearer_token("Bearer svk_x"), "svk_x")
        self.assertEqual(parse_bearer_token("bearer svk_x"), "svk_x")
        for header in (None, "", "Basic svk_x", "Bearer",
                       "Bearer ", "Bearer a b", 7):
            self.assertIsNone(parse_bearer_token(header), header)

    def test_scope_requirement_mapping(self):
        self.assertEqual(scope_requirement("repo", "read"),
                         ("repo:read", "contents:read"))
        self.assertEqual(scope_requirement("repo", "write"),
                         ("repo:write", "contents:write"))
        self.assertEqual(scope_requirement("issues", "triage"),
                         ("issues:write", "issues:write"))
        self.assertEqual(scope_requirement("pull_requests", "read"),
                         ("repo:read", "pull_requests:read"))
        self.assertEqual(scope_requirement("profile", "read"),
                         ("profile:read", None))
        exc = self._reason(scope_requirement, "nope", "read")
        self.assertEqual(exc.reason, "resource_unknown")

    def test_decide_token_scope_matrix(self):
        self.assertTrue(decide_token_scope(
            "password", frozenset(), "repo", "admin"))
        self.assertTrue(decide_token_scope(
            "classic_token", frozenset({"repo:write"}), "repo", "read"))
        self.assertFalse(decide_token_scope(
            "classic_token", frozenset({"repo:read"}), "repo", "write"))
        self.assertFalse(decide_token_scope(
            "classic_token", frozenset({"issues:write"}), "repo", "read"))
        self.assertTrue(decide_token_scope(
            "fine_token", frozenset({"contents:write", "metadata:read"}),
            "contents", "read"))
        self.assertFalse(decide_token_scope(
            "fine_token", frozenset({"contents:write", "metadata:read"}),
            "contents", "read", bound_matches=False))
        self.assertTrue(decide_token_scope(
            "fine_token", frozenset({"metadata:read"}), "repo", "read"))
        self.assertFalse(decide_token_scope(
            "fine_token", frozenset({"metadata:read"}), "repo", "write"))
        self.assertFalse(decide_token_scope(
            "fine_token", frozenset({"metadata:read"}), "profile", "read"))
        self.assertFalse(decide_token_scope(
            "anonymous", frozenset(), "repo", "read"))

    # -- authorisation through S-190 ----------------------------
    def test_authorize_anonymous_reads_public_only(self):
        granted = self.w.api.authorize(None, "volmarr", "pub")
        self.assertEqual(granted.role, "read")
        self.assertEqual(granted.resolution.source, "visibility")
        self.assertIsNone(granted.user)
        exc = self._reason(self.w.api.authorize, None, "volmarr", "priv")
        self.assertEqual(exc.reason, "repo_not_found")

    def test_unreadable_is_indistinguishable_from_missing(self):
        missing = self._reason(
            self.w.api.authorize, basic("yrsa", PW), "volmarr", "nosuch")
        unreadable = self._reason(
            self.w.api.authorize, basic("yrsa", PW), "volmarr", "priv")
        self.assertEqual(missing.reason, "repo_not_found")
        self.assertEqual(error_to_dict(missing), error_to_dict(unreadable))

    def test_authorize_owner_token_carries_s190_resolution(self):
        granted = self.w.api.authorize(
            "Bearer " + self.w.owner_read, "volmarr", "priv")
        self.assertEqual(granted.role, "admin")
        self.assertEqual(granted.resolution.source, "owner")
        self.assertEqual(granted.repository.full_name, "volmarr/priv")
        self.assertIn("own", granted.resolution.detail)

    def test_authorize_internal_visibility_is_s190s_alone(self):
        # S-054 has no internal contribution; only S-190's
        # engine can grant this read to a signed-in member.
        granted = self.w.api.authorize(basic("yrsa", PW), "volmarr", "int")
        self.assertEqual(granted.role, "read")
        self.assertEqual(granted.resolution.source, "internal")
        exc = self._reason(self.w.api.authorize, None, "volmarr", "int")
        self.assertEqual(exc.reason, "repo_not_found")

    def test_every_authorize_resolves_through_s190(self):
        original = PermissionEngine.resolve
        calls = []
        def counting(engine, viewer, repo, **kw):
            calls.append((viewer, repo.full_name))
            return original(engine, viewer, repo, **kw)
        with mock.patch.object(PermissionEngine, "resolve", counting):
            self.w.api.authorize(None, "volmarr", "pub")
            self.w.api.authorize(
                "Bearer " + self.w.owner_read, "volmarr", "priv")
            self._reason(self.w.api.authorize,
                         basic("mallory", PW), "volmarr", "priv")
        self.assertEqual(len(calls), 3)
        self.assertEqual(calls[1][1], "volmarr/priv")

    def test_token_never_widens_its_owner(self):
        exc = self._reason(
            self.w.api.authorize,
            "Bearer " + self.w.stranger_read, "volmarr", "priv")
        self.assertEqual(exc.reason, "repo_not_found")
        granted = self.w.api.authorize(
            "Bearer " + self.w.stranger_read, "volmarr", "pub")
        self.assertEqual(granted.role, "read")

    def test_classic_scope_is_a_ceiling_over_s190(self):
        exc = self._reason(
            self.w.api.authorize, "Bearer " + self.w.owner_read,
            "volmarr", "priv", minimum="write")
        self.assertEqual(exc.reason, "insufficient_scope")
        granted = self.w.api.authorize(
            "Bearer " + self.w.owner_write, "volmarr", "priv",
            minimum="write")
        self.assertEqual(granted.role, "admin")
        # Password Basic carries no token ceiling.
        granted = self.w.api.authorize(
            basic("volmarr", PW), "volmarr", "priv", minimum="admin")
        self.assertEqual(granted.role, "admin")

    def test_fine_token_binding_and_resource_scopes(self):
        granted = self.w.api.authorize(
            "Bearer " + self.w.fine_priv, "volmarr", "priv")
        self.assertEqual(granted.role, "admin")
        exc = self._reason(
            self.w.api.authorize, "Bearer " + self.w.fine_priv,
            "volmarr", "pub")
        self.assertEqual(exc.reason, "insufficient_scope")
        granted = self.w.api.authorize(
            "Bearer " + self.w.fine_priv, "volmarr", "priv",
            resource="issues")
        self.assertEqual(granted.role, "admin")
        exc = self._reason(
            self.w.api.authorize, "Bearer " + self.w.fine_priv,
            "volmarr", "priv", resource="contents", minimum="write")
        self.assertEqual(exc.reason, "insufficient_scope")

    def test_authorize_invalid_header_never_downgrades(self):
        exc = self._reason(
            self.w.api.authorize, "Bearer svk_wrong", "volmarr", "pub")
        self.assertEqual(exc.reason, "credentials_invalid")

    def test_authorize_rejects_unknown_resource_and_rung(self):
        exc = self._reason(
            self.w.api.authorize, None, "volmarr", "pub",
            resource="nope")
        self.assertEqual(exc.reason, "resource_unknown")
        exc = self._reason(
            self.w.api.authorize, None, "volmarr", "pub",
            minimum="superuser")
        self.assertEqual(exc.reason, "role_invalid")

    # -- witnesses and renders -----------------------------------
    def test_authentication_writes_and_audits_nothing(self):
        before = self._audit_count()
        self.w.api.authenticate("Bearer " + self.w.owner_write)
        self.w.api.authenticate(basic("yrsa", PW))
        self.w.api.authorize("Bearer " + self.w.owner_read,
                              "volmarr", "priv")
        self.assertEqual(self._audit_count(), before)
        self.assertEqual(self._session_count(), 0)

    def test_render_page_says_the_law_and_escapes(self):
        page = render_api_auth_page()
        for word in ("Bearer", "Basic", "S-190", "session",
                     "credentials_invalid", "repo_not_found"):
            self.assertIn(word, page)
        evil = User(id=99, username="<script>x</script>",
                    username_lower="evil", email=None,
                    email_verified=False, status="active",
                    is_admin=False, created_at=0)
        page = render_api_auth_page(ApiIdentity(user=evil, kind="password"))
        self.assertNotIn("<script>x</script>", page)
        self.assertIn("&lt;script&gt;", page)
        anon = render_api_auth_page(ApiIdentity(user=None, kind="anonymous"))
        self.assertIn("anonymous", anon)
