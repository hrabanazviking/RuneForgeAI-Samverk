"""Secrets law (S-003).

Instance secrets load from exactly two places:

    1. environment variables  (SAMVERK_SECRET_<NAME>)
    2. a secrets file         (KEY=VALUE lines, owner-only permissions)

and from nowhere else. In particular they are **never stored in the
database** — neither plaintext nor "encoded" (study 42 §3; threat
model T-03: a stolen database must not be a working keyring). Settings
in the database may *reference* a secret by name ("secret:instance_key")
but the value itself only ever lives in memory and in its source.

The secrets file must be private (mode 600 or stricter on POSIX);
a loosely-permissioned file is refused, fail-closed, with the fix
named in the error. There is no override flag: an override nobody
audits is a hole (S-015's audit-logged override pattern may revisit
this for operators, later, deliberately).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from . import platform_seam
from .config import Config

ENV_PREFIX = "SAMVERK_SECRET_"
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SecretError(Exception):
    """A secrets-law violation or a missing required secret."""


class Secrets:
    """In-memory holder for instance secrets. Values never repr."""

    def __init__(self, values: dict[str, str] | None = None):
        self._values = dict(values or {})

    def get(self, name: str) -> str | None:
        return self._values.get(name)

    def require(self, name: str) -> str:
        value = self._values.get(name)
        if value is None:
            raise SecretError(
                f"required instance secret {name!r} is not set "
                f"(provide {ENV_PREFIX}{name} or an entry in the secrets file)"
            )
        return value

    def names(self) -> list[str]:
        return sorted(self._values)

    def __contains__(self, name: str) -> bool:
        return name in self._values

    def __repr__(self) -> str:  # redaction law (S-018) starts here
        return f"Secrets(names={self.names()!r})"


def _parse_secrets_file(path: Path) -> dict[str, str]:
    if not platform_seam.secret_file_is_private(path):
        raise SecretError(
            f"secrets file {path} is readable by group/other users; "
            f"refusing to load it. Fix: chmod 600 {path}"
        )
    values: dict[str, str] = {}
    for lineno, raw in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise SecretError(f"{path}:{lineno}: expected KEY=VALUE")
        name, _, value = line.partition("=")
        name = name.strip()
        if not _NAME_RE.match(name):
            raise SecretError(f"{path}:{lineno}: bad secret name {name!r}")
        values[name] = value.strip()
    return values


def load_secrets(
    cfg: Config, env: dict[str, str] | None = None
) -> Secrets:
    """Load instance secrets: secrets file first, environment wins.

    The file is cfg.secret_file when set, else <data_root>/secrets.env
    when that exists. A missing file is fine — environment alone is a
    complete source.
    """
    env = dict(os.environ) if env is None else env
    values: dict[str, str] = {}
    path = cfg.secret_file
    if path is None:
        candidate = cfg.data_root / "secrets.env"
        if candidate.is_file():
            path = candidate
    if path is not None:
        if not path.is_file():
            raise SecretError(f"secrets file {path} does not exist")
        values.update(_parse_secrets_file(path))
    for key, value in env.items():
        if key.startswith(ENV_PREFIX):
            name = key[len(ENV_PREFIX):]
            if _NAME_RE.match(name):
                values[name] = value
    return Secrets(values)
