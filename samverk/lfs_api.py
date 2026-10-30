"""LFS batch API (S-061).

The Git LFS batch API is how real `git-lfs` clients move
objects: one POST describes every object a push or fetch
needs, and the server answers, per object, with *actions* —
short-lived signed URLs for upload, download, and verify.

- **Signed, expiring action URLs.** An action URL carries an
  HMAC-SHA256-signed token naming exactly one repository, one
  oid, one operation, and an expiry (one hour). The token is
  verified through the S-005 constant-time seam. Whoever
  holds an upload URL can upload *that object to that repo*
  until it expires — nothing else: no listing, no other oid,
  no other repo. (The token is a capability, so hrefs are
  minted only inside a batch answer given to a caller the
  transport authenticated — Part IV's S-081/S-082 own that
  authentication; this module takes the resolved actor.)
- **Permissions come from S-054's one function.** Download
  needs read, upload needs write; a repo the actor cannot
  read answers as not-found, exactly as S-054 rules.
- **Presence is honest.** An upload object that is already
  stored (with the claimed size) gets no actions — it is
  already here. A download object that is missing gets a
  per-object 404 in the batch answer, per the LFS spec.
- **Verify is real.** The verify action re-hashes the stored
  object (S-060's `verify`): a client is told success only
  when the bytes on disk hash to the oid.

`make_lfs_handler` adapts this service to HTTP under
`/<owner>/<repo>/info/lfs/…` — the surface a stock git-lfs
client speaks. The main server's route table adopts these
routes with Part IV's transports; the handler stands on its
own so the interop battery drives the *real* client against
Samverk's own endpoint code, not a mock.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import sqlite3
import time
from collections.abc import Callable
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler
from pathlib import Path

from .accounts import AccountStore
from .lfs_store import LFSError, LFSStore, validate_oid
from .permissions import can_read, can_write
from .repositories import RepositoryStore
from .throttle import constant_time_equal

ACTION_TTL_SECONDS = 3600


class LFSApiError(ValueError):
    def __init__(self, reason: str, message: str, status: int = 400):
        super().__init__(message)
        self.reason = reason
        self.status = status


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class LFSApi:
    def __init__(self, conn: sqlite3.Connection, data_root: Path,
                 accounts: AccountStore, repositories: RepositoryStore,
                 signing_key: bytes,
                 time_fn: Callable[[], float] = time.time):
        self._conn = conn
        self._data_root = Path(data_root)
        self._accounts = accounts
        self._repos = repositories
        self._key = signing_key
        self._now = time_fn

    # -- signed action tokens ------------------------------------
    def mint_action(self, full_name: str, oid: str, op: str,
                    size: int | None = None) -> str:
        payload = {"repo": full_name, "oid": oid, "op": op,
                   "size": size, "exp": int(self._now()) + ACTION_TTL_SECONDS}
        raw = json.dumps(payload, separators=(",", ":"), sort_keys=True
                         ).encode("utf-8")
        sig = hmac.new(self._key, raw, hashlib.sha256).digest()
        return f"{_b64(raw)}.{_b64(sig)}"

    def verify_action(self, token: object, *, op: str) -> dict:
        if not isinstance(token, str) or token.count(".") != 1:
            raise LFSApiError("token_invalid", "Bad action token.", 403)
        raw_b64, sig_b64 = token.split(".")
        try:
            raw = _unb64(raw_b64)
            sig = _unb64(sig_b64)
        except Exception:
            raise LFSApiError("token_invalid", "Bad action token.", 403) from None
        expected = hmac.new(self._key, raw, hashlib.sha256).digest()
        if not constant_time_equal(expected, sig):
            raise LFSApiError("token_invalid", "Bad action token.", 403)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception:
            raise LFSApiError("token_invalid", "Bad action token.", 403) from None
        if payload.get("op") != op:
            raise LFSApiError("token_invalid", "Wrong action token.", 403)
        if int(payload.get("exp", 0)) < int(self._now()):
            raise LFSApiError("token_expired", "That action has expired.", 403)
        return payload

    # -- helpers ---------------------------------------------------
    def _authorised(self, actor_user_id, owner, repo, *, write: bool):
        current = self._repos.get_repository(owner, repo)
        if current is None:
            raise LFSApiError("no_such_repo", "No such repository.", 404)
        actor = (self._accounts.get_by_id(actor_user_id)
                 if actor_user_id is not None else None)
        allowed = (can_write(actor, current) if write
                   else can_read(actor, current))
        if not allowed:
            # S-054: a repo you cannot read is a repo that is not there.
            raise LFSApiError("no_such_repo", "No such repository.", 404)
        return current

    def _store(self, current) -> LFSStore:
        return LFSStore(self._repos.path_for(current.owner, current.name))

    @staticmethod
    def _action(href: str) -> dict:
        return {"href": href, "header": {},
                "expires_in": ACTION_TTL_SECONDS}

    # -- the batch operation ---------------------------------------
    def batch(self, actor_user_id, owner, repo, request: dict,
              *, base_url: str) -> dict:
        if not isinstance(request, dict):
            raise LFSApiError("bad_request", "Batch body must be an object.")
        operation = request.get("operation")
        if operation not in ("upload", "download"):
            raise LFSApiError("bad_request", "Unknown LFS operation.")
        objects = request.get("objects")
        if not isinstance(objects, list) or not objects:
            raise LFSApiError("bad_request", "No objects in batch request.")
        current = self._authorised(actor_user_id, owner, repo,
                                    write=(operation == "upload"))
        store = self._store(current)
        out = []
        for item in objects:
            if not isinstance(item, dict):
                raise LFSApiError("bad_request", "Bad object entry.")
            try:
                oid = validate_oid(item.get("oid"))
            except LFSError as exc:
                raise LFSApiError(exc.reason, str(exc)) from None
            size = item.get("size")
            if not isinstance(size, int) or size < 0:
                raise LFSApiError("bad_request", "Bad object size.")
            entry: dict = {"oid": oid, "size": size}
            if operation == "download":
                if store.has(oid) and store.size_of(oid) == size:
                    token = self.mint_action(current.full_name, oid,
                                             "download", size)
                    entry["actions"] = {"download": self._action(
                        f"{base_url}/lfs-actions/{token}")}
                else:
                    entry["error"] = {"code": 404,
                                      "message": "Object not found."}
            else:  # upload
                if store.has(oid) and store.size_of(oid) == size:
                    entry["authenticated"] = True   # already present
                else:
                    up = self.mint_action(current.full_name, oid,
                                          "upload", size)
                    ver = self.mint_action(current.full_name, oid,
                                           "verify", size)
                    entry["actions"] = {
                        "upload": self._action(f"{base_url}/lfs-actions/{up}"),
                        "verify": self._action(f"{base_url}/lfs-actions/{ver}"),
                    }
            out.append(entry)
        return {"transfer": "basic", "objects": out}

    # -- action endpoints -------------------------------------------
    def accept_upload(self, token: str, data: bytes) -> dict:
        payload = self.verify_action(token, op="upload")
        owner, _, name = payload["repo"].partition("/")
        current = self._repos.get_repository(owner, name)
        if current is None:
            raise LFSApiError("no_such_repo", "No such repository.", 404)
        store = self._store(current)
        try:
            obj = store.put(payload["oid"], data,
                            expected_size=payload.get("size"))
        except LFSError as exc:
            raise LFSApiError(exc.reason, str(exc), 422) from None
        return {"oid": obj.oid, "size": obj.size}

    def serve_download(self, token: str) -> bytes:
        payload = self.verify_action(token, op="download")
        owner, _, name = payload["repo"].partition("/")
        current = self._repos.get_repository(owner, name)
        if current is None:
            raise LFSApiError("no_such_repo", "No such repository.", 404)
        try:
            return self._store(current).read(payload["oid"])
        except LFSError as exc:
            raise LFSApiError(exc.reason, str(exc), 404) from None

    def accept_verify(self, token: str, body: dict) -> dict:
        payload = self.verify_action(token, op="verify")
        owner, _, name = payload["repo"].partition("/")
        current = self._repos.get_repository(owner, name)
        if current is None:
            raise LFSApiError("no_such_repo", "No such repository.", 404)
        store = self._store(current)
        oid = payload["oid"]
        if (not store.has(oid) or store.size_of(oid) != payload.get("size")
                or not store.verify(oid)):
            raise LFSApiError("verify_failed",
                              "The stored object does not verify.", 422)
        return {"oid": oid, "size": payload.get("size")}


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def make_lfs_handler(api: LFSApi,
                     actor_resolver: Callable[[object], int | None],
                     locks=None):
    """Build a request handler serving the LFS API surface.

    `actor_resolver(headers)` returns the authenticated account
    id (Part IV supplies the real Basic/token resolvers; tests
    supply their own). `locks`, when given, is an `LFSLocking`
    (S-062) whose routes join the same surface.
    """

    class LFSHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, format: str, *args) -> None:  # noqa: A003
            pass

        # -- plumbing --
        def _body(self) -> bytes:
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                length = 0
            return self.rfile.read(length) if length > 0 else b""

        def _json(self, status: int, payload: dict) -> None:
            raw = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/vnd.git-lfs+json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def _fail(self, exc: LFSApiError) -> None:
            payload = {"message": str(exc)}
            existing = getattr(exc, "existing", None)
            if existing is not None:   # S-062: a lock conflict names its lock
                payload["lock"] = existing
            self._json(exc.status, payload)

        def _base(self) -> str:
            host = self.headers.get("Host") or "localhost"
            return f"http://{host}"

        def _actor(self):
            return actor_resolver(self.headers)

        # -- routes --
        def do_POST(self) -> None:  # noqa: N802 (stdlib name)
            try:
                if self.path.endswith("/objects/batch"):
                    owner, repo = self.path.split("/")[1:3]
                    request = json.loads(self._body().decode("utf-8"))
                    answer = api.batch(self._actor(), owner, repo, request,
                                       base_url=self._base())
                    self._json(200, answer)
                elif self.path.startswith("/lfs-actions/"):
                    token = self.path[len("/lfs-actions/"):]
                    body = json.loads(self._body().decode("utf-8") or "{}")
                    self._json(200, api.accept_verify(token, body))
                elif locks is not None and "/info/lfs/locks" in self.path:
                    locks.handle_post(self, api)
                else:
                    self._json(404, {"message": "Not found."})
            except LFSApiError as exc:
                self._fail(exc)
            except Exception:
                self._json(500, {"message": "Internal error."})

        def do_PUT(self) -> None:  # noqa: N802
            try:
                if self.path.startswith("/lfs-actions/"):
                    token = self.path[len("/lfs-actions/"):]
                    self._json(200, api.accept_upload(token, self._body()))
                else:
                    self._json(404, {"message": "Not found."})
            except LFSApiError as exc:
                self._fail(exc)
            except Exception:
                self._json(500, {"message": "Internal error."})

        def do_GET(self) -> None:  # noqa: N802
            try:
                if self.path.startswith("/lfs-actions/"):
                    token = self.path[len("/lfs-actions/"):]
                    data = api.serve_download(token)
                    self.send_response(200)
                    self.send_header("Content-Type",
                                     "application/octet-stream")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                elif locks is not None and "/info/lfs/locks" in self.path:
                    locks.handle_get(self, api)
                else:
                    self._json(404, {"message": "Not found."})
            except LFSApiError as exc:
                self._fail(exc)
            except Exception:
                self._json(500, {"message": "Internal error."})

    return LFSHandler
