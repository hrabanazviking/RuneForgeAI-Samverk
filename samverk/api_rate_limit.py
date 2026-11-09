"""API rate limiting (S-241).

Rate limiting on the API -- per-token buckets,
limit headers on every response, honest
`Retry-After`; limits are instance-configurable.
S-237's contract recorded this law and named
this slice to land it; S-011 already brakes the
web's doors per IP and per account, and this
module is the API door's own brake, judged where
S-238 judges every API call.

- **Per-token buckets at the API door.** Every
  API call resolves through S-238's door to an
  `ApiIdentity`; this limiter keys its bucket by
  the credential that carried the call -- a
  token's own bucket (`token:<kind>:<id>`), so
  two tokens of one account are limited
  separately and one token's flood cannot spend
  another's allowance, exactly as the roadmap
  names it. A password-Basic call carries no
  token, so it is keyed by its account; the
  anonymous caller, carrying nothing, shares the
  one anonymous bucket, whose tighter limits are
  the instance's public posture toward scripts
  that will not name themselves. Buckets are
  token buckets in S-011's honest shape: a burst
  up to capacity at once, then refill at the
  configured rate. They live in memory and are
  thread-safe, as S-011's do -- limits are speed
  bumps measured in seconds, and losing them on
  restart loses nothing that matters.
- **Limit headers on every response.** Allowed
  or refused, every judgement answers with the
  same three headers -- `X-RateLimit-Limit` (the
  bucket's capacity), `X-RateLimit-Remaining`
  (whole tokens left after this call), and
  `X-RateLimit-Reset` (the epoch second at which
  the bucket stands full again) -- so a script
  can pace itself from any response, never only
  from a refusal. The headers carry numbers
  only: the configured limit, which is instance
  configuration, not a private fact, and counts
  of the caller's own allowance. No token id, no
  account name, and no other caller's standing
  ever rides in them.
- **An honest `Retry-After`.** A refused call
  raises `rate_limited` -- the refusal S-019 and
  S-240 already register at 429 -- rendered by
  `error_to_dict` in S-240's one problem format,
  and the error carries its judgement, so the
  handler answers with the limit headers plus a
  `Retry-After` computed from the bucket's own
  state: whole seconds, rounded up, until the
  refused request could have been served. The
  promise is never early: at the stated second
  the same call succeeds (the battery proves it
  against a fake clock). A refusal charges
  nothing -- the bucket is judged, never drained
  by a call it refused.
- **Instance-configurable limits.** The limits
  live in the instance `settings` table (the
  S-038 road), under `api_rate_limit.*` keys:
  whether limiting is on, the per-token capacity
  and refill rate, and the anonymous capacity
  and refill rate. `load_rate_limit_settings`
  reads them (defaults stand where a key is
  absent; a stored value that cannot be read as
  its number is refused `rate_settings_invalid`
  rather than silently replaced -- a limit an
  operator mis-typed must be loud, not quietly
  different), and `save_rate_limit_settings`
  writes them for a site administrator, audited
  `admin.settings.change` with the keys named,
  the existing event S-038 already rides. A
  limiter built from settings judges by them
  from the next call; there is no second,
  hidden limit anywhere in this module.
- **Refusals are S-240's shape.** Every refusal
  is an `ApiRateLimitError` with a
  machine-branchable reason, rendered by
  `error_to_dict` in the one problem format
  (type, title, status, detail, error id)
  through samverk/error_shape.py.
- **What a judgement witnesses.** Judging a
  call writes no row and audits nothing: the
  buckets are memory, and a caller hitting its
  own limit is not a witnessed mutation. Only
  changing the limits themselves is witnessed,
  through the settings change above. No
  migration (schema stays 94), no taxonomy
  event (129 stand: 33 auth / 83 repo / 13
  admin).
"""
from __future__ import annotations

import math
import sqlite3
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .api_auth import ApiIdentity
from .error_shape import problem_from_error, problem_to_dict
from .escaping import escape_html_text

__all__ = [
    "HEADER_LIMIT", "HEADER_REMAINING", "HEADER_RESET",
    "HEADER_RETRY_AFTER", "RATE_LIMIT_HEADERS", "RATE_LIMIT_PATH",
    "SETTING_KEYS", "ApiRateLimitError", "ApiRateLimiter",
    "RateLimitDecision", "RateLimitSettings",
    "bucket_key_for", "decide_bucket", "default_settings",
    "error_to_dict", "load_rate_limit_settings",
    "parse_rate_limit_settings", "render_api_rate_limit_page",
    "save_rate_limit_settings",
]

RATE_LIMIT_PATH = "/api/rate-limit"

HEADER_LIMIT = "X-RateLimit-Limit"
HEADER_REMAINING = "X-RateLimit-Remaining"
HEADER_RESET = "X-RateLimit-Reset"
HEADER_RETRY_AFTER = "Retry-After"
RATE_LIMIT_HEADERS = (HEADER_LIMIT, HEADER_REMAINING, HEADER_RESET)

KEY_ENABLED = "api_rate_limit.enabled"
KEY_TOKEN_CAPACITY = "api_rate_limit.token_capacity"
KEY_TOKEN_REFILL = "api_rate_limit.token_refill_per_second"
KEY_ANON_CAPACITY = "api_rate_limit.anonymous_capacity"
KEY_ANON_REFILL = "api_rate_limit.anonymous_refill_per_second"
SETTING_KEYS = (
    KEY_ENABLED, KEY_TOKEN_CAPACITY, KEY_TOKEN_REFILL,
    KEY_ANON_CAPACITY, KEY_ANON_REFILL)

# The defaults an unconfigured instance stands
# with: a token may burst 5000 calls and refills
# across the hour; the anonymous bucket is the
# tighter public posture, 300 across the hour.
DEFAULT_TOKEN_CAPACITY = 5000.0
DEFAULT_TOKEN_REFILL_PER_SECOND = 5000.0 / 3600.0
DEFAULT_ANONYMOUS_CAPACITY = 300.0
DEFAULT_ANONYMOUS_REFILL_PER_SECOND = 300.0 / 3600.0

_SETTINGS_INVALID = (
    "That rate-limit setting could not be understood; "
    "no limit was changed.")


class ApiRateLimitError(ValueError):
    """One refused rate-limit call or setting:
    a machine-branchable reason with its human
    detail. A `rate_limited` refusal carries its
    judgement as `.decision`, so the handler can
    answer with the limit headers and the honest
    `Retry-After` the decision computed."""

    def __init__(self, reason: str, message: str = "",
                 decision: "RateLimitDecision | None" = None):
        super().__init__(message or reason)
        self.reason = reason
        self.decision = decision


def error_to_dict(exc: ApiRateLimitError) -> dict:
    """One refusal as data, in S-240's one problem
    format (samverk/error_shape.py): type, title,
    status, detail, error_id -- nothing else."""
    return problem_to_dict(problem_from_error(exc))


# ------------------------------------------------------------------
# Settings -- instance-configurable, in the settings table
# ------------------------------------------------------------------

@dataclass(frozen=True)
class RateLimitSettings:
    """The instance's API limits: whether the
    brake is on, the per-token bucket's capacity
    and refill rate, and the anonymous bucket's.
    Rates are tokens per second; capacities are
    whole bursts. Every value must be positive
    where it is a size -- a limit of zero or a
    rate of zero would be a refusal of everyone,
    which is a different decision than a limit,
    and is refused here rather than smuggled in
    as arithmetic."""
    enabled: bool = True
    token_capacity: float = DEFAULT_TOKEN_CAPACITY
    token_refill_per_second: float = DEFAULT_TOKEN_REFILL_PER_SECOND
    anonymous_capacity: float = DEFAULT_ANONYMOUS_CAPACITY
    anonymous_refill_per_second: float = (
        DEFAULT_ANONYMOUS_REFILL_PER_SECOND)

    def validate(self) -> "RateLimitSettings":
        for name in (
                "token_capacity", "token_refill_per_second",
                "anonymous_capacity",
                "anonymous_refill_per_second"):
            value = getattr(self, name)
            if (isinstance(value, bool)
                    or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ApiRateLimitError(
                    "rate_settings_invalid", _SETTINGS_INVALID)
        return self


def default_settings() -> RateLimitSettings:
    """The limits an unconfigured instance
    stands with."""
    return RateLimitSettings()


def _parse_number(raw: object, key: str) -> float:
    if isinstance(raw, bool):
        raise ApiRateLimitError(
            "rate_settings_invalid", _SETTINGS_INVALID)
    try:
        value = float(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        raise ApiRateLimitError(
            "rate_settings_invalid", _SETTINGS_INVALID) from None
    if not math.isfinite(value):
        raise ApiRateLimitError(
            "rate_settings_invalid", _SETTINGS_INVALID)
    return value


def parse_rate_limit_settings(
        values: Mapping[str, object]) -> RateLimitSettings:
    """Settings from a mapping of the
    `api_rate_limit.*` keys to stored values
    (strings from the settings table, or native
    values): absent keys keep their defaults, a
    present value that cannot be read is refused
    `rate_settings_invalid`. Pure."""
    enabled_raw = values.get(KEY_ENABLED)
    if enabled_raw is None:
        enabled = True
    elif isinstance(enabled_raw, bool):
        enabled = enabled_raw
    else:
        enabled = str(enabled_raw).strip().lower() in (
            "1", "true", "yes", "on")

    def number(key: str, fallback: float) -> float:
        raw = values.get(key)
        return fallback if raw is None else _parse_number(raw, key)

    return RateLimitSettings(
        enabled=enabled,
        token_capacity=number(
            KEY_TOKEN_CAPACITY, DEFAULT_TOKEN_CAPACITY),
        token_refill_per_second=number(
            KEY_TOKEN_REFILL, DEFAULT_TOKEN_REFILL_PER_SECOND),
        anonymous_capacity=number(
            KEY_ANON_CAPACITY, DEFAULT_ANONYMOUS_CAPACITY),
        anonymous_refill_per_second=number(
            KEY_ANON_REFILL,
            DEFAULT_ANONYMOUS_REFILL_PER_SECOND)).validate()


def load_rate_limit_settings(
        conn: sqlite3.Connection) -> RateLimitSettings:
    """The instance's limits, read from the
    settings table: defaults where no key has
    been set, a loud refusal where a stored
    value cannot be read."""
    rows = conn.execute(
        "SELECT key, value FROM settings WHERE key LIKE ?",
        ("api_rate_limit.%",)).fetchall()
    values = {row["key"]: row["value"] for row in rows}
    return parse_rate_limit_settings(values)


def save_rate_limit_settings(
        conn: sqlite3.Connection, settings: RateLimitSettings,
        *, audit=None, actor_id: int | None = None,
        source_ip: str | None = None) -> RateLimitSettings:
    """Write the instance's limits to the
    settings table, in one transaction, audited
    `admin.settings.change` with the keys named
    (the existing event S-038 rides -- changing
    a setting is the witnessed act; judging a
    call never is)."""
    settings.validate()
    rows = [
        (KEY_ENABLED, "1" if settings.enabled else "0"),
        (KEY_TOKEN_CAPACITY, repr(float(settings.token_capacity))),
        (KEY_TOKEN_REFILL,
         repr(float(settings.token_refill_per_second))),
        (KEY_ANON_CAPACITY,
         repr(float(settings.anonymous_capacity))),
        (KEY_ANON_REFILL,
         repr(float(settings.anonymous_refill_per_second))),
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
            target_kind="instance", target_id="api_rate_limit",
            outcome="success", source_ip=source_ip,
            detail={"keys": [key for key, _ in rows]})
    return settings


# ------------------------------------------------------------------
# The pure judgement -- one bucket, one call
# ------------------------------------------------------------------

def decide_bucket(
        tokens: float, capacity: float,
        refill_per_second: float, now: float,
        updated_at: float, cost: float,
) -> tuple[bool, float, float]:
    """Judge one call against one bucket: refill
    the bucket from *updated_at* to *now*, then
    either charge *cost* or refuse it. Returns
    (allowed, tokens_after, retry_after_seconds)
    -- the tokens the bucket holds after the
    judgement (a refusal charges nothing, so its
    tokens_after is the refilled balance), and
    the honest seconds until *cost* tokens will
    stand in the bucket (0 when allowed). Pure:
    no clock, no storage, no lock lives here."""
    elapsed = max(0.0, now - updated_at)
    balance = min(capacity, tokens + elapsed * refill_per_second)
    if balance >= cost:
        return True, balance - cost, 0.0
    return False, balance, (cost - balance) / refill_per_second


def bucket_key_for(identity: ApiIdentity) -> str:
    """The bucket one resolved caller is judged
    against: a token's own bucket, an account's
    bucket for a password-Basic call, and the
    one shared anonymous bucket for a caller
    with no credential. The key is this module's
    own bookkeeping -- it never leaves in a
    header or a refusal. Pure."""
    if identity.kind in ("classic_token", "fine_token"):
        return f"token:{identity.kind}:{identity.token_id}"
    if identity.user is not None:
        return f"account:{identity.user.id}"
    return "anonymous"


@dataclass(frozen=True)
class RateLimitDecision:
    """One judgement, whole: whether the call
    may proceed, the bucket it was judged
    against, the limit and remaining counts its
    headers state, the epoch second the bucket
    stands full again, and -- on a refusal --
    the honest seconds until the call could be
    served."""
    allowed: bool
    bucket_key: str
    limit: int
    remaining: int
    reset_at: int
    retry_after_seconds: float | None = None

    @property
    def retry_after_header(self) -> str | None:
        """The `Retry-After` value of a refusal:
        whole seconds, rounded up so the promise
        is never early; None when allowed."""
        if self.allowed or self.retry_after_seconds is None:
            return None
        return str(max(1, math.ceil(self.retry_after_seconds)))

    def headers(self) -> dict[str, str]:
        """The headers this judgement answers
        with: the three limit headers on every
        response, plus the honest `Retry-After`
        on a refusal. Numbers only -- the limit
        is instance configuration, the rest are
        the caller's own counts."""
        result = {
            HEADER_LIMIT: str(self.limit),
            HEADER_REMAINING: str(self.remaining),
            HEADER_RESET: str(self.reset_at),
        }
        retry = self.retry_after_header
        if retry is not None:
            result[HEADER_RETRY_AFTER] = retry
        return result


@dataclass
class _BucketState:
    tokens: float
    updated_at: float


class ApiRateLimiter:
    """The API door's brake: per-token token
    buckets judged against S-238's resolved
    callers, in memory, thread-safe, in S-011's
    shape. Build it from `RateLimitSettings`
    directly, or from a connection with
    `from_conn`, which reads the instance's
    configured limits out of the settings
    table."""

    def __init__(
            self, settings: RateLimitSettings | None = None,
            time_fn: Callable[[], float] = time.time):
        self._settings = (settings or default_settings()).validate()
        self._now = time_fn
        self._lock = threading.Lock()
        self._buckets: dict[str, _BucketState] = {}

    @classmethod
    def from_conn(
            cls, conn: sqlite3.Connection,
            time_fn: Callable[[], float] = time.time,
    ) -> "ApiRateLimiter":
        return cls(load_rate_limit_settings(conn), time_fn=time_fn)

    @property
    def settings(self) -> RateLimitSettings:
        return self._settings

    def _shape_for(self, identity: ApiIdentity) -> tuple[float, float]:
        if identity.user is None:
            return (self._settings.anonymous_capacity,
                    self._settings.anonymous_refill_per_second)
        return (self._settings.token_capacity,
                self._settings.token_refill_per_second)

    def _judge(
            self, identity: ApiIdentity, cost: float,
            *, charge: bool) -> RateLimitDecision:
        key = bucket_key_for(identity)
        capacity, rate = self._shape_for(identity)
        if cost <= 0 or cost > capacity:
            raise ApiRateLimitError(
                "limit_invalid",
                "That call's cost is not inside the limit.")
        now = self._now()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(
                    tokens=capacity, updated_at=now)
                self._buckets[key] = state
            allowed, after, wait = decide_bucket(
                state.tokens, capacity, rate, now,
                state.updated_at, cost)
            balance = after if charge else min(
                capacity,
                state.tokens + max(0.0, now - state.updated_at) * rate)
            if charge:
                state.tokens = after
                state.updated_at = now
            remaining = int(balance)
            reset_at = int(math.ceil(
                now + max(0.0, (capacity - balance) / rate)))
            return RateLimitDecision(
                allowed=allowed, bucket_key=key,
                limit=int(capacity), remaining=remaining,
                reset_at=reset_at,
                retry_after_seconds=None if allowed else wait)

    def check(self, identity: ApiIdentity,
              cost: float = 1.0) -> RateLimitDecision:
        """Judge one call and charge it when it
        is allowed (a refusal charges nothing).
        With limiting off, every call is allowed
        and its headers still state the configured
        limits, untouched."""
        if not self._settings.enabled:
            key = bucket_key_for(identity)
            capacity, _rate = self._shape_for(identity)
            now = self._now()
            return RateLimitDecision(
                allowed=True, bucket_key=key,
                limit=int(capacity), remaining=int(capacity),
                reset_at=int(math.ceil(now)))
        return self._judge(identity, cost, charge=True)

    def peek(self, identity: ApiIdentity,
             cost: float = 1.0) -> RateLimitDecision:
        """The judgement of one call, without
        charging anything either way -- the
        headers a response carries when the call
        itself was judged elsewhere."""
        if not self._settings.enabled:
            return self.check(identity, cost)
        return self._judge(identity, cost, charge=False)

    def require(self, identity: ApiIdentity,
                cost: float = 1.0) -> RateLimitDecision:
        """Judge one call as `check` does, raising
        the `rate_limited` refusal -- S-240's
        problem at 429, carrying this decision --
        when the bucket refuses it."""
        decision = self.check(identity, cost)
        if decision.allowed:
            return decision
        seconds = decision.retry_after_header
        raise ApiRateLimitError(
            "rate_limited",
            "This caller has reached the API rate limit of "
            f"{decision.limit} requests; the next request can "
            f"be served in {seconds} seconds.",
            decision=decision)


def render_api_rate_limit_page(
        settings: RateLimitSettings | None = None) -> str:
    """The API's rate limits, in plain words,
    where a script's author finds them: per-token
    buckets, the headers every response carries,
    the honest Retry-After, and the instance's
    own configured numbers. Every value escaped
    through S-010."""
    settings = (settings or default_settings()).validate()
    state = "on" if settings.enabled else "off"
    parts = [
        "<h1>API rate limiting</h1>",
        "<p>Every API call is judged against a "
        "per-token bucket: a token may burst up to "
        "its limit at once, then its allowance "
        "refills steadily. A call made with an "
        "account password is judged against the "
        "account's bucket, and an anonymous call "
        "against the instance's smaller anonymous "
        "bucket. A refused call is charged "
        "nothing.</p>",
        "<p>Every API response, allowed or "
        "refused, carries the limit headers: "
        f"{escape_html_text(HEADER_LIMIT)} (the "
        "bucket's limit), "
        f"{escape_html_text(HEADER_REMAINING)} "
        "(requests remaining), and "
        f"{escape_html_text(HEADER_RESET)} (the "
        "epoch second the bucket stands full "
        "again). A refusal additionally carries "
        f"{escape_html_text(HEADER_RETRY_AFTER)}: "
        "the honest whole seconds until the "
        "refused request could have been served, "
        "and it answers in S-240's one problem "
        "format with the reason rate_limited.</p>",
        f"<p>This instance: limiting is {state}; "
        "the per-token limit is "
        f"{int(settings.token_capacity)} requests "
        "refilling at "
        f"{escape_html_text(format(settings.token_refill_per_second, 'g'))} "
        "per second; the anonymous limit is "
        f"{int(settings.anonymous_capacity)} "
        "requests refilling at "
        f"{escape_html_text(format(settings.anonymous_refill_per_second, 'g'))} "
        "per second. An instance's operator sets "
        "these numbers; no endpoint is unbounded "
        "by design.</p>",
    ]
    return "\n".join(parts)
