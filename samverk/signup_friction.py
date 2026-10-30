"""Signup abuse friction (S-021).

Registration is the one door an unauthenticated stranger may
knock on, so it carries friction by design — and the friction is
ours: **no third-party captcha**, ever. A captcha vendor would
see every prospective member's visit, decide who looks human by
rules nobody here can read, and become a dependency (S-017) with
a privacy price. Samverk's friction is instead:

1. **Throttles (the S-011 buckets, aimed).** A `SignupGuard`
   charges each attempt to two buckets at once — the source IP
   (default: 5 attempts, refilling at 5/hour) and the normalised
   email address (3 attempts, refilling at 3/hour) — charged to
   both or neither, per S-011's law. A flood from one address
   dies at the IP bucket however many emails it invents; a
   single address retried from a botnet's worth of IPs dies at
   the email bucket. Refusals carry a truthful `Retry-After`.
2. **Disposable-domain policy hooks.** The operator's policy
   decides which email domains may register at all. The hook is
   a plain callable over the parsed domain; the shipped policies
   are allow-all (the default — an instance that wants no domain
   law gets none) and a blocklist (the operator's own list; a
   listed domain's subdomains are listed too). No third-party
   disposable-domain list is bundled or fetched: whose mail is
   welcome is the operator's call, made from their own list.

The guard *decides*; it does not create accounts (S-025 owns
registration, and consumes this decision). Ordering inside a
decision is deliberate: a malformed address is refused as
malformed, a refused domain is refused without spending throttle
tokens (it could never succeed anyway), and only a plausible
attempt is charged to the buckets.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass

from .rate_limit import RateLimiter

# A domain policy answers one question about a parsed, lowercased
# domain: may an address at this domain register?
DomainPolicy = Callable[[str], bool]


def allow_all_domains(domain: str) -> bool:
    return True


class BlocklistDomains:
    """Refuse the listed domains and their subdomains."""

    def __init__(self, domains: frozenset[str] | set[str]):
        self._domains = frozenset(d.strip().lower() for d in domains if d.strip())

    def __call__(self, domain: str) -> bool:
        return not any(
            domain == listed or domain.endswith("." + listed)
            for listed in self._domains
        )


def domain_of_email(email: object) -> str | None:
    """The lowercased domain of a plausibly-shaped address, or
    None when the shape is not an address at all. (Full address
    validation is S-025's; the guard needs only the domain and a
    shape sane enough to bucket by.)"""
    if not isinstance(email, str):
        return None
    local, at, domain = email.strip().partition("@")
    if not at or not local or not domain or "@" in domain:
        return None
    domain = domain.rstrip(".").lower()
    labels = domain.split(".")
    if (not domain or len(labels) < 2 or not all(labels)
            or " " in domain):
        return None
    return domain


@dataclass(frozen=True)
class SignupDecision:
    allowed: bool
    reason: str  # ok | invalid_email | domain_refused | throttled
    retry_after_seconds: float = 0.0


class SignupGuard:
    """The S-021 decision-maker registration consults."""

    def __init__(
        self,
        domain_policy: DomainPolicy = allow_all_domains,
        *,
        ip_capacity: float = 5.0,
        ip_refill_per_hour: float = 5.0,
        email_capacity: float = 3.0,
        email_refill_per_hour: float = 3.0,
        time_fn: Callable[[], float] = time.monotonic,
    ):
        self._domain_policy = domain_policy
        self._limiter = RateLimiter(
            ip_capacity=ip_capacity,
            ip_refill_per_second=ip_refill_per_hour / 3600.0,
            account_capacity=email_capacity,
            account_refill_per_second=email_refill_per_hour / 3600.0,
            time_fn=time_fn,
        )

    def check(self, ip: str, email: str) -> SignupDecision:
        domain = domain_of_email(email)
        if domain is None:
            return SignupDecision(False, "invalid_email")
        if not self._domain_policy(domain):
            return SignupDecision(False, "domain_refused")
        decision = self._limiter.acquire(
            ip, account=email.strip().lower())
        if not decision.allowed:
            return SignupDecision(
                False, "throttled",
                retry_after_seconds=decision.retry_after_seconds)
        return SignupDecision(True, "ok")
