# User guide (S-397)

The one starting point for a person who uses a Samverk
instance. Every door named here was walked or read
against a live instance by S-397
(docs/documentation-completeness-s397.md).

## 1. Your account

You register an account with a username and a password
judged by the instance's registration law; sign-in is by
session. An administrator's first sign-in home shows the
next three things to do, in plain words — the same three
doors below.

## 2. Mint a token

Personal access tokens are created on the token settings
page (`/settings/tokens`). A token is shown once at
creation; scripts authenticate to the API with the token
or with session-free Basic, and every API call is judged
by the same permission engine as the web surface.

## 3. Create a repository

A repository is created under your own name with the
web's own creation law — through the API that is
`POST /api/v1/repos`. Repositories hold real git history:
you clone, push and pull with standard git commands over
HTTP or SSH. Forks, branches and contents reads carry
the same permissions on every surface.

## 4. Issues and pull requests

Issues and pull requests run their full lifecycle — open,
comment, label, assign, review, merge — on the web and
through the API with parity: a script can drive an entire
pull request from open to merge. Search finds code,
repositories, issues, pulls and people within the limits
in docs/SEARCH_LIMITS.md.

## 5. Webhooks

Repositories and organizations can subscribe to webhook
events; deliveries are signed, queued off the request
path, logged, and redeliverable. The event taxonomy is
docs/WEBHOOK_EVENTS.md and the API contract for all of
the above is docs/API_CONTRACT.md.

## Honest limits

Repository creation's landed door today is the API
(`POST /api/v1/repos`); no standalone web page for it is
claimed here. Where a surface is a service module rather
than a route on the bare server, the API contract says
so — landed means landed, contracted means contracted.
