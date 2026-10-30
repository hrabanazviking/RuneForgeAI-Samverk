"""TLS and secure defaults (S-015).

The default posture of a Samverk instance is HTTPS. Plaintext HTTP
is a loopback-only convenience for local development; serving it to
a network without TLS is refused — not warned about, refused —
unless the operator has *explicitly* armed the override, and the
arming itself is written to the audit log
(`admin.plaintext_http_override`, taxonomy S-008) before the
server starts. An override that is not audit-logged does not
exist: `enforce_bind_policy` raises rather than proceed without a
log when the override path is taken.

What counts as loopback is literal and small: `localhost`, and IP
literals in the loopback ranges (127.0.0.0/8, ::1) per
`ipaddress`. Wildcards (`0.0.0.0`, `::`, an empty host) bind every
interface and are therefore *not* loopback; a DNS name other than
`localhost` is not loopback either — the policy does no DNS
resolution, because a name that resolves to loopback today can be
rebound tomorrow.

TLS is configured by naming both a certificate and a key file.
Naming exactly one is a misconfiguration and is refused in every
posture — a half-configured TLS that silently falls back to
plaintext would be worse than none. When TLS is configured it
also settles the S-009 question: session cookies are Secure,
because the instance *is* served over HTTPS.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

from .config import Config

OVERRIDE_EVENT = "admin.plaintext_http_override"


class BindRefused(ValueError):
    """A bind posture refused by the S-015 law; `reason` is a
    stable machine-readable code."""

    def __init__(self, reason: str, detail: str = ""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


def is_loopback_host(host: str) -> bool:
    """True only for `localhost` and loopback IP literals."""
    h = (host or "").strip().lower()
    if h == "localhost":
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def tls_configured(cfg: Config) -> bool:
    return cfg.tls_cert_file is not None and cfg.tls_key_file is not None


def _check_tls_shape(cfg: Config) -> None:
    if (cfg.tls_cert_file is None) != (cfg.tls_key_file is None):
        raise BindRefused(
            "tls_half_configured",
            "tls_cert_file and tls_key_file must be set together")


def enforce_bind_policy(cfg: Config, audit=None) -> str:
    """Apply the bind law to *cfg*; return the posture taken:
    ``"loopback"``, ``"tls"``, or ``"override"``.

    Raises BindRefused for a half-configured TLS, and for
    non-loopback plaintext without the override. When the
    override is what makes the bind lawful, *audit* (an
    `AuditLog`) is required and the arming is recorded before
    this returns — no audit log, no override.
    """
    _check_tls_shape(cfg)
    if tls_configured(cfg):
        # Served over HTTPS: S-009's Secure flag is no longer the
        # operator's guess, it is a fact of the bind.
        cfg.secure_cookies = True
        return "tls"
    if is_loopback_host(cfg.host):
        return "loopback"
    if not cfg.allow_plaintext_http:
        raise BindRefused(
            "plaintext_outside_loopback",
            f"host {cfg.host!r} is not loopback and no TLS is "
            "configured; set tls_cert_file/tls_key_file, bind to "
            "loopback, or arm allow_plaintext_http (audit-logged)")
    if audit is None:
        raise BindRefused(
            "override_requires_audit",
            "allow_plaintext_http is armed but no audit log was "
            "provided; the override must be audit-logged (S-015)")
    audit.append(
        actor_kind="operator",
        action=OVERRIDE_EVENT,
        target_kind="instance",
        target_id=f"{cfg.host}:{cfg.port}",
        outcome="armed",
        detail={"host": cfg.host, "port": cfg.port},
    )
    return "override"


def enforce_with_audit(cfg: Config):
    """`enforce_bind_policy` with the instance's own audit log,
    opened only when the override path actually needs it (the
    loopback and TLS postures write nothing). Returns the posture.
    """
    _check_tls_shape(cfg)
    needs_override = (
        not tls_configured(cfg)
        and not is_loopback_host(cfg.host)
        and cfg.allow_plaintext_http
    )
    if not needs_override:
        return enforce_bind_policy(cfg)
    # Lazy imports: the audit/db stack is only needed on this path.
    from .audit import AuditLog
    from .db import init_db

    conn = init_db(cfg.db_path)
    try:
        return enforce_bind_policy(cfg, audit=AuditLog(conn))
    finally:
        conn.close()
