# Quotas (S-068 + S-354)

Samverk enforces storage quotas at one point: the
receive-time judgement in
`samverk.repo_quotas.QuotaService.check_receive`, which
the S-089 receive gate consults before any object is
accepted. A push that would break a limit is refused
before anything lands, with a message that says, in
plain numbers, how much is held, what the limit is, and
how much the push tried to add.

## The two levels

- **Per-repository** (S-068): an explicit quota on one
  repository, set by its owner or a site admin
  (`set_repo_quota`), or the instance default an admin
  set (`set_default_quota`, stored as
  `repo_quota_default_bytes`). Per-repo wins over the
  default; absence of both means unlimited.
- **Per-user** (S-354): an explicit quota on everything
  one owner holds, measured as the sum of the same
  S-058 filesystem walk over all of the owner's
  repositories. Set by a site admin only
  (`set_user_quota`, stored as
  `user_quota_bytes:<owner>`), or the instance user
  default an admin set (`set_default_user_quota`,
  stored as `user_quota_default_bytes`). Per-user wins
  over the user default; absence of both means
  unlimited. An owner cannot set their own user quota:
  a ceiling you can raise yourself is no ceiling.

Both levels are judged on every receive, repository
first, then user. The refusal names the level that bit
(`ReceiveDecision.blocked_by` is `"repository"` or
`"user"`), and the decision object carries both levels'
usage and limit either way. Raising the biting quota
lets the same push through; nothing is cached, every
judgement re-measures.

Upload stores (release assets, CI artifacts) keep
their own S-268 gate on the joined storage account;
this document covers the receive-time quota point.

## Seeing it before it bites

`samverk.quotas.QuotaOverviewService.overview_for`
builds one owner's whole account -- the per-user total
against the user quota, plus one row per repository
with its usage against its own quota -- stated in
plain words by `overview_words` and rendered by
`render_quotas_page`. Owners and site admins may read
an account; anyone else is refused. Reading is a
measurement, not an act: it appends no audit entry.

## Who may set what

| Quota | Who | Audit |
| --- | --- | --- |
| Per-repository | Owner or site admin | `repo.settings.change` (S-068) |
| Instance repo default | Site admin | (S-068 door) |
| Per-user | Site admin only | `admin.settings.change`, key `user_quota_bytes` |
| Instance user default | Site admin only | `admin.settings.change`, key `user_quota_default_bytes` |

No migration (schema 139 stands) and no new audit verb
(taxonomy 138 stands: 33 auth / 92 repo / 13 admin);
the per-user values ride the settings table.
