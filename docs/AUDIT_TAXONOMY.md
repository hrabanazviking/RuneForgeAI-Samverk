# Samverk Audit Event Taxonomy — v1

*Slice S-008. The frozen vocabulary of the audit log (study 35).
Enforced in code by `samverk/taxonomy.py`: `AuditLog.append` refuses
any name not in this document's set.*

## Rules

- Names are `family.subject.verb`, lowercase, dot-separated.
- **v1 names are never renamed or removed.** A name that stops being
  emitted is marked *(deprecated)* here and stays valid forever — old
  rows must remain interpretable for the life of the instance.
- Additions append new names (and are recorded in
  `PROJECT_MEMORY_MAP.md` when they land); they never change an
  existing name's meaning.
- Every event carries the standard fields of study 35 §2 (seq, ts,
  actor_kind, actor_id, target_kind, target_id, source_ip, outcome).
  The `detail` column holds only the safe specifics listed per event
  — never secrets, tokens, passwords, or request bodies (S-018).

## auth — authentication and credentials

| Event | Meaning | detail carries |
|---|---|---|
| `auth.signup.success` | Account created | `{"method": "invite"\|"open"}` |
| `auth.signup.denied` | Signup refused (throttle/policy) | `{"reason": ...}` |
| `auth.login.success` | Login succeeded | `{"method": "password"}` |
| `auth.login.failure` | Login failed | `{"attempted_user": ...}` (see study 35 §4 caveat) |
| `auth.logout` | Session ended by its owner | — |
| `auth.password.change` | Password changed (sessions revoked) | — |
| `auth.password.reset` | Password reset completed | `{"via": "email"\|"operator"}` |
| `auth.token.create` | API/access token created | `{"token_id": ..., "scopes": [...]}` — never the token |
| `auth.token.revoke` | Token revoked | `{"token_id": ...}` |
| `auth.ssh_key.add` | SSH key registered | `{"fingerprint": ...}` |
| `auth.ssh_key.remove` | SSH key removed | `{"fingerprint": ...}` |
| `auth.twofactor.enable` | 2FA enrolled | `{"method": "totp"\|"webauthn"}` |
| `auth.twofactor.disable` | 2FA removed | — |
| `auth.twofactor.reset` | 2FA reset via recovery | — |
| `auth.session.revoke` | A session (or all) revoked | `{"scope": "one"\|"all"}` |
| `auth.email.verify` | Email verification token redeemed (S-026; outcome distinguishes success from denied) | `{"reason": ...}` on denial only |
| `auth.profile.update` | Profile text or avatar changed (S-029) | `{"fields": "text"\|"avatar"}` |

## repo — repositories and their security surface

| Event | Meaning | detail carries |
|---|---|---|
| `repo.create` | Repository created | `{"visibility": ...}` |
| `repo.delete` | Repository deleted | — |
| `repo.visibility.change` | Visibility changed | `{"from": ..., "to": ...}` |
| `repo.transfer` | Ownership transferred | `{"from_owner": ..., "to_owner": ...}` |
| `repo.push` | Refs updated by a push | `{"ref": ..., "old": ..., "new": ...}` (oid prefixes) |
| `repo.protection.change` | Branch protection changed | `{"branch": ..., "rule": ...}` |
| `repo.collaborator.add` | Collaborator added | `{"user": ..., "role": ...}` |
| `repo.collaborator.remove` | Collaborator removed | `{"user": ...}` |
| `repo.collaborator.role_change` | Collaborator role changed | `{"user": ..., "from": ..., "to": ...}` |
| `repo.release.publish` | Release published | `{"tag": ...}` |
| `repo.webhook.add` | Webhook added (an exfiltration path; watched) | `{"host": ...}` — never the secret |
| `repo.webhook.remove` | Webhook removed | `{"host": ...}` |
| `repo.settings.change` | Security-relevant repo setting changed | `{"key": ..., "from": ..., "to": ...}` |

## admin — instance administration

| Event | Meaning | detail carries |
|---|---|---|
| `admin.user.create` | Admin created a user | — |
| `admin.user.disable` | User disabled | `{"reason": ...}` |
| `admin.user.delete` | User deleted | — |
| `admin.user.role_change` | Instance role changed | `{"from": ..., "to": ...}` |
| `admin.settings.change` | Instance setting changed | `{"key": ..., "from": ..., "to": ...}` |
| `admin.plaintext_http_override` | Plaintext-HTTP override armed (S-015) | `{"scope": ...}` |
| `admin.audit.ip_disclosure` | Audit IP display enabled/disabled for a scope | `{"scope": ..., "enabled": true\|false}` |
| `admin.audit.export` | Audit log exported | `{"scope": ..., "entries": ...}` |
| `admin.key.rotate` | Instance key rotated (S-020) | `{"key": ...}` — the key's name, never its value |
| `admin.user.approve` | Operator approved a pending account (S-026, the no-SMTP road) | `{"from_status": ...}` |

## Version note

Taxonomy v1, frozen 2026-10-29 with S-008. 37 events: 15 auth,
13 repo, 9 admin. The machine-readable set lives in
`samverk/taxonomy.py`; a battery test asserts this document and the
code name exactly the same set.

Additions (append-only, meanings of existing names unchanged):
S-026 (2026-10-30) added `auth.email.verify` and
`admin.user.approve` — 39 events: 16 auth, 13 repo, 10 admin.
S-029 (2026-10-30) added `auth.profile.update` — 40 events:
17 auth, 13 repo, 10 admin.
