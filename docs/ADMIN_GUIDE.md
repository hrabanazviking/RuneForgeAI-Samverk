# Admin guide (S-397)

The one starting point for an instance administrator.
Every surface named here was walked against a live
instance by S-397 (docs/documentation-completeness-s397.md).

## 1. Become the first admin

Two roads, both judged by the same law: the install walk
(docs/INSTALL_WALK.md) creates the first admin during
installation, and the CLI door
`samverk admin create-first-admin --username NAME`
creates it afterwards — first means first: the door
refuses whenever any admin already exists. The full
account is docs/FIRST_ADMIN.md (S-350). Your first
sign-in home shows the next three things to do: mint a
token, create a repository, set up a mirror.

## 2. The admin panel

The admin panel is the one desk for users, organizations
and repositories: one search box over all three subjects,
and destructive actions (create/suspend/delete user,
delete repository or organization, role change) that are
sudo-gated, audit-logged and fail-closed — without an
audit log and a fresh sudo grant they are refused, by
construction. The full account is docs/ADMIN_PANEL.md
(S-351).

## 3. Site settings

Instance-wide settings an admin governs stand in
docs/SITE_SETTINGS.md; boot-time configuration an
operator governs stands in docs/CONFIGURATION.md — the
admin guide keeps the two apart on purpose: settings are
changed on a running instance, configuration is read
before the database opens.

## 4. Watch the instance

`GET /admin/status` is the operator's page (admins only;
anonymous callers are refused, as S-397's walk verified
live). The instance audit view and the abuse queue are
their own documents in docs/ (INSTANCE_AUDIT_VIEW.md,
ABUSE_QUEUE.md).
