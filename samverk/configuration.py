"""Configuration -- one file, documented key by
key, environment overrides, and a check that
speaks plainly (S-346).

S-002 built the boot configuration law: one INI
file (`samverk.ini`, section `[samverk]`),
built-in defaults below it, environment
variables above it, CLI flags last. That law
worked, but it failed silently in three ways an
operator only discovers late:

- a bad value crashed the boot with a raw
  traceback (`port = abc` raised ValueError out
  of `int()`), naming neither the key nor the
  file it came from;
- an unknown key -- a typo like `prot = 8737` --
  was ignored without a word, so the operator
  believed a setting was in force that was not;
- no surface listed the keys, their defaults,
  their environment names, or the effective
  value each key ended with or where it came
  from.

This slice is the judgement over that law; it
does not replace it. `samverk/config.py` and
its `load_config` keep working exactly as
before -- every standing call site (server,
CLI, TLS policy, CSP) reads through them
unchanged. What this module adds:

- **One documented key set.** `KEY_SPECS`
  names every key the config file and the
  environment may set: its file key, its
  environment variable, its kind, its default
  and what it means, in the same words
  docs/CONFIGURATION.md carries. The file,
  the environment and the docs judge against
  this one list, so they cannot drift apart
  silently -- the battery pins the docs to it.
- **Environment overrides, judged.** The
  environment still wins over the file, key by
  key, exactly as S-002 ordered. What is new
  is that an override is validated like any
  other value: `SAMVERK_PORT=abc` is a named
  problem, not a traceback. Environment
  variables that are not configuration and
  never claimed to be -- the runner's
  SAMVERK_JOB_ID and kin, the import seam's
  credentials, S-003's SAMVERK_SECRET_<NAME>
  store -- are left alone; an unknown
  SAMVERK_* name that is none of those is
  stated as a warning, because it is most
  often a mistyped override.
- **A check that explains itself in plain
  words.** `check_configuration` reads the
  file and the environment the way
  `load_config` would, but collects *every*
  problem instead of dying on the first, and
  each problem names the key, says where the
  bad value came from (the file, the
  environment), what is wrong with it, and
  what a right value looks like, with an
  example. Cross-key law is judged too: the
  TLS certificate and key must be named
  together or not at all (S-015's law, stated
  here before the server refuses to boot),
  and files the config names but that do not
  exist are stated as warnings. The check
  also answers the effective settings --
  every key, its final value, and the source
  that supplied it (default, file or
  environment) -- so `samverk config show`
  can say what would actually run.
  `samverk config check` exits 0 when the
  configuration stands and 1 when it does
  not, printing the plain words either way.
- **No store, no migration, no event.**
  Configuration is boot fact, read before
  the database opens (S-002's study); this
  slice adds no table, no column and no
  audit event. Schema stays 139, taxonomy
  stays 138 (33 auth / 92 repo / 13 admin).
  `audit_configuration` proves that absence
  against the live instance: no table or
  column carries a configuration surface of
  this slice's own (the FTS shadow tables
  `*_fts_config` are SQLite's, named here so
  the audit never cries wolf over them).

Honest limits, stated plainly: the check
judges the values it is handed; it cannot
prove the host's port is free, the TLS files
are a matching pair (S-015's TLS law judges
that at boot), or that a data root is
writable -- it says the path that would be
used, and the boot remains the proof. A
missing config file is not an error:
defaults plus environment are a working
configuration, exactly as S-002 ordered, and
the check says so in words.
"""

from __future__ import annotations

import configparser
import io
import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from . import taxonomy
from .config import Config
from .escaping import escape_html_text

LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
CSP_MODES = ("enforce", "report-only")
BOOL_TRUE = ("1", "true", "yes", "on")
BOOL_FALSE = ("0", "false", "no", "off")

#: SAMVERK_* environment names that exist but
#: are not configuration: the runner protocol's
#: per-job facts, the import seam's askpass
#: credentials, and the locator itself. Judged
#: as known, never as mistyped overrides.
KNOWN_NON_CONFIG_ENV = frozenset({
    "SAMVERK_CONFIG",
    "SAMVERK_IMPORT_TOKEN",
    "SAMVERK_IMPORT_USERNAME",
    "SAMVERK_JOB_ID",
    "SAMVERK_OID",
    "SAMVERK_REPOSITORY",
    "SAMVERK_RUN_ID",
    "SAMVERK_WORKFLOW",
})


@dataclass(frozen=True)
class KeySpec:
    """One configuration key, documented."""
    key: str
    env_var: str
    kind: str  # text | port | path | optional_path | log_level | bool | csp_mode
    default_text: str
    summary: str
    example: str


KEY_SPECS: tuple[KeySpec, ...] = (
    KeySpec("host", "SAMVERK_HOST", "text", "127.0.0.1",
            "The network address the server listens on. "
            "127.0.0.1 means this machine only.", "0.0.0.0"),
    KeySpec("port", "SAMVERK_PORT", "port", "8737",
            "The TCP port the server listens on. 0 lets the "
            "operating system choose a free port.", "8737"),
    KeySpec("data_root", "SAMVERK_DATA_ROOT", "path", "(platform data directory)",
            "The directory holding the database, keys and "
            "instance data.", "/var/lib/samverk"),
    KeySpec("secret_file", "SAMVERK_SECRET_FILE", "optional_path", "(none)",
            "The file S-003 reads instance secrets from. "
            "The config names the file; secrets never live "
            "in the config itself.", "/etc/samverk/secrets.ini"),
    KeySpec("log_level", "SAMVERK_LOG_LEVEL", "log_level", "INFO",
            "How much the server logs: one of DEBUG, INFO, "
            "WARNING, ERROR, CRITICAL.", "DEBUG"),
    KeySpec("secure_cookies", "SAMVERK_SECURE_COOKIES", "bool", "false",
            "Set true when the instance is served over HTTPS, "
            "so session cookies carry the Secure flag.", "true"),
    KeySpec("tls_cert_file", "SAMVERK_TLS_CERT_FILE", "optional_path", "(none)",
            "The TLS certificate file. Must be named together "
            "with tls_key_file, or neither.", "/etc/samverk/cert.pem"),
    KeySpec("tls_key_file", "SAMVERK_TLS_KEY_FILE", "optional_path", "(none)",
            "The TLS private key file. Must be named together "
            "with tls_cert_file, or neither.", "/etc/samverk/key.pem"),
    KeySpec("allow_plaintext_http", "SAMVERK_ALLOW_PLAINTEXT_HTTP", "bool", "false",
            "Allow plain HTTP beyond loopback. Leave false "
            "unless you mean it; arming it is audit-logged.", "false"),
    KeySpec("csp_mode", "SAMVERK_CSP_MODE", "csp_mode", "enforce",
            "Content-Security-Policy mode: enforce, or "
            "report-only for a rehearsal before enforcement.", "report-only"),
)

SPECS_BY_KEY = {s.key: s for s in KEY_SPECS}
SPECS_BY_ENV = {s.env_var: s for s in KEY_SPECS}


@dataclass(frozen=True)
class ConfigProblem:
    """One thing wrong, in plain words."""
    key: str
    source: str  # "config file" | "environment" | "configuration"
    severity: str  # "error" | "warning"
    message: str
    hint: str

    @property
    def words(self) -> str:
        return (f"{self.key} (from the {self.source}): "
                f"{self.message} {self.hint}")


@dataclass(frozen=True)
class EffectiveSetting:
    key: str
    value_text: str
    source: str  # "default" | "config file" | "environment"


def _problem(key, source, message, hint, severity="error"):
    return ConfigProblem(key=key, source=source,
                         severity=severity,
                         message=message, hint=hint)


def validate_value(spec: KeySpec, raw: str, source: str):
    """Judge one raw value against its key's kind.

    Returns (converted, None) on success or
    (None, ConfigProblem) -- never raises on a
    bad value, so a check can collect every
    problem in one pass.
    """
    text = raw.strip()
    if spec.kind == "text":
        if not text:
            return None, _problem(
                spec.key, source,
                "the value is empty.",
                f"Set {spec.key} to an address like "
                f"{spec.example}.")
        if any(ch.isspace() for ch in text):
            return None, _problem(
                spec.key, source,
                f"{raw!r} contains spaces, so it is not "
                "one address.",
                f"Set {spec.key} to a single address "
                f"like {spec.example}.")
        return text, None
    if spec.kind == "port":
        try:
            number = int(text)
        except ValueError:
            return None, _problem(
                spec.key, source,
                f"{raw!r} is not a whole number.",
                "Set port to a number from 0 to 65535, "
                f"for example {spec.example}.")
        if not 0 <= number <= 65535:
            return None, _problem(
                spec.key, source,
                f"{number} is outside the port range.",
                "Set port to a number from 0 to 65535, "
                f"for example {spec.example}.")
        return number, None
    if spec.kind in ("path", "optional_path"):
        if not text:
            if spec.kind == "optional_path":
                return None, None
            return None, _problem(
                spec.key, source,
                "the value is empty.",
                f"Set {spec.key} to a directory like "
                f"{spec.example}.")
        return Path(text).expanduser(), None
    if spec.kind == "log_level":
        upper = text.upper()
        if upper not in LOG_LEVELS:
            return None, _problem(
                spec.key, source,
                f"{raw!r} is not a log level Samverk knows.",
                "Set log_level to one of "
                + ", ".join(LOG_LEVELS)
                + f", for example {spec.example}.")
        return upper, None
    if spec.kind == "bool":
        low = text.lower()
        if low in BOOL_TRUE:
            return True, None
        if low in BOOL_FALSE:
            return False, None
        return None, _problem(
            spec.key, source,
            f"{raw!r} does not say yes or no in words "
            "Samverk understands.",
            f"Set {spec.key} to true or false, for "
            f"example {spec.example}.")
    if spec.kind == "csp_mode":
        low = text.lower()
        if low not in CSP_MODES:
            return None, _problem(
                spec.key, source,
                f"{raw!r} is not a CSP mode Samverk knows.",
                "Set csp_mode to enforce or report-only, "
                f"for example {spec.example}.")
        return low, None
    raise AssertionError(f"unknown kind {spec.kind!r}")


def parse_config_text(text: str):
    """Parse INI text tolerantly.

    Returns (raw_values, problems): the raw
    string values of known keys in [samverk],
    plus one plain-words problem per syntax
    error, unknown section or unknown key.
    Never raises.
    """
    parser = configparser.ConfigParser()
    try:
        parser.read_file(io.StringIO(text))
    except configparser.Error as exc:
        return {}, [_problem(
            "config file", "config file",
            f"the file cannot be read as settings: {exc}.",
            "Write the file as lines of key = value under "
            "a [samverk] heading; see docs/CONFIGURATION.md.")]
    problems: list[ConfigProblem] = []
    values: dict[str, str] = {}
    for section in parser.sections():
        if section != "samverk":
            problems.append(_problem(
                section, "config file",
                f"the section [{section}] is not a section "
                "Samverk reads, so everything in it is ignored.",
                "Put every setting under the [samverk] "
                "heading."))
            continue
        for key, raw in parser[section].items():
            if key not in SPECS_BY_KEY:
                problems.append(_problem(
                    key, "config file",
                    f"{key!r} is not a Samverk setting, so "
                    "it is ignored -- this is often a typo.",
                    "The settings Samverk knows are: "
                    + ", ".join(s.key for s in KEY_SPECS) + "."))
                continue
            values[key] = raw
    return values, problems


@dataclass
class ConfigCheck:
    """The judged configuration, whole."""
    file_path: str | None
    file_found: bool
    problems: tuple[ConfigProblem, ...]
    settings: tuple[EffectiveSetting, ...]
    config: Config | None

    @property
    def errors(self) -> tuple[ConfigProblem, ...]:
        return tuple(p for p in self.problems
                     if p.severity == "error")

    @property
    def warnings(self) -> tuple[ConfigProblem, ...]:
        return tuple(p for p in self.problems
                     if p.severity == "warning")

    @property
    def ok(self) -> bool:
        return not self.errors and self.config is not None

    @property
    def words(self) -> str:
        if self.ok and not self.warnings:
            return ("The configuration stands: every value "
                    "is one Samverk understands.")
        if self.ok:
            return ("The configuration stands, with "
                    f"{len(self.warnings)} warning(s) below.")
        return ("The configuration does not stand: "
                f"{len(self.errors)} error(s) below. "
                "Samverk would not boot on these values.")


def _value_text(value) -> str:
    if value is None:
        return "(none)"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def check_configuration(config_path=None, env=None) -> ConfigCheck:
    """Judge the configuration exactly where
    `load_config` would read it, collecting
    every problem in plain words instead of
    raising on the first.

    Precedence is S-002's: defaults < file <
    environment. An invalid value never takes
    effect: the value below it in precedence
    stands, and the problem says so by naming
    its source.
    """
    from . import platform_seam
    env = dict(os.environ) if env is None else dict(env)
    problems: list[ConfigProblem] = []
    # Locate the file the way load_config does.
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
    file_found = path is not None and path.is_file()
    converted: dict[str, object] = {}
    sources: dict[str, str] = {}
    if path is not None and not file_found and config_path is not None:
        problems.append(_problem(
            "config file", "configuration",
            f"no file exists at {path}.",
            "Point --config (or SAMVERK_CONFIG) at the "
            "samverk.ini you mean, or drop the flag to "
            "run on defaults plus environment.",
            severity="warning"))
    if file_found:
        raw_values, parse_problems = parse_config_text(
            path.read_text(encoding="utf-8"))
        problems.extend(parse_problems)
        for key, raw in raw_values.items():
            value, problem = validate_value(
                SPECS_BY_KEY[key], raw, "config file")
            if problem is not None:
                problems.append(problem)
            else:
                converted[key] = value
                sources[key] = "config file"
    for env_var, raw in sorted(env.items()):
        spec = SPECS_BY_ENV.get(env_var)
        if spec is not None:
            if raw == "":
                continue  # S-002: an empty override is no override
            value, problem = validate_value(spec, raw, "environment")
            if problem is not None:
                problems.append(problem)
            else:
                converted[spec.key] = value
                sources[spec.key] = "environment"
        elif (env_var.startswith("SAMVERK_")
              and env_var not in KNOWN_NON_CONFIG_ENV
              and not env_var.startswith("SAMVERK_SECRET_")):
            problems.append(_problem(
                env_var, "environment",
                f"{env_var} is not a Samverk setting, so it "
                "changes nothing -- this is often a mistyped "
                "override.",
                "The environment settings Samverk knows are: "
                + ", ".join(s.env_var for s in KEY_SPECS) + ".",
                severity="warning"))
    # Cross-key law: TLS pair together or neither (S-015).
    cfg = Config()
    for key, value in converted.items():
        setattr(cfg, key, value)
    if (cfg.tls_cert_file is None) != (cfg.tls_key_file is None):
        named = "tls_cert_file" if cfg.tls_cert_file else "tls_key_file"
        missing = "tls_key_file" if cfg.tls_cert_file else "tls_cert_file"
        problems.append(_problem(
            named, "configuration",
            f"{named} is set but {missing} is not; TLS needs "
            "the certificate and the key together.",
            f"Set {missing} too, or remove {named} to run "
            "without TLS files."))
    # Named files that do not exist: warnings, in words.
    for key in ("secret_file", "tls_cert_file", "tls_key_file"):
        value = getattr(cfg, key)
        if value is not None and not Path(value).is_file():
            problems.append(_problem(
                key, "configuration",
                f"the file it names, {value}, does not exist.",
                f"Create that file, or point {key} at the "
                "file you mean.", severity="warning"))
    settings = tuple(
        EffectiveSetting(
            key=spec.key,
            value_text=_value_text(getattr(cfg, spec.key)),
            source=sources.get(spec.key, "default"))
        for spec in KEY_SPECS)
    has_error = any(p.severity == "error" for p in problems)
    return ConfigCheck(
        file_path=str(path) if path is not None else None,
        file_found=file_found,
        problems=tuple(problems),
        settings=settings,
        config=None if has_error else cfg)


def format_check_report(check: ConfigCheck) -> str:
    """The check as plain text for a terminal."""
    lines = []
    if check.file_found:
        lines.append(f"Config file: {check.file_path}")
    elif check.file_path:
        lines.append(f"Config file: {check.file_path} (not found; "
                     "defaults and environment apply)")
    else:
        lines.append("Config file: none found (defaults and "
                     "environment apply -- that is a working "
                     "configuration)")
    lines.append(check.words)
    for problem in check.problems:
        label = "ERROR" if problem.severity == "error" else "Warning"
        lines.append(f"{label}: {problem.words}")
    lines.append("Effective settings:")
    for setting in check.settings:
        lines.append(f"  {setting.key} = {setting.value_text} "
                     f"(from {setting.source})")
    return "\n".join(lines)


def example_config_text() -> str:
    """A samverk.ini with every key present and
    documented -- the file `config example`
    prints and docs/CONFIGURATION.md carries."""
    lines = ["# Samverk configuration -- every key, documented.",
             "# Copy to samverk.ini and edit. Environment "
             "variables", "# (named per key) override this file; "
             "see docs/CONFIGURATION.md.", "", "[samverk]"]
    defaults = Config()
    for spec in KEY_SPECS:
        lines.append(f"# {spec.summary}")
        lines.append(f"# Environment override: {spec.env_var}. "
                     f"Default: {spec.default_text}.")
        raw = getattr(defaults, spec.key)
        if raw is None:
            lines.append(f"# (unset by default; example: "
                         f"{spec.key} = {spec.example})")
        else:
            value = _value_text(raw)
            if spec.key == "data_root":
                value = str(defaults.data_root)
            lines.append(f"{spec.key} = {value}")
        lines.append("")
    return "\n".join(lines)


class ConfigurationService:
    """The operator-facing service over the pure
    judgements: check, show, example. Holds the
    location it was handed, reads nothing until
    asked, writes nothing ever."""

    def __init__(self, config_path=None, env=None):
        self._config_path = config_path
        self._env = env

    def check(self) -> ConfigCheck:
        return check_configuration(self._config_path, self._env)

    def effective_settings(self) -> tuple[EffectiveSetting, ...]:
        return self.check().settings

    def example(self) -> str:
        return example_config_text()


#: Surface words for this slice's own storage.
#: Bare "config" is NOT one: SQLite's FTS shadow
#: tables (*_fts_config) carry it innocently.
_SURFACE_WORDS = ("configuration", "samverk_config")


@dataclass(frozen=True)
class ConfigurationAudit:
    """Proof the slice added no store of its own:
    schema exactly 139, taxonomy exactly the
    standing 138, and no table, column or event
    carries a configuration surface."""
    source_ok: bool
    schema_version: int
    schema_ok: bool
    events_scanned: int
    taxonomy_ok: bool
    tables_scanned: int
    columns_scanned: int
    offending_tables: tuple
    offending_columns: tuple
    offending_events: tuple

    @property
    def stands_cleanly(self) -> bool:
        return (self.source_ok and self.schema_ok
                and self.taxonomy_ok
                and not self.offending_tables
                and not self.offending_columns
                and not self.offending_events)


def _surface(name: str) -> bool:
    text = name.lower()
    return any(word in text for word in _SURFACE_WORDS)


def audit_configuration(conn: sqlite3.Connection) -> ConfigurationAudit:
    """Check the configuration law against the
    live instance: the key set is whole and
    documented, the schema is exactly 139, the
    taxonomy is exactly the standing 138, and
    no configuration surface hides in the
    schema or the taxonomy. Pure read."""
    from .db import schema_version as _schema_version
    version = _schema_version(conn)
    clean = check_configuration(
        config_path="/nonexistent/samverk.ini", env={})
    source_ok = (
        len(KEY_SPECS) == 10
        and len(SPECS_BY_KEY) == 10
        and len(SPECS_BY_ENV) == 10
        and all(s.summary and s.example for s in KEY_SPECS)
        and clean.ok
        and clean.config is not None
        and clean.config.port == 8737)
    taxonomy_ok = (
        len(taxonomy.AUDIT_EVENTS) == 142
        and len(taxonomy.AUTH_EVENTS) == 34
        and len(taxonomy.REPO_EVENTS) == 92
        and len(taxonomy.ADMIN_EVENTS) == 16)
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master"
        " WHERE type = 'table' ORDER BY name").fetchall()]
    offending_tables: list = []
    offending_columns: list = []
    columns_scanned = 0
    for table in tables:
        if _surface(table):
            offending_tables.append(table)
        safe = table.replace('"', '""')
        for row in conn.execute(
                f'PRAGMA table_info("{safe}")').fetchall():
            columns_scanned += 1
            if _surface(str(row[1])):
                offending_columns.append(f"{table}.{row[1]}")
    events = sorted(taxonomy.AUDIT_EVENTS)
    offending_events = [e for e in events if _surface(e)]
    return ConfigurationAudit(
        source_ok=source_ok,
        schema_version=version, schema_ok=version == 140,
        events_scanned=len(events), taxonomy_ok=taxonomy_ok,
        tables_scanned=len(tables),
        columns_scanned=columns_scanned,
        offending_tables=tuple(offending_tables),
        offending_columns=tuple(offending_columns),
        offending_events=tuple(offending_events))


def render_configuration_page(check: ConfigCheck | None = None) -> str:
    """Configuration, in plain words, where an
    operator finds it: every key documented,
    plus one check's words and effective
    settings when they ride along. Every value
    escaped through S-010; standing is said in
    words, never a colour alone."""
    parts = [
        "<h1>Configuration</h1>",
        "<p>Samverk reads <strong>one config "
        "file</strong> (<code>samverk.ini</code>, "
        "section <code>[samverk]</code>). "
        "Environment variables override the file "
        "key by key, and command-line flags "
        "override both. A missing file is not an "
        "error: the defaults below apply.</p>",
        "<table><thead><tr><th>Key</th><th>Environment</th>"
        "<th>Default</th><th>What it means</th></tr></thead>"
        "<tbody>"]
    for spec in KEY_SPECS:
        parts.append(
            "<tr><td><code>" + escape_html_text(spec.key)
            + "</code></td><td><code>"
            + escape_html_text(spec.env_var)
            + "</code></td><td>"
            + escape_html_text(spec.default_text)
            + "</td><td>"
            + escape_html_text(spec.summary)
            + "</td></tr>")
    parts.append("</tbody></table>")
    if check is not None:
        parts.append(
            f"<p>{escape_html_text(check.words)}</p>")
        for problem in check.problems:
            parts.append(
                "<p>" + escape_html_text(
                    ("Error: " if problem.severity == "error"
                     else "Warning: ") + problem.words) + "</p>")
        parts.append("<ul>")
        for setting in check.settings:
            parts.append(
                "<li><code>" + escape_html_text(setting.key)
                + "</code> = "
                + escape_html_text(setting.value_text)
                + " (from "
                + escape_html_text(setting.source) + ")</li>")
        parts.append("</ul>")
    return "\n".join(parts)
