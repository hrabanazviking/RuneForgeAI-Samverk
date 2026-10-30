# Samverk — Project Memory Map

*The living map of this project, per the Forge Protocol: updated in the
same session as any work it records. If it is not written here, it did
not happen.*

## What this is

**Samverk** — our own clean-room, open-source version-control application.
An extremely robust, highly secure equivalent of GitHub's feature set,
studied from public behaviour and documentation, copying no code, assets,
or proprietary design. Standalone-first; integrable into Samtal as its
code-and-file-sharing heart; bearer of the standing duty to mirror
Volmarr's original repos onto his own machines.

- Repo: `hrabanazviking/RuneForgeAI-Samverk` (public)
- Licence: AGPL-3.0 (placed by Volmarr at the founding; never alter)
- Name: chosen by Volmarr 2026-10-29 from the Skald's five candidates
  (*Samverk* = the together-work; siblings: Samtal the together-talk,
  Samkoma the together-gathering)

## Founding decisions (2026-10-29)

- **Commissioned by Volmarr** in a voice call after Forgejo — installed on
  purplelongship, reset after a lost password — proved unusable to its
  owner (everyday controls unfindable). Samverk's founding virtues answer
  that failure: user-friendliness is law; security is the spine;
  sovereignty (native installs, **no Docker ever**); standard git;
  standalone first, Samtal seam second.
- **Clean-room rule:** features and behaviour are studied; no GitHub code,
  assets, or proprietary UI are copied. Stated in the roadmap preamble
  and `research/INDEX.md`, binding on every slice and study.
- **Architecture stance:** Python, stdlib-first, Samtal-pattern (SQLite
  state, one program family); git plumbing does git's work; three stores
  (SQLite / filesystem / git) under one event store.
- **Cross-platform law** (Volmarr, 2026-10-29, founding): Samverk is
  cross-platform completely — server on Linux, Windows, macOS; x86-64
  and ARM down to Raspberry Pi-class hardware; UI reachable from any
  modern browser/device. Roadmap virtue 6, Part I commitment, and
  Part XXII (S-405–S-416) carries the proof: a matrix cell is PROVEN
  only when its battery ran there, NOT PROVEN until then.
- **Design law** (Volmarr, 2026-10-29, founding): Samverk must look
  *really nice* in his modern Cyber-Viking design language. Its face is
  designed under the Cyber-Viking Visual Design Lawbook, with the
  design warband seated in roadmap Part XX by office — Hallveig
  (design-system architecture), Rannveig (composition), Solveig
  (design-to-code contracts), Ljósbera (colour/light), Rúnhildr
  (type/runes), Tove (accessibility; holds the Book XIV ship-gate
  veto). Ship gate bound as acceptance: grayscale coherence, 125–200%
  scaling, effects-off coherence, no colour-only status.
- **Roadmap:** `docs/SAMVERK_MASSIVE_ROADMAP.md` — **416 slices, 22
  parts**, slice sequence machine-verified continuous (S-001–S-416).
- **Research corpus:** `research/` — 46 empty study files +
  `INDEX.md` carrying each study question (Volmarr's exact founding ask:
  empty files first; words land as studies are done).
- **Standing exclusions:** no Docker; no federation; no hosted-service
  ambitions; no AI features that invent facts.

## Current state

- **Phase: Part I underway** (Volmarr's go-ahead, 2026-10-29 ~21:39
  EDT). Campaign branch: `yrsa/samverk-part1`.
- **Part I research complete (2026-10-29):** studies 31 (threat
  model), 35 (audit log), 42 (data model & storage), 07 (passwords &
  sessions) written and committed.
- **S-001 DONE (2026-10-29)** — threat model ratified: threat register
  T-01…T-20, trust boundaries TB1…TB8, honest limits §6 of study 31.
- **S-002 DONE (2026-10-29)** — project skeleton: `samverk/` package
  (config loading, platform seam, `samverk serve`), `pyproject.toml`
  (stdlib-only), acceptance battery `tests/test_skeleton.py`:
  **10 passed / 0 failed** on Linux x86-64 (this VM), including the
  literal acceptance — a fresh `python -m samverk serve` process
  answering `/healthz`. Platform cells beyond this machine (Pi,
  Windows, macOS) are **NOT PROVEN** — Part XXII owns their proof;
  the skeleton's platform touchpoints exist only behind
  `samverk/platform_seam.py`, mechanically checked by test.
- **S-003 DONE (2026-10-29)** — secrets law: `samverk/secrets.py`
  (env or mode-600 file only, fail-closed on loose permissions,
  values never repr'd), `samverk/db.py` connection factory (WAL +
  synchronous=FULL + foreign_keys=ON + busy_timeout 5000, numbered
  transactional migrations), battery `tests/test_secrets.py`:
  **9 passed / 0 failed**, including the literal acceptance — a
  seeded DB (with a `secret:NAME` reference row) greps clean of both
  file- and env-sourced secret values. Cumulative battery: 19/19.
- Next: S-004 password hashing.
- The classified inventory of Volmarr's original repos (the mirror
  fixture for Part XVII) lives at `~/workspace/forgejo-backup/` — kept
  outside this repo; its 17 UNCERTAIN-classified repos each need
  Volmarr's word before mirroring.

## Session log

- **2026-10-29** — Founding. Repo created by Volmarr (LICENSE + stub
  README with his approved description). By Yrsa: research scaffold
  (44 empty files + INDEX), tentative README developed from his stub
  (his title and description preserved verbatim at the head), massive
  roadmap authored after public-source study of GitHub's feature
  surface (docs.github.com product/security documentation; git protocol
  references), and this map seeded. All pushed and remote-verified.
- **2026-10-29 (later)** — Two founding amendments by Volmarr's word:
  cross-platform as founding law (research file 45, roadmap virtue 6,
  new Part XXII, S-405–S-416 — roadmap now 416 slices / 22 parts) and
  the Cyber-Viking design law (research file 46; Part XX binds the
  design warband by office and the Book XIV ship gate as acceptance;
  README and this map carry the plain statement). Corpus now 46 study
  files. Pushed and remote-verified.
- **2026-10-29 (campaign opens)** — Volmarr's go-ahead ~21:39 EDT.
  Part I studies 31/35/42/07 completed as genuine clean-room studies;
  **S-001 DONE** (threat model ratified). Work proceeds on branch
  `yrsa/samverk-part1`; banking to main is the coordinator's step,
  verified by ls-remote.
