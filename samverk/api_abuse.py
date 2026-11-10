"""API abuse defences (S-255).

API abuse defences -- payload size caps,
expensive-endpoint accounting, per-token
concurrency limits. S-237's contract named this
slice in its rate-limits rule (payload size caps
and expensive-endpoint accounting are S-255's
abuse defences); S-241 landed the per-token rate
buckets this module stands beside, and this
module is the API door's remaining three brakes,
judged where S-238 judges every API call.

- **Payload size caps, judged before the body is
  read for meaning.** Every endpoint in the
  contract's route table is catalogued in
  ``ENDPOINTS`` with the size class of the body it
  may carry: ``none`` for the bodiless methods
  (a GET carries no body this door will read) and
  ``json`` for a JSON request body, capped at the
  instance's configured cap (1 MiB by default).
  No v1 endpoint carries a file body -- contents
  are read-only and the API writes files through
  Git, never around it (S-242's law in the
  contract) -- so one honest cap governs every
  body the API accepts. The pure ``decide_payload``
  judges a stated size against a cap before any
  parsing: a size inside the cap is allowed, a
  size past it is ``payload_too_large`` (S-240's
  problem at 413), and a size that is not a
  whole, non-negative byte count at all is
  ``payload_size_invalid`` -- a shapeless size is
  refused in words, never waved through as small.
  A refused body is read no further and charged
  nothing: not accounted, never admitted to a
  concurrency slot.
- **Expensive-endpoint accounting.** Endpoints
  are not equal in what a call costs the
  instance, so the catalogue prices each one in
  cost units: an ordinary endpoint costs 1, and
  the four expensive ones -- search (a fan-out
  over five executors), repository contents (blob
  bytes read and carried), repository forks (a
  clone), and pull-request merge (a Git merge) --
  cost 10, named in ``EXPENSIVE_ENDPOINTS`` so
  the price list is data a reader can audit, not
  a judgement hidden in code. Every admitted call
  is charged to its caller in the guard's ledger,
  keyed exactly as S-241 keys its buckets
  (`bucket_key_for`: a token's own ledger, an
  account's for a password-Basic call, the one
  anonymous ledger), and the ledger answers whole:
  per caller (calls, cost units, and the
  per-endpoint split) and per endpoint across all
  callers. Accounting is bookkeeping, not a
  brake: it refuses nothing by itself, and it
  keeps recording even when the brakes are
  configured off, so turning a brake off never
  blinds the operator watching for abuse. The
  counts are the proof -- a call the payload cap
  or the concurrency brake refused is not in
  them, and the battery reconciles the ledger
  against the calls it made, count for count.
- **Per-token concurrency limits.** A token
  bucket prices how *often* a caller may call;
  it does not price how *many* calls one token
  may hold open at once, and a caller that opens
  calls and holds them (slow bodies, stalled
  merges) can occupy the instance while spending
  almost no rate. ``ApiAbuseGuard.acquire`` admits
  a call under the caller's own ceiling -- 8 in
  flight per token by default, 2 for an expensive
  endpoint, whose work is the heavy kind -- and
  answers with a lease the caller releases when
  the call ends (a context manager, so an
  exception still releases). Past the ceiling the
  call is refused ``concurrency_limit_exceeded``
  (S-240's problem at 429) carrying its judgement;
  there is no `Retry-After`, because no honest
  second can be named -- a slot frees when a held
  call ends, not when a clock says so. A password
  call is limited by its account and the anonymous
  caller by the one shared anonymous ceiling,
  exactly as the buckets key. Releasing a lease
  twice, or a lease this guard never issued, is
  refused ``lease_invalid``: a slot is returned
  once, by its holder, or the counts would lie.
- **Instance-configurable defences.** The caps
  and ceilings live in the instance `settings`
  table (the S-038 road S-241 rides), under
  `api_abuse.*` keys: whether the defences are on,
  the JSON payload cap in bytes, and the two
  concurrency ceilings. `load_abuse_settings`
  reads them (defaults stand where a key is
  absent; a stored value that cannot be read as
  its number is refused `abuse_settings_invalid`
  rather than silently replaced -- a cap an
  operator mis-typed must be loud, not quietly
  different), and `save_abuse_settings` writes
  them for a site administrator, audited
  `admin.settings.change` with the keys named,
  the existing event S-038 already rides. With
  the defences off, every call is admitted and
  its decisions still state the configured caps
  and ceilings -- and the ledger still accounts.
- **Refusals are S-240's shape.** Every refusal
  is an `ApiAbuseError` with a machine-branchable
  reason, rendered by `error_to_dict` in the one
  problem format (type, title, status, detail,
  error id) through samverk/error_shape.py; this
  slice registers its reasons there
  (`payload_too_large` at 413,
  `concurrency_limit_exceeded` at 429, and its
  invalid/unknown names at their statuses).
- **What a judgement witnesses.** Judging,
  accounting and holding a slot write no row and
  audit nothing: the ledger and the slots are
  memory, thread-safe, as S-241's buckets are --
  they are measured in the life of one process,
  and losing them on restart loses nothing that
  matters. Only changing the defences themselves
  is witnessed, through the settings change
  above. No migration (schema stays 99), no
  taxonomy event (131 stand: 33 auth / 85 repo /
  13 admin). The contract's rate-limits rule now
  records these defences as landed, beside
  S-241's.
"""
from __future__ import annotations

import math
import sqlite3
import threading
from collections.abc import Mapping
from dataclasses import dataclass, field

from .api_auth import ApiIdentity
from .api_contract import API_RESOURCES, audit_api_contract, get_rule
from .api_rate_limit import bucket_key_for
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text

__all__ = [
    "ABUSE_PATH", "ALLOWED", "CONCURRENCY_LIMIT_EXCEEDED",
    "EXPENSIVE_COST", "EXPENSIVE_ENDPOINTS", "ORDINARY_COST",
    "PAYLOAD_SIZE_INVALID", "PAYLOAD_TOO_LARGE", "SETTING_KEYS",
    "TIER_EXPENSIVE", "TIER_ORDINARY", "AbuseAudit",
    "AbuseSettings", "ApiAbuseError", "ApiAbuseGuard",
    "CallerAccounting", "ConcurrencyDecision", "ConcurrencyLease",
    "EndpointSpec", "EndpointTotal", "ENDPOINTS", "PayloadDecision",
    "audit_api_abuse", "decide_concurrency", "decide_payload",
    "default_settings", "endpoint_cost", "error_to_dict",
    "get_endpoint", "load_abuse_settings", "parse_abuse_settings",
    "payload_cap_for", "render_api_abuse_page",
    "save_abuse_settings",
]

ABUSE_PATH = "/api/abuse-defences"

ALLOWED = "allowed"
PAYLOAD_TOO_LARGE = "payload_too_large"
PAYLOAD_SIZE_INVALID = "payload_size_invalid"
CONCURRENCY_LIMIT_EXCEEDED = "concurrency_limit_exceeded"

TIER_ORDINARY = "ordinary"
TIER_EXPENSIVE = "expensive"
ORDINARY_COST = 1
EXPENSIVE_COST = 10

KEY_ENABLED = "api_abuse.enabled"
KEY_PAYLOAD_CAP = "api_abuse.payload_cap_bytes"
KEY_MAX_CONCURRENT = "api_abuse.max_concurrent_per_token"
KEY_EXPENSIVE_MAX_CONCURRENT = (
    "api_abuse.expensive_max_concurrent_per_token")
SETTING_KEYS = (
    KEY_ENABLED, KEY_PAYLOAD_CAP, KEY_MAX_CONCURRENT,
    KEY_EXPENSIVE_MAX_CONCURRENT)

# The defaults an unconfigured instance stands
# with: a JSON body may carry 1 MiB (the bodies
# this API accepts are issues, reviews, settings
# and their kin -- text, not files), one token
# may hold 8 calls open at once, and only 2 of
# them may be expensive calls, whose work is the
# heavy kind.
DEFAULT_PAYLOAD_CAP_BYTES = 1024 * 1024
DEFAULT_MAX_CONCURRENT_PER_TOKEN = 8
DEFAULT_EXPENSIVE_MAX_CONCURRENT_PER_TOKEN = 2

_SETTINGS_INVALID = (
    "That abuse-defence setting could not be understood; "
    "no defence was changed.")


class ApiAbuseError(ValueError):
    """One refused abuse-defence call or setting:
    a machine-branchable reason with its human
    detail. A `concurrency_limit_exceeded` refusal
    carries its judgement as `.decision`, so the
    handler can answer with the caller's standing
    the decision computed."""

    def __init__(self, reason: str, message: str = "",
                 decision: "ConcurrencyDecision | None" = None):
        super().__init__(message or reason)
        self.reason = reason
        self.decision = decision


def error_to_dict(exc: ApiAbuseError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


# ------------------------------------------------------------------
# Settings -- instance-configurable, in the settings table
# ------------------------------------------------------------------

@dataclass(frozen=True)
class AbuseSettings:
    """The instance's abuse defences: whether they
    are on, the JSON payload cap in bytes, and the
    per-token concurrency ceilings (all calls, and
    the tighter ceiling for expensive calls).
    Every value must be a whole, positive size --
    a cap of zero would refuse every body and a
    ceiling of zero every call, which are refusals
    of everyone, not defences, and are refused
    here rather than smuggled in as arithmetic."""
    enabled: bool = True
    payload_cap_bytes: int = DEFAULT_PAYLOAD_CAP_BYTES
    max_concurrent_per_token: int = (
        DEFAULT_MAX_CONCURRENT_PER_TOKEN)
    expensive_max_concurrent_per_token: int = (
        DEFAULT_EXPENSIVE_MAX_CONCURRENT_PER_TOKEN)

    def validate(self) -> "AbuseSettings":
        for name in (
                "payload_cap_bytes", "max_concurrent_per_token",
                "expensive_max_concurrent_per_token"):
            value = getattr(self, name)
            if (isinstance(value, bool)
                    or not isinstance(value, int)
                    or value <= 0):
                raise ApiAbuseError(
                    "abuse_settings_invalid", _SETTINGS_INVALID)
        if (self.expensive_max_concurrent_per_token
                > self.max_concurrent_per_token):
            raise ApiAbuseError(
                "abuse_settings_invalid", _SETTINGS_INVALID)
        return self


def default_settings() -> AbuseSettings:
    """The defences an unconfigured instance
    stands with."""
    return AbuseSettings()


def _parse_whole(raw: object) -> int:
    if isinstance(raw, bool):
        raise ApiAbuseError(
            "abuse_settings_invalid", _SETTINGS_INVALID)
    if isinstance(raw, float):
        if not math.isfinite(raw) or raw != int(raw):
            raise ApiAbuseError(
                "abuse_settings_invalid", _SETTINGS_INVALID)
        return int(raw)
    try:
        return int(str(raw).strip(), 10)
    except (TypeError, ValueError):
        raise ApiAbuseError(
            "abuse_settings_invalid", _SETTINGS_INVALID) from None


def parse_abuse_settings(
        values: Mapping[str, object]) -> AbuseSettings:
    """Settings from a mapping of the `api_abuse.*`
    keys to stored values (strings from the
    settings table, or native values): absent keys
    keep their defaults, a present value that
    cannot be read as its whole number is refused
    `abuse_settings_invalid`. Pure."""
    enabled_raw = values.get(KEY_ENABLED)
    if enabled_raw is None:
        enabled = True
    elif isinstance(enabled_raw, bool):
        enabled = enabled_raw
    else:
        enabled = str(enabled_raw).strip().lower() in (
            "1", "true", "yes", "on")

    def whole(key: str, fallback: int) -> int:
        raw = values.get(key)
        return fallback if raw is None else _parse_whole(raw)

    return AbuseSettings(
        enabled=enabled,
        payload_cap_bytes=whole(
            KEY_PAYLOAD_CAP, DEFAULT_PAYLOAD_CAP_BYTES),
        max_concurrent_per_token=whole(
            KEY_MAX_CONCURRENT,
            DEFAULT_MAX_CONCURRENT_PER_TOKEN),
        expensive_max_concurrent_per_token=whole(
            KEY_EXPENSIVE_MAX_CONCURRENT,
            DEFAULT_EXPENSIVE_MAX_CONCURRENT_PER_TOKEN),
    ).validate()


def load_abuse_settings(
        conn: sqlite3.Connection) -> AbuseSettings:
    """The instance's defences, read from the
    settings table: defaults where no key has been
    set, a loud refusal where a stored value
    cannot be read."""
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE ?",
        ("api_abuse.%",)).fetchall()
    values = {row["key"]: row["value"] for row in rows}
    return parse_abuse_settings(values)


def save_abuse_settings(
        conn: sqlite3.Connection, settings: AbuseSettings,
        *, audit=None, actor_id: int | None = None,
        source_ip: str | None = None) -> AbuseSettings:
    """Write the instance's defences to the
    settings table, in one transaction, audited
    `admin.settings.change` with the keys named
    (the existing event S-038 rides -- changing a
    defence is the witnessed act; judging a call
    never is)."""
    settings.validate()
    rows = [
        (KEY_ENABLED, "1" if settings.enabled else "0"),
        (KEY_PAYLOAD_CAP, str(int(settings.payload_cap_bytes))),
        (KEY_MAX_CONCURRENT,
         str(int(settings.max_concurrent_per_token))),
        (KEY_EXPENSIVE_MAX_CONCURRENT,
         str(int(settings.expensive_max_concurrent_per_token))),
    ]
    with conn:
        conn.executemany(
            "INSERT INTO settings (key, value) VALUES (?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            rows)
    if audit is not None:
        audit.append(
            actor_kind="user" if actor_id else "operator",
            actor_id=actor_id,
            action="admin.settings.change",
            target_kind="instance", target_id="api_abuse",
            outcome="success", source_ip=source_ip,
            detail={"keys": [key for key, _ in rows]})
    return settings


# ------------------------------------------------------------------
# The endpoint catalogue -- size class and price, as data
# ------------------------------------------------------------------

@dataclass(frozen=True)
class EndpointSpec:
    """One catalogued endpoint of the contract's
    route table: its stable id (the contract
    resource's own id), its cost tier, the cost in
    units one admitted call is accounted, and the
    size class of the body it may carry -- `none`
    for a bodiless call, `json` for a JSON request
    body under the instance's cap."""
    id: str
    tier: str
    cost: int
    payload_class: str


def _spec(resource_id: str, tier: str,
          payload_class: str) -> EndpointSpec:
    return EndpointSpec(
        id=resource_id, tier=tier,
        cost=(EXPENSIVE_COST if tier == TIER_EXPENSIVE
              else ORDINARY_COST),
        payload_class=payload_class)


# Every resource of the contract's route table,
# in the contract's own order. The expensive four
# are named for the work a call sets off: search
# fans out over five executors, contents reads
# and carries blob bytes, forking clones a
# repository, and merging runs a Git merge.
ENDPOINTS: tuple[EndpointSpec, ...] = (
    _spec("root", TIER_ORDINARY, "none"),
    _spec("repositories", TIER_ORDINARY, "json"),
    _spec("repository", TIER_ORDINARY, "json"),
    _spec("repository-branches", TIER_ORDINARY, "none"),
    _spec("repository-contents", TIER_EXPENSIVE, "none"),
    _spec("repository-forks", TIER_EXPENSIVE, "json"),
    _spec("issues", TIER_ORDINARY, "json"),
    _spec("issue", TIER_ORDINARY, "json"),
    _spec("issue-comments", TIER_ORDINARY, "json"),
    _spec("pulls", TIER_ORDINARY, "json"),
    _spec("pull", TIER_ORDINARY, "json"),
    _spec("pull-merge", TIER_EXPENSIVE, "json"),
    _spec("pull-reviews", TIER_ORDINARY, "json"),
    _spec("user", TIER_ORDINARY, "none"),
    _spec("organizations", TIER_ORDINARY, "json"),
    _spec("organization", TIER_ORDINARY, "json"),
    _spec("organization-members", TIER_ORDINARY, "json"),
    _spec("organization-member", TIER_ORDINARY, "json"),
    _spec("organization-teams", TIER_ORDINARY, "json"),
    _spec("team", TIER_ORDINARY, "json"),
    _spec("team-members", TIER_ORDINARY, "json"),
    _spec("team-member", TIER_ORDINARY, "json"),
    _spec("team-repositories", TIER_ORDINARY, "json"),
    _spec("team-repository", TIER_ORDINARY, "json"),
    _spec("organization-default-permission",
          TIER_ORDINARY, "json"),
    _spec("repository-collaborators", TIER_ORDINARY, "json"),
    _spec("repository-collaborator", TIER_ORDINARY, "json"),
    _spec("search", TIER_EXPENSIVE, "none"),
    _spec("events", TIER_ORDINARY, "none"),
    _spec("user-events", TIER_ORDINARY, "none"),
    _spec("repository-events", TIER_ORDINARY, "none"),
    _spec("event", TIER_ORDINARY, "none"),
    _spec("statuses", TIER_ORDINARY, "json"),
    _spec("check-runs", TIER_ORDINARY, "json"),
    _spec("repository-hooks", TIER_ORDINARY, "json"),
    _spec("organization-hooks", TIER_ORDINARY, "json"),
)

EXPENSIVE_ENDPOINTS: tuple[str, ...] = tuple(
    spec.id for spec in ENDPOINTS if spec.tier == TIER_EXPENSIVE)


def get_endpoint(endpoint_id: object) -> EndpointSpec:
    """One catalogued endpoint by its id. An
    unknown id is refused endpoint_unknown -- the
    defences price only what the contract
    catalogues, and invent no price to answer
    with."""
    for spec in ENDPOINTS:
        if spec.id == endpoint_id:
            return spec
    raise ApiAbuseError(
        "endpoint_unknown", "No such API endpoint is "
        "catalogued.")


def endpoint_cost(endpoint_id: object) -> int:
    """The cost in units one admitted call to one
    endpoint is accounted. Pure."""
    return get_endpoint(endpoint_id).cost


def payload_cap_for(
        spec: EndpointSpec,
        settings: AbuseSettings) -> int | None:
    """The byte cap one endpoint's body is judged
    against under these settings: no cap for a
    bodiless endpoint (None -- there is no body
    this door will read), the instance's JSON cap
    for a body-carrying one. Pure."""
    if spec.payload_class == "none":
        return None
    return settings.payload_cap_bytes


# ------------------------------------------------------------------
# The pure judgements -- one size, one slot
# ------------------------------------------------------------------

def decide_payload(size_bytes: object,
                   cap_bytes: int | None) -> str:
    """Judge one stated body size against one cap:
    ALLOWED when the size is a whole, non-negative
    byte count inside the cap (or the endpoint
    carries no body, cap None, and the size is
    zero), PAYLOAD_TOO_LARGE when it stands past
    the cap, and PAYLOAD_SIZE_INVALID when the
    size is not a byte count at all -- shapeless,
    fractional, negative, or a body claimed for a
    bodiless endpoint. Pure: no storage, no clock
    lives here."""
    if (isinstance(size_bytes, bool)
            or not isinstance(size_bytes, int)
            or size_bytes < 0):
        return PAYLOAD_SIZE_INVALID
    if cap_bytes is None:
        return ALLOWED if size_bytes == 0 else PAYLOAD_SIZE_INVALID
    if (isinstance(cap_bytes, bool)
            or not isinstance(cap_bytes, int)
            or cap_bytes <= 0):
        return PAYLOAD_SIZE_INVALID
    return ALLOWED if size_bytes <= cap_bytes else PAYLOAD_TOO_LARGE


def decide_concurrency(in_flight: object, limit: object) -> str:
    """Judge one admission against one ceiling:
    ALLOWED when the calls already in flight stand
    below the limit, CONCURRENCY_LIMIT_EXCEEDED
    when they stand at it. A count or limit that
    is not a whole number fails closed as
    exceeded -- the guard's own counts are always
    whole, so an unreadable one is a defect, and a
    defect at the door refuses rather than admits.
    Pure."""
    if (isinstance(in_flight, bool)
            or not isinstance(in_flight, int)
            or isinstance(limit, bool)
            or not isinstance(limit, int)
            or in_flight < 0 or limit <= 0):
        return CONCURRENCY_LIMIT_EXCEEDED
    return (ALLOWED if in_flight < limit
            else CONCURRENCY_LIMIT_EXCEEDED)


# ------------------------------------------------------------------
# Decisions and ledger views
# ------------------------------------------------------------------

@dataclass(frozen=True)
class PayloadDecision:
    """One payload judgement, whole: the endpoint
    judged, the stated size, the cap it was judged
    against (None for a bodiless endpoint), the
    verdict word, and whether the defences stood
    on for it."""
    endpoint_id: str
    size_bytes: int
    cap_bytes: int | None
    verdict: str
    enabled: bool = True

    @property
    def allowed(self) -> bool:
        return self.verdict == ALLOWED


@dataclass(frozen=True)
class ConcurrencyDecision:
    """One concurrency judgement, whole: the
    caller it was judged for (its bucket key --
    this module's own bookkeeping, never a
    caller's name), the endpoint, the calls the
    caller already holds in flight and the calls
    of the endpoint's tier among them, and the
    ceiling that refused it (the tier ceiling for
    an expensive call, the caller's whole ceiling
    otherwise)."""
    bucket_key: str
    endpoint_id: str
    in_flight: int
    tier_in_flight: int
    limit: int
    allowed: bool


@dataclass(frozen=True)
class CallerAccounting:
    """One caller's ledger, whole: how many
    admitted calls it has been charged, the cost
    units they total, and the per-endpoint split
    as (endpoint_id, calls, cost_units) in
    endpoint order."""
    bucket_key: str
    calls: int
    cost_units: int
    by_endpoint: tuple[tuple[str, int, int], ...]


@dataclass(frozen=True)
class EndpointTotal:
    """One endpoint's ledger across all callers:
    admitted calls and the cost units they
    total."""
    endpoint_id: str
    calls: int
    cost_units: int


@dataclass
class _CallerLedger:
    calls: int = 0
    cost_units: int = 0
    by_endpoint: dict[str, list[int]] = field(
        default_factory=dict)


class ConcurrencyLease:
    """One admitted call's slot, held until
    released: a context manager, so the slot is
    returned when the call ends, however it ends.
    A lease is returned once, by its holder --
    releasing it twice, or through another guard,
    is refused `lease_invalid` rather than
    silently unbalancing the counts."""

    def __init__(self, guard: "ApiAbuseGuard", bucket_key: str,
                 spec: EndpointSpec):
        self._guard = guard
        self.bucket_key = bucket_key
        self.endpoint_id = spec.id
        self.tier = spec.tier
        self._released = False

    @property
    def released(self) -> bool:
        return self._released

    def release(self) -> None:
        self._guard._release(self)

    def __enter__(self) -> "ConcurrencyLease":
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if not self._released:
            self.release()
        return False


# ------------------------------------------------------------------
# The guard -- caps, accounting and slots at the API door
# ------------------------------------------------------------------

class ApiAbuseGuard:
    """The API door's abuse defences: payload caps
    judged before a body is read for meaning,
    every admitted call accounted to its caller
    at its endpoint's price, and per-token
    concurrency ceilings held in leases -- in
    memory, thread-safe, in S-241's shape. Build
    it from `AbuseSettings` directly, or from a
    connection with `from_conn`, which reads the
    instance's configured defences out of the
    settings table."""

    def __init__(self, settings: AbuseSettings | None = None):
        self._settings = (settings or default_settings()).validate()
        self._lock = threading.Lock()
        self._ledger: dict[str, _CallerLedger] = {}
        self._endpoint_totals: dict[str, list[int]] = {}
        self._in_flight: dict[str, int] = {}
        self._tier_in_flight: dict[tuple[str, str], int] = {}

    @classmethod
    def from_conn(cls, conn: sqlite3.Connection) -> "ApiAbuseGuard":
        return cls(load_abuse_settings(conn))

    @property
    def settings(self) -> AbuseSettings:
        return self._settings

    # -- payload caps ---------------------------------------------

    def judge_payload(self, endpoint_id: object,
                      size_bytes: object) -> PayloadDecision:
        """Judge one call's stated body size against
        its endpoint's cap, changing nothing: the
        decision a handler answers from before it
        reads the body for meaning. An unknown
        endpoint is refused endpoint_unknown."""
        spec = get_endpoint(endpoint_id)
        cap = payload_cap_for(spec, self._settings)
        if not self._settings.enabled:
            verdict = (ALLOWED if isinstance(size_bytes, int)
                       and not isinstance(size_bytes, bool)
                       and size_bytes >= 0
                       else PAYLOAD_SIZE_INVALID)
            return PayloadDecision(
                endpoint_id=spec.id,
                size_bytes=(size_bytes if verdict == ALLOWED else 0),
                cap_bytes=cap, verdict=verdict, enabled=False)
        verdict = decide_payload(size_bytes, cap)
        return PayloadDecision(
            endpoint_id=spec.id,
            size_bytes=(size_bytes if isinstance(size_bytes, int)
                        and not isinstance(size_bytes, bool)
                        else 0),
            cap_bytes=cap, verdict=verdict, enabled=True)

    def require_payload(self, endpoint_id: object,
                        size_bytes: object) -> PayloadDecision:
        """Judge one body as `judge_payload` does,
        raising the refusal the verdict names --
        `payload_too_large` in S-240's problem at
        413, `payload_size_invalid` at 400 -- when
        the body may not be carried."""
        decision = self.judge_payload(endpoint_id, size_bytes)
        if decision.allowed:
            return decision
        if decision.verdict == PAYLOAD_TOO_LARGE:
            raise ApiAbuseError(
                "payload_too_large",
                "That request body is "
                f"{decision.size_bytes} bytes; this endpoint "
                f"accepts at most {decision.cap_bytes} bytes.")
        raise ApiAbuseError(
            "payload_size_invalid",
            "That request's body size could not be understood; "
            "nothing was read.")

    # -- accounting -------------------------------------------------

    def account(self, identity: ApiIdentity,
                endpoint_id: object) -> CallerAccounting:
        """Charge one admitted call to its caller at
        its endpoint's price, and answer the
        caller's ledger whole. Accounting refuses
        nothing and is charged only for calls the
        other defences admitted -- the handler
        accounts after the payload and concurrency
        judgements pass (see `admit`)."""
        spec = get_endpoint(endpoint_id)
        key = bucket_key_for(identity)
        with self._lock:
            ledger = self._ledger.setdefault(key, _CallerLedger())
            ledger.calls += 1
            ledger.cost_units += spec.cost
            split = ledger.by_endpoint.setdefault(spec.id, [0, 0])
            split[0] += 1
            split[1] += spec.cost
            total = self._endpoint_totals.setdefault(
                spec.id, [0, 0])
            total[0] += 1
            total[1] += spec.cost
            return self._caller_view(key, ledger)

    def _caller_view(self, key: str,
                     ledger: _CallerLedger) -> CallerAccounting:
        return CallerAccounting(
            bucket_key=key, calls=ledger.calls,
            cost_units=ledger.cost_units,
            by_endpoint=tuple(
                (endpoint_id, counts[0], counts[1])
                for endpoint_id, counts
                in sorted(ledger.by_endpoint.items())))

    def accounting_for(self, identity: ApiIdentity) -> CallerAccounting:
        """One caller's ledger, read without charging
        anything: an unknown caller stands at zero."""
        key = bucket_key_for(identity)
        with self._lock:
            ledger = self._ledger.get(key)
            if ledger is None:
                return CallerAccounting(
                    bucket_key=key, calls=0, cost_units=0,
                    by_endpoint=())
            return self._caller_view(key, ledger)

    def endpoint_totals(self) -> tuple[EndpointTotal, ...]:
        """Every endpoint's ledger across all
        callers, in endpoint order: the expensive
        work of the instance, counted, where an
        operator reads it."""
        with self._lock:
            return tuple(
                EndpointTotal(
                    endpoint_id=endpoint_id, calls=counts[0],
                    cost_units=counts[1])
                for endpoint_id, counts
                in sorted(self._endpoint_totals.items()))

    # -- concurrency --------------------------------------------------

    def _ceiling_for(self, spec: EndpointSpec) -> tuple[int, str]:
        if spec.tier == TIER_EXPENSIVE:
            return (
                self._settings.expensive_max_concurrent_per_token,
                TIER_EXPENSIVE)
        return (self._settings.max_concurrent_per_token,
                TIER_ORDINARY)

    def in_flight(self, identity: ApiIdentity) -> int:
        """The calls one caller currently holds
        open, across all endpoints."""
        key = bucket_key_for(identity)
        with self._lock:
            return self._in_flight.get(key, 0)

    def acquire(self, identity: ApiIdentity,
                endpoint_id: object) -> ConcurrencyLease:
        """Admit one call under its caller's
        ceilings and answer the lease that holds
        its slot. Two ceilings judge together: the
        caller's whole in-flight count against the
        per-token ceiling, and -- for an expensive
        endpoint -- its expensive count against the
        tighter expensive ceiling. Past either, the
        call is refused `concurrency_limit_exceeded`
        carrying the judgement that refused it; a
        refused call holds no slot and is accounted
        nothing. With the defences off, every call
        is admitted and its slot still tracked, so
        a release stays honest."""
        spec = get_endpoint(endpoint_id)
        key = bucket_key_for(identity)
        ceiling, _tier = self._ceiling_for(spec)
        with self._lock:
            held = self._in_flight.get(key, 0)
            tier_held = self._tier_in_flight.get(
                (key, TIER_EXPENSIVE), 0)
            if self._settings.enabled:
                if decide_concurrency(held, self._settings
                                      .max_concurrent_per_token) \
                        != ALLOWED:
                    raise ApiAbuseError(
                        "concurrency_limit_exceeded",
                        "This caller already holds "
                        f"{held} calls in flight; the limit is "
                        f"{self._settings.max_concurrent_per_token} "
                        "at once.",
                        decision=ConcurrencyDecision(
                            bucket_key=key, endpoint_id=spec.id,
                            in_flight=held,
                            tier_in_flight=tier_held,
                            limit=self._settings
                            .max_concurrent_per_token,
                            allowed=False))
                if spec.tier == TIER_EXPENSIVE and \
                        decide_concurrency(tier_held, ceiling) \
                        != ALLOWED:
                    raise ApiAbuseError(
                        "concurrency_limit_exceeded",
                        "This caller already holds "
                        f"{tier_held} expensive calls in flight; "
                        f"the limit is {ceiling} at once.",
                        decision=ConcurrencyDecision(
                            bucket_key=key, endpoint_id=spec.id,
                            in_flight=held,
                            tier_in_flight=tier_held,
                            limit=ceiling, allowed=False))
            lease = ConcurrencyLease(self, key, spec)
            self._in_flight[key] = held + 1
            if spec.tier == TIER_EXPENSIVE:
                self._tier_in_flight[(key, TIER_EXPENSIVE)] = (
                    tier_held + 1)
            return lease

    def _release(self, lease: ConcurrencyLease) -> None:
        with self._lock:
            if lease._guard is not self or lease._released:
                raise ApiAbuseError(
                    "lease_invalid",
                    "That concurrency lease is not this guard's "
                    "to release, or was already released.")
            lease._released = True
            held = self._in_flight.get(lease.bucket_key, 0)
            self._in_flight[lease.bucket_key] = max(0, held - 1)
            if lease.tier == TIER_EXPENSIVE:
                tier_key = (lease.bucket_key, TIER_EXPENSIVE)
                tier_held = self._tier_in_flight.get(tier_key, 0)
                self._tier_in_flight[tier_key] = max(
                    0, tier_held - 1)

    # -- the whole door, in order --------------------------------------

    def admit(self, identity: ApiIdentity, endpoint_id: object,
              size_bytes: object) -> ConcurrencyLease:
        """Judge one call at the door, in the
        defences' order, and answer the lease that
        holds its slot: the payload cap first (a
        body past its cap is read no further), the
        concurrency ceilings second (a refused call
        holds nothing), and accounting last, charged
        only for the call actually admitted -- so
        the ledger counts admitted calls, never
        attempts, and the battery reconciles it
        count for count."""
        self.require_payload(endpoint_id, size_bytes)
        lease = self.acquire(identity, endpoint_id)
        self.account(identity, endpoint_id)
        return lease


# ------------------------------------------------------------------
# The audit -- the defences checked against the live contract
# ------------------------------------------------------------------

@dataclass(frozen=True)
class AbuseAudit:
    """The defences checked against the live
    contract: the REST contract's own ratification,
    every catalogued endpoint standing in the
    route table, every route-table resource
    catalogued (no endpoint unpriced), every price
    the tier's own, and the contract's rate-limits
    rule recording S-255 as landed. The defences
    hold only when all of it stands."""
    rest_ratified: bool
    rule_ok: bool
    endpoints_checked: int
    resources_checked: int
    uncatalogued_resources: tuple[str, ...]
    unknown_endpoints: tuple[str, ...]
    mispriced_endpoints: tuple[str, ...]

    @property
    def defences_hold(self) -> bool:
        return (self.rest_ratified
                and self.rule_ok
                and not self.uncatalogued_resources
                and not self.unknown_endpoints
                and not self.mispriced_endpoints)


def audit_api_abuse() -> AbuseAudit:
    """Check the defences against the live
    contract: the REST contract audit must still
    ratify, the rate-limits rule must record these
    defences as S-255's landed work, every resource
    in the route table must be catalogued here (an
    unpriced endpoint would be an unbounded one),
    every catalogued endpoint must stand in the
    table, and every price must be its tier's.
    Pure read."""
    rest = audit_api_contract()
    rule = get_rule("rate-limits")
    rule_ok = "S-255" in rule.statement and \
        "api_abuse" in rule.statement
    resource_ids = tuple(r.id for r in API_RESOURCES)
    catalogued = tuple(spec.id for spec in ENDPOINTS)
    uncatalogued = tuple(
        rid for rid in resource_ids if rid not in catalogued)
    unknown = tuple(
        eid for eid in catalogued if eid not in resource_ids)
    mispriced = tuple(
        spec.id for spec in ENDPOINTS
        if spec.cost != (EXPENSIVE_COST
                         if spec.tier == TIER_EXPENSIVE
                         else ORDINARY_COST)
        or spec.tier not in (TIER_ORDINARY, TIER_EXPENSIVE)
        or spec.payload_class not in ("none", "json"))
    return AbuseAudit(
        rest_ratified=rest.ratified,
        rule_ok=rule_ok,
        endpoints_checked=len(catalogued),
        resources_checked=len(resource_ids),
        uncatalogued_resources=uncatalogued,
        unknown_endpoints=unknown,
        mispriced_endpoints=mispriced)


def render_api_abuse_page(
        settings: AbuseSettings | None = None,
        audit: AbuseAudit | None = None) -> str:
    """The defences, in plain words, where a
    script's author finds them: the payload caps,
    the priced endpoints, the concurrency
    ceilings, and the instance's own configured
    numbers. Every value escaped through S-010."""
    settings = (settings or default_settings()).validate()
    state = "on" if settings.enabled else "off"
    parts = [
        "<h1>API abuse defences</h1>",
        "<p>Three defences stand at the API door, "
        "beside S-241's per-token rate buckets. A "
        "request body is judged against its "
        "endpoint's payload cap before it is read "
        "for meaning. Every admitted call is "
        "accounted to its caller at its endpoint's "
        "price in cost units, so expensive work is "
        "counted, not merely allowed. And one token "
        "may hold only so many calls in flight at "
        "once -- fewer when the calls are expensive "
        "-- so a caller cannot occupy the instance "
        "by opening calls and holding them.</p>",
        "<h2>Payload caps</h2>",
        "<p>An endpoint whose methods carry no body "
        "accepts no body. A JSON request body is "
        "capped at "
        f"{settings.payload_cap_bytes} bytes on "
        "this instance. A body past its cap is "
        "refused payload_too_large in S-240's one "
        "problem format (status 413), is read no "
        "further, and is charged nothing.</p>",
        "<h2>Expensive endpoints, priced</h2>",
        "<ul>",
    ]
    for endpoint_id in EXPENSIVE_ENDPOINTS:
        parts.append(
            f"<li><strong>{escape_html_text(endpoint_id)}"
            f"</strong>: {EXPENSIVE_COST} cost units "
            "per admitted call.</li>")
    parts.append("</ul>")
    parts.append(
        "<p>Every other catalogued endpoint costs "
        f"{ORDINARY_COST} cost unit per admitted "
        "call. The ledger is bookkeeping: it "
        "refuses nothing by itself, and it keeps "
        "counting while the defences are off, so "
        "an operator can see expensive work as it "
        "happens.</p>")
    parts.append("<h2>Concurrency limits</h2>")
    parts.append(
        f"<p>On this instance the defences are "
        f"{state}: one token may hold "
        f"{settings.max_concurrent_per_token} calls "
        "in flight at once, and at most "
        f"{settings.expensive_max_concurrent_per_token} "
        "of them may be expensive calls (a password "
        "call is limited by its account, an "
        "anonymous call by the one shared anonymous "
        "ceiling). A call past its ceiling is "
        "refused concurrency_limit_exceeded (status "
        "429) and holds no slot; a slot frees when "
        "a held call ends, so the refusal carries "
        "no Retry-After -- no honest second could "
        "be named.</p>")
    if audit is not None:
        if audit.defences_hold:
            parts.append(
                "<p>Checked, not just claimed: the "
                "REST contract was compared with the "
                f"live code over "
                f"{audit.resources_checked} resources "
                "and still ratifies; every resource "
                "in its route table is catalogued and "
                "priced here, and the contract's "
                "rate-limits rule records these "
                "defences as landed in S-255.</p>")
        else:
            found = ", ".join(
                audit.uncatalogued_resources
                + audit.unknown_endpoints
                + audit.mispriced_endpoints
                + (("REST contract no longer ratifies",)
                   if not audit.rest_ratified else ())
                + (("the rate-limits rule does not record "
                    "S-255",) if not audit.rule_ok else ()))
            parts.append(
                "<p>Checked, and not clean: the "
                "defences no longer hold as stated -- "
                f"{escape_html_text(found)} -- and "
                "that is a defect against S-255, to "
                "be fixed where it lies.</p>")
    parts.append(
        "<p>The full statement of these defences "
        "lives in docs/API_ABUSE.md.</p>")
    return "\n".join(parts)
