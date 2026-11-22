# Configuration (S-346)

Samverk reads **one config file**: `samverk.ini`, section
`[samverk]`. It is located via, in order: `--config PATH`,
`$SAMVERK_CONFIG`, `./samverk.ini`, or `samverk.ini` in the
default data root. A missing file is **not** an error —
built-in defaults plus environment are a working configuration.

Precedence, lowest to highest (S-002's law, unchanged):

    built-in defaults  <  config file  <  environment  <  CLI flags

Secrets never live in the config: it names *where* the secret
file is, and S-003 owns what is inside it.

## Every key, documented

| Key | Environment override | Default | What it means |
|---|---|---|---|
| `host` | `SAMVERK_HOST` | `127.0.0.1` | The network address the server listens on. 127.0.0.1 means this machine only. Example: `0.0.0.0`. |
| `port` | `SAMVERK_PORT` | `8737` | The TCP port the server listens on. 0 lets the operating system choose a free port. Example: `8737`. |
| `data_root` | `SAMVERK_DATA_ROOT` | platform data directory | The directory holding the database, keys and instance data. Example: `/var/lib/samverk`. |
| `secret_file` | `SAMVERK_SECRET_FILE` | (none) | The file S-003 reads instance secrets from. Example: `/etc/samverk/secrets.ini`. |
| `log_level` | `SAMVERK_LOG_LEVEL` | `INFO` | One of DEBUG, INFO, WARNING, ERROR, CRITICAL. Example: `DEBUG`. |
| `secure_cookies` | `SAMVERK_SECURE_COOKIES` | `false` | Set true when served over HTTPS, so session cookies carry the Secure flag. Booleans are written true/false (1/yes/on and 0/no/off also work). |
| `tls_cert_file` | `SAMVERK_TLS_CERT_FILE` | (none) | The TLS certificate file. Must be named together with `tls_key_file`, or neither. |
| `tls_key_file` | `SAMVERK_TLS_KEY_FILE` | (none) | The TLS private key file. Must be named together with `tls_cert_file`, or neither. |
| `allow_plaintext_http` | `SAMVERK_ALLOW_PLAINTEXT_HTTP` | `false` | Allow plain HTTP beyond loopback. Leave false unless you mean it; arming it is audit-logged. |
| `csp_mode` | `SAMVERK_CSP_MODE` | `enforce` | Content-Security-Policy mode: `enforce`, or `report-only` for a rehearsal before enforcement. |

`samverk config example` prints a `samverk.ini` with every key
above present and commented, ready to copy and edit.

## Checking a configuration

    samverk config check [--config PATH]
    samverk config show  [--config PATH]

`check` reads the file and the environment the way the server
would, but collects **every** problem instead of stopping at
the first, and explains each in plain words: it names the key,
says where the bad value came from (the config file or the
environment), what is wrong with it, and what a right value
looks like, with an example. It exits 0 when the configuration
stands and 1 when it does not. `show` prints the same report,
whose tail lists the **effective settings** — every key, its
final value, and the source that supplied it (default, config
file, or environment) — so you can see what would actually run.

What the check judges:

- every value against its key's kind (a port must be a whole
  number from 0 to 65535; a log level must be one of the five;
  a boolean must say yes or no in recognised words; a CSP mode
  must be enforce or report-only);
- unknown keys and unknown sections in the file — a typo like
  `prot = 8737` is an error naming the key, never silently
  ignored;
- unknown `SAMVERK_*` environment names — a warning, because
  they are most often mistyped overrides (the runner's,
  import seam's and secrets store's own `SAMVERK_*` names are
  known and left alone);
- the TLS pair law: certificate and key together, or neither;
- files the config names that do not exist — warnings, in words.

An invalid value never takes effect: the value below it in
precedence stands, and the problem names its source.

Honest limits: the check cannot prove the port is free, that
the TLS files are a matching pair (S-015's TLS law judges that
at boot), or that the data root is writable. The boot remains
the proof for those.

## Standing

S-346 added no database table, no migration (schema stays
139) and no audit event (taxonomy stays 138: 33 auth / 92 repo
/ 13 admin). Configuration is boot fact, read before the
database opens; `audit_configuration` in
`samverk/configuration.py` proves no configuration surface
hides in the schema or the taxonomy.
