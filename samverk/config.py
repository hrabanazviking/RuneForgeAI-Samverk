"""Configuration loading (S-002).

Boot configuration only: the facts that must exist *before* the
database can open (study 42 §3). Everything else lives in the database
settings table in later slices.

Precedence, lowest to highest:
    built-in defaults  <  config file (INI)  <  environment  <  CLI flags
(CLI flags are applied by cli.py after load_config returns.)

Secrets never live here in usable form: the config names *where* the
secret file is; S-003 owns loading what is inside it.
"""

from __future__ import annotations

import configparser
import os
from dataclasses import dataclass, field
from pathlib import Path

from . import platform_seam

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8737


@dataclass
class Config:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    data_root: Path = field(default_factory=platform_seam.data_root_default)
    secret_file: Path | None = None
    log_level: str = "INFO"
    # S-009: the operator declares the instance is served over HTTPS;
    # session cookies then carry the Secure flag. S-015 owns the TLS
    # law that makes HTTPS the default posture.
    secure_cookies: bool = False

    @property
    def db_path(self) -> Path:
        return self.data_root / "samverk.db"


def _parse_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _from_file(cfg: Config, path: Path) -> None:
    parser = configparser.ConfigParser()
    with path.open("r", encoding="utf-8") as fh:
        parser.read_file(fh)
    if not parser.has_section("samverk"):
        return
    s = parser["samverk"]
    if "host" in s:
        cfg.host = s["host"].strip()
    if "port" in s:
        cfg.port = int(s["port"])
    if "data_root" in s:
        cfg.data_root = Path(s["data_root"]).expanduser()
    if "secret_file" in s:
        cfg.secret_file = Path(s["secret_file"]).expanduser()
    if "log_level" in s:
        cfg.log_level = s["log_level"].strip().upper()
    if "secure_cookies" in s:
        cfg.secure_cookies = _parse_bool(s["secure_cookies"])


def _from_env(cfg: Config, env: dict[str, str]) -> None:
    if env.get("SAMVERK_HOST"):
        cfg.host = env["SAMVERK_HOST"]
    if env.get("SAMVERK_PORT"):
        cfg.port = int(env["SAMVERK_PORT"])
    if env.get("SAMVERK_DATA_ROOT"):
        cfg.data_root = Path(env["SAMVERK_DATA_ROOT"]).expanduser()
    if env.get("SAMVERK_SECRET_FILE"):
        cfg.secret_file = Path(env["SAMVERK_SECRET_FILE"]).expanduser()
    if env.get("SAMVERK_LOG_LEVEL"):
        cfg.log_level = env["SAMVERK_LOG_LEVEL"].upper()
    if env.get("SAMVERK_SECURE_COOKIES"):
        cfg.secure_cookies = _parse_bool(env["SAMVERK_SECURE_COOKIES"])


def load_config(
    config_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> Config:
    """Load boot configuration from file + environment.

    The config file is located via, in order: the explicit
    *config_path*, $SAMVERK_CONFIG, ./samverk.ini, or
    <default data root>/samverk.ini. A missing file is not an error;
    defaults + environment still produce a working Config.
    """
    env = dict(os.environ) if env is None else env
    cfg = Config()
    path: Path | None = None
    if config_path is not None:
        path = Path(config_path)
    elif env.get("SAMVERK_CONFIG"):
        path = Path(env["SAMVERK_CONFIG"])
    elif Path("samverk.ini").is_file():
        path = Path("samverk.ini")
    else:
        candidate = platform_seam.data_root_default() / "samverk.ini"
        if candidate.is_file():
            path = candidate
    if path is not None and path.is_file():
        _from_file(cfg, path)
    _from_env(cfg, env)
    return cfg
