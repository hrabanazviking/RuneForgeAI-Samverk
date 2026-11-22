# Site settings (S-352)

The instance's own settings, changed only by instance admins and
witnessed by the standing `admin.settings.change` audit event.
They live in the database `settings` table (keys `site.*`) — no
migration (schema stays 139) and no new taxonomy event (138 stand).
S-346's configuration layer does not exist on the S-343 base, and
boot configuration (`samverk/config.py`) is boot-only by its own
law, so site settings are the sibling module
`samverk/site_settings.py`, following the standing settings-table
pattern of S-068 / S-038.

| Setting | Key | Default | Effect |
|---|---|---|---|
| Instance name | `site.instance_name` | `Samverk` | Shown on the site-settings page; plain text, at most 80 characters. |
| Instance description | `site.instance_description` | empty | Shown under the name; plain text, at most 500 characters. |
| Registration mode | `site.registration_mode` | `open` | `open` admits signups; `invite` admits only a valid single-use invite code (admin-minted, stored only as SHA-256 hashes, consumed by the signup it admits); `closed` refuses every signup. Enforced in `AccountStore.register` when the store is wired with the site-settings service. |
| Default repo visibility | `site.default_repo_visibility` | `private` | A repository created without naming a visibility — web/store door or the repositories API — is born with this visibility. An explicitly named visibility always wins. |
| Upload limit | `site.upload_max_bytes` | 10485760 (10 MiB) | `SiteSettingsService.enforce_upload` runs S-012's inspection under this cap; an oversize upload is refused in plain words naming its size and the limit. |
| Repo size limit | `site.repo_size_limit_bytes` | no limit | Written together with S-068's `repo_quota_default_bytes` key, so the receive-time quota enforcement (per-repo quota wins, instance default next) enforces exactly this number. Clearing it clears both keys. |

## Honest remainders

- Wiring is a seam, not a rewrite: stores constructed without a
  site-settings service keep their historic behaviour (open
  registration, private default visibility, S-012's default
  upload policy). The server bootstrap wiring the service into
  its stores is the integration step that turns the seam on for
  a running instance.
- Organization repositories (S-185 door) keep their own creation
  policy and explicit private default; the site default governs
  personal repositories and the repositories API.
- Upload enforcement exists at the S-012 inspection seam this
  slice owns; handlers that read bodies off the wire must consult
  `upload_policy()` for their read cap (S-012's own law).
