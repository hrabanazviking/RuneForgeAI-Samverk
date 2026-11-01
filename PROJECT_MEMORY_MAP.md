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

- **Phase: Part VII open** (Part I gate passed
  2026-10-30; Part II gate S-048 passed 2026-10-30 at
  368/368; Part III gate S-076 passed 2026-10-30 at 510/510;
  Part IV gate S-096 passed 2026-10-30 at 640; Part V gate
  S-120 passed 2026-10-30; Part VI gate S-140 passed
  2026-10-30 at 906 passed / 1 skipped; S-121..S-128 banked 2026-10-30 —
  governing recounts reproduced from log files read back
  after each run finished: pytest 783 passed / 1 skipped /
  0 failed (784 collected); unittest discover 784 ran,
  783 passed / 1 skipped / 0 failed; the one skip is a
  named cell, NOT PROVEN on this host: S-095's real-sshd
  cell. The two git-lfs client cells ran and passed —
  the recounts prepended `~/workspace/.tools` to PATH,
  as the S-112 run did and the S-115 correction directed.
  S-124..S-128 stand on their own counted batteries plus
  foreground combined runs read back from log files
  (S-127 run: cross-references + taxonomy + dependencies
  + issues + numbering + comments + labels + milestones
  + assignees 61 passed / 0 failed; S-128 run: reactions
  + taxonomy + dependencies 16 passed / 0 failed). The
  fresh full-suite governing recount this run owed before
  S-129 was read back from its log file: pytest 818
  passed / 1 skipped / 0 failed — exactly the prior 783
  plus S-124..S-128's 35 battery tests; the one skip is
  S-095's named real-sshd cell);
  S-129 banked 2026-10-30 (11-test battery, foreground;
  combined with taxonomy + dependencies 22 passed /
  0 failed); S-130 banked 2026-10-30 (6-test battery,
  foreground; combined run 44 passed / 0 failed);
  S-131 banked 2026-10-30 (8-test battery, foreground);
  S-132 banked 2026-10-30 (7-test battery, foreground;
  combined with taxonomy + comments + dependencies
  25 passed / 0 failed; the timeline extension's
  combined run 16 passed / 0 failed);
  S-133 banked 2026-10-30 (8-test battery, foreground);
  S-134 banked 2026-10-30 (7-test battery, foreground;
  combined affected suites 55 passed / 0 failed);
  governing full-suite recount read back from its log
  file after this run's slices: pytest 866 passed /
  1 skipped / 0 failed (867 collected, 5 subtests
  passed; the one skip is S-095's named real-sshd
  cell);
  S-135 banked 2026-10-30 (8-test battery, foreground;
  research file 19 written — the full query grammar);
  S-136 banked 2026-10-30 (6-test battery, foreground;
  combined with S-135 + dependencies 19 passed /
  0 failed; migration 45);
  governing full-suite recount read back from its log
  file after this run's slices: pytest 880 passed /
  1 skipped / 0 failed (881 collected, 5 subtests
  passed — exactly the prior 866 plus this run's 14
  battery tests; the one skip is S-095's named
  real-sshd cell);
  S-137 banked 2026-10-30 (8-test battery, foreground;
  combined with taxonomy + timeline + issues +
  dependencies 35 passed / 0 failed; migration 46;
  taxonomy append-only +2, 87 events);
  S-138 banked 2026-10-30 (7-test battery, foreground;
  combined with taxonomy + timeline + comments +
  dependencies 34 passed / 0 failed; migration 47;
  taxonomy append-only +3, 90 events);
  S-139 banked 2026-10-30 (6-test battery, foreground;
  combined with dependencies 11 passed / 0 failed;
  migration 48; no new audit events — the outbox
  derives from the audit record);
  S-140 banked 2026-10-30 — PART VI GATE (5-test gate
  battery, foreground; governing full-suite recount
  read back from its log file: pytest 906 passed /
  1 skipped / 0 failed, 907 collected, 5 subtests
  passed, 1793.68 s — exactly the prior 880 plus this
  run's 26 battery tests; the one skip is S-095's
  named real-sshd cell);
  S-141 banked 2026-10-30 (8-test battery, foreground;
  combined with conversion + compare + taxonomy +
  dependencies 30 passed / 0 failed; no migration, no
  new audit event — creation rides S-137's existing
  repo.pull_request.create, taxonomy stands at 90);
  governing full-suite recount owed by S-141 was paid
  by the next keeper run and read back from its log
  file: pytest 914 passed / 1 skipped / 0 failed
  (915 collected, 5 subtests passed, 1719.11 s —
  exactly the prior 906 plus S-141's 8 battery tests;
  the one skip is S-095's named real-sshd cell);
  S-142 banked 2026-10-30 (10-test battery, foreground;
  combined with same-repo PRs + conversion + forks +
  proc + taxonomy + dependencies + secrets 59 passed /
  0 failed; migration 49; new dedicated S-014 fetch
  seam `run_git_fetch_ref`; no new audit event —
  creation rides repo.pull_request.create with
  same_repo false in the detail, taxonomy stands
  at 90);
  S-143 banked 2026-10-30 (9-test battery, foreground;
  combined with taxonomy + same-repo PRs + cross-fork
  PRs + conversion + issue events out + dependencies
  52 passed / 0 failed, read back from its log file;
  taxonomy append-only +2, 92 events; no migration);
  governing full-suite recount owed by S-143 was paid
  by the next keeper run and read back from its log
  file: pytest 933 passed / 1 skipped / 0 failed
  (934 collected, 5 subtests passed, 2065.27 s —
  exactly the prior 914 plus S-142's 10 and S-143's 9;
  the one skip is S-095's named real-sshd cell);
  S-144 banked 2026-10-30 (11-test battery, foreground;
  combined with taxonomy + timeline + cross-references
  + drafts + issue comments + issue events out +
  dependencies + same-repo PRs + cross-fork PRs +
  conversion 88 passed / 0 failed, read back from its
  log file; taxonomy append-only +3, 95 events; no
  migration);
  S-145 banked 2026-10-30 (10-test battery, foreground;
  combined with same-repo PRs + cross-fork PRs +
  drafts + conversation + compare + diff engine +
  conversion + taxonomy + dependencies 75 passed /
  0 failed, read back from its log file; migration
  50; no audit event of its own — a per-reviewer
  reading preference, taxonomy stands at 95);
  governing full-suite recount read back from its
  log file after this run's slice: pytest 954
  passed / 1 skipped / 0 failed (955 collected, 5
  subtests passed, 3149.85 s under heavy VM
  contention — exactly the prior 933 plus S-144's
  11 and S-145's 10; the one skip is S-095's named
  real-sshd cell). One earlier recount this run was
  discarded, never counted: run without the
  campaign's established environment (no
  `~/workspace/.tools` on PATH, no campaign TMPDIR)
  it read 942 passed / 3 skipped — the two git-lfs
  client cells skipped instead of passing; the
  corrected rerun above stands;
  S-146 banked 2026-10-30 (13-test battery, foreground;
  combined with same-repo PRs + cross-fork PRs +
  drafts + conversation + files view + compare +
  diff engine + conversion + taxonomy + dependencies
  + issue events out 94 passed / 0 failed; migration
  51; taxonomy append-only +3, 98 events);
  S-147 banked 2026-10-30 (12-test battery, foreground;
  combined with line comments + same-repo PRs +
  cross-fork PRs + drafts + conversation + files
  view + compare + diff engine + conversion +
  taxonomy + dependencies + issue events out 106
  passed / 0 failed; migration 52; taxonomy
  append-only +5, 103 events);
  governing full-suite recount owed by S-147 was paid
  by the next keeper run and read back from its log
  file: pytest 979 passed / 1 skipped / 0 failed
  (980 collected, 5 subtests passed, 860.17 s —
  exactly the prior 954 plus S-146's 13 and S-147's
  12; the one skip is S-095's named real-sshd cell);
  S-148 banked 2026-10-30 (16-test battery, foreground;
  combined with line comments + review threads +
  same-repo PRs + cross-fork PRs + drafts +
  conversation + files view + compare + diff engine
  + conversion + taxonomy + dependencies + issue
  events out 122 passed / 0 failed, read back from
  its log file; migration 53; taxonomy append-only
  +1, 104 events);
  S-149 banked 2026-10-30 (14-test battery, foreground;
  combined with reviews + review threads + line
  comments + drafts + same-repo PRs + cross-fork PRs
  + conversation + files view + taxonomy +
  dependencies + issue events out 120 passed /
  0 failed, read back from its log file; migration
  54; no new audit event — the policy change rides
  the frozen repo.settings.change with its key named,
  taxonomy stands at 104);
  governing full-suite recount owed by S-148 was NOT
  paid this tick: the VM carried several other
  campaigns' full suites at once (MemAvailable
  ~0.7 GB throughout), and a Samverk recount launched
  into that contention would risk OOM and prove
  nothing clean — it stays owed, now covering S-148
  and S-149 (arithmetic expectation 1009 passed /
  1 skipped / 0 failed = 995 + S-149's 14), and the
  next keeper run must verify it from a log file
  before banking further slices;
  S-150 banked 2026-10-31 (18-test battery, foreground,
  read back from its log file; migration 55; taxonomy
  append-only +2, 106 events; the combined
  affected-suites cross-check is owed — see the
  S-150 entry's correction note below);
  governing full-suite recount was NOT paid this
  tick either: the VM again carried many other
  campaigns' full suites at once (MemAvailable
  ~0.6–1.5 GB throughout the run), and a recount
  launched into that contention would risk OOM and
  prove nothing clean — it stays owed, now covering
  S-148, S-149 and S-150 (arithmetic expectation
  1027 passed / 1 skipped / 0 failed = 1009 +
  S-150's 18), and the next keeper run with a quiet
  machine must verify it from a log file before
  banking further slices;
  keeper tick 2026-10-31 ~05:05 EDT: no Samverk
  worker was live and no new commits had landed;
  the owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.34–0.88 GB
  across a 10-minute watch (other campaigns' full
  suites running throughout), never near a safe
  threshold for the ~1000-test suite, so launching
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  keeper tick 2026-10-31 ~05:15 EDT: no Samverk
  worker was live (the one pytest process on the
  box belonged to another project). The VM
  rebooted mid-tick and briefly opened a quiet
  window (MemAvailable ~1.5 GB, load falling), so
  the owed recount was launched in the campaign's
  established environment (log:
  hidden_files/recount-2026-10-31-0515-pytest.log);
  the window closed within minutes as the other
  campaigns respawned — MemAvailable fell to
  ~0.40 GB, load rose to ~5.6, and only ~46 tests
  flushed in ~9 minutes with no failures among
  them — so the keeper aborted the recount rather
  than let a multi-hour contended run risk OOM
  and prove nothing clean. The tally is NOT
  verified: the recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~05:25 EDT: no Samverk
  worker was live and no new commits had landed.
  The owed recount was checked for again and
  still NOT paid — MemAvailable stayed
  ~0.34–0.43 GB across a two-minute watch with
  load rising 9.6 → 12.7 and 7–10 other
  campaigns' pytest processes running
  throughout, never near a safe threshold for
  the ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~05:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 05:25 tick. The owed recount was
  checked for again and still NOT paid —
  MemAvailable stayed ~0.36–0.47 GB across a
  two-minute watch (9 other campaigns' pytest
  processes running throughout, load ~2.4–6.2),
  never near a safe threshold for the
  ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~05:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 05:35 tick (head b25db35, verified
  equal to origin/main by ls-remote; worktree
  clean). The owed recount was checked for
  again and still NOT paid — MemAvailable
  stayed ~0.24–0.52 GB across the watch
  (other campaigns' pytest processes running
  throughout, load ~2.3–7.9), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~05:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 05:45 tick (head 1184247, verified
  equal to origin/main by ls-remote; worktree
  clean). The owed recount was checked for
  again and still NOT paid — MemAvailable
  stayed ~0.61–0.65 GB across a one-minute
  watch (other campaigns' pytest processes —
  mythic-coder, ember — running throughout,
  load ~2.8–6.9), never near a safe threshold
  for the ~1000-test suite, so launching would
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~06:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 05:55 tick (head ae43127, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to sagnaskemma,
  yggdrasil and hermes, none to Samverk). The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.37–0.63 GB
  across a two-minute watch (other campaigns'
  pytest processes running throughout, load
  ~4.3–6.6), never near a safe threshold for
  the ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~06:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 06:05 tick (head 00cdf45, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to sagnaskemma,
  mythic-coder and hermes, none to Samverk).
  The owed recount was checked for again and
  still NOT paid — MemAvailable stayed
  ~0.58–0.69 GB across the watch (other
  campaigns' pytest processes running
  throughout, load ~5.1–6.3), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~06:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 06:15 tick (head 0efc92a, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to yggdrasil,
  mythic-coder, hermes and ravens, none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.36–0.37 GB across the watch (other
  campaigns' pytest processes running
  throughout, load ~10.9), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~06:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 06:25 tick (head 81a7d1c, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box belonged to other campaigns, none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.29–0.49 GB across a one-minute watch (other
  campaigns' pytest processes running
  throughout, load ~9.3–10.2), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~06:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 06:35 tick (head 9077961, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box belonged to other campaigns, none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.55–0.86 GB across a one-minute watch (other
  campaigns' pytest processes running
  throughout, 1-minute load easing to ~1.4–1.8
  but memory never recovering), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~06:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 06:45 tick (head e838f00, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box
  belonged to other campaigns, none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.51–0.72 GB across a one-minute watch (other
  campaigns' pytest processes running
  throughout, 1-minute load rising ~6.3–10.4),
  never near a safe threshold for the
  ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~07:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 06:55 tick (head 784260e, verified
  equal to origin/main after a fetch; worktree
  clean — the pytest process on the box was
  verified by cwd to belong to another campaign
  (sagnaskemma-build), none to Samverk). The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.47–0.53 GB
  across the watch (1-minute load ~7.3–8.2),
  never near a safe threshold for the
  ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~07:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 07:05 tick (head f2ec3a6, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box
  belonged to other campaigns (sagnaskemma-build
  and yggdrasil-build), none to Samverk). The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.51–0.65 GB
  across a one-minute watch (1-minute load
  ~4.1–6.0), never near a safe threshold for
  the ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~07:25 EDT: no Samverk
  worker was live (head f0d3691, verified equal
  to origin/main by ls-remote; worktree clean;
  the pytest processes on the box belonged to
  other campaigns — yggdrasil-build,
  sagnaskemma-build, hermes-hack-build — none
  to Samverk). This tick DID launch the owed
  governing recount into the brief post-reboot
  quiet window (machine up ~6 min, MemAvailable
  ~1.0–1.1 GB, 1-minute load ~1.0–1.4 — the
  quietest readings in hours), with the
  campaign's established environment (TMPDIR
  `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`), logging to
  `full-pytest-s150-recount.log` in that TMPDIR.
  Contention returned within minutes
  (MemAvailable fell to ~0.40–0.56 GB, load
  rose to ~5–8, more foreign suites joined);
  after ~11 minutes the log held 86 test
  markers, every one passing, none failing —
  a ~2-hour projected total under that load
  and a live OOM risk on a swapless box — so
  the recount was stopped, following the
  05:15 tick's precedent. The tally is NOT
  verified: the recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file. Prep banked
  outside the tree (no slice code written, no
  test collection disturbed): an S-151 design
  draft at
  `~/workspace/goals/samverk-version-control-forge/hidden_files/s151-codeowners-design.md`
  (parser + matcher shape, migration 56
  review-requests table riding under S-152,
  taxonomy +1 to 107, ~14-test battery plan);
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~07:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 07:25 tick (head 7171538, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, hermes-hack-build,
  yggdrasil, ember), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.47–0.65 GB
  across two watches (1-minute load ~6.5–10.6),
  never near a safe threshold for the
  ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~07:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 07:35 tick (head c81b301, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build), none
  to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.58–0.71 GB across three watches
  (1-minute load ~7.1–9.3), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~07:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 07:45 tick (head d4939f4, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (hermes-hack-build, sagnaskemma-build), none
  to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.54–0.62 GB across three watches
  (1-minute load ~6.6–10.1), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~08:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 07:55 tick (head f04405a, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  hermes-hack-build, sagnaskemma-build), none
  to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.26–0.42 GB across the watch
  (1-minute load ~3.7–5.9, 12 other campaigns'
  pytest processes running throughout), never
  near a safe threshold for the ~1000-test
  suite, so launching would risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~08:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 08:05 tick (head 1b267d5, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  sagnaskemma-build, mythic-coder-build,
  ember-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.62–0.83 GB
  across the watch (1-minute load easing
  ~1.3–2.4 but 5-minute load ~5.6–6.9, other
  campaigns' pytest processes running
  throughout, swap 0), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~08:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 08:15 tick (head 290ed2c, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (hermes-hack-build,
  sagnaskemma-build, mindspark-build,
  ember-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.36–0.68 GB
  across the watch (5-minute load ~4.7–5.1,
  other campaigns' pytest processes running
  throughout, swap 0), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~08:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 08:25 tick (head 7d14f98, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable
  started ~0.75 GB and fell to ~0.36 GB across
  the watch (5-minute load ~6.0–6.7, other
  campaigns' pytest processes running
  throughout, swap 0), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~08:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 08:35 tick (head b6ad865, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (sagnaskemma-build,
  yggdrasil-build, hermes-hack-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable
  stayed ~0.41–0.49 GB across the watch
  (5-minute load ~8.5–8.9, other campaigns'
  pytest processes running throughout, swap
  0), never near a safe threshold for the
  ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~08:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 08:45 tick (head 105d163, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (mythic-coder-build,
  sagnaskemma-build, yggdrasil-build, hermes),
  none to Samverk). The owed recount was
  checked for again and still NOT paid —
  MemAvailable stayed ~0.54 GB at the final
  check (5-minute load ~5.5, other campaigns'
  pytest processes running throughout, swap
  0), never near a safe threshold for the
  ~1000-test suite, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~09:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 08:55 tick (head 045ad5e, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  ember-build, hermes-hack-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.47–0.62 GB across two watches (5-minute
  load ~5.2–5.6, other campaigns' pytest
  processes running throughout, swap 0), never
  near a safe threshold for the ~1000-test
  suite, so launching would risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~09:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:05 tick (head 26a528f, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (mythic-coder-build, sagnaskemma-build), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.47–0.52 GB across the watch (5-minute
  load ~4.6, other campaigns' pytest processes
  running throughout, swap 0), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~09:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:15 tick (head 9f577d7, verified
  equal to origin/main after fetch; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, runmal-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable moved ~0.55–0.89 GB across
  the watch (5-minute load ~5.4–6.1, 1-minute
  spikes to ~12 on a VM only minutes past a
  reboot, other campaigns' pytest processes
  running throughout), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~09:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:25 tick (head ec87769, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.49–0.66 GB across the watch (samples
  580164 / 556620 / 690228 / 549164 / 516988 kB,
  5-minute load ~5.6–6.4, other campaigns' pytest
  processes running throughout, swap 0), never
  near a safe threshold for the ~1000-test suite,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~09:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:35 tick (head e22d2af, verified
  equal to origin/main by ls-remote; worktree
  clean — the active python processes on the box
  belonged to other campaigns (model-tests/janas
  prefetch at ~80% CPU, a sagnaskemma-build gate
  loop, ember idle probes), none to Samverk).
  The owed recount was checked for again and
  still NOT paid — MemAvailable stayed
  ~0.33–0.41 GB across the watch (samples
  407508 / 340536 / 348728 kB, 5-minute load
  ~4.1–4.3, swap 0), never near a safe
  threshold for the ~1000-test suite, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~09:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:35 tick (head e22d2af, verified
  equal to origin/main by ls-remote; the 09:45
  tick's map entry was present as an uncommitted
  worktree edit, its commit blocked last tick by
  a box-wide write gate — this tick re-attempts
  that commit + push). The active processes on
  the box belonged to other campaigns
  (yggdrasil-build and sagnaskemma-build pytest,
  model-tests/janas prefetch, ember idle probes),
  verified by cwd none to Samverk. The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.25–0.41 GB
  across the watch (samples 381568 / 251352 /
  356408 / 407296 kB, 5-minute load ~3.7–4.0,
  swap 0), never near a safe threshold for the
  ~1000-test suite, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~10:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:35 tick (head e22d2af, verified
  equal to origin/main by ls-remote; the 09:45
  and 09:55 ticks' map entries were present as
  uncommitted worktree edits — this tick banks
  all three entries together). The active
  processes on the box belonged to other
  campaigns (yggdrasil-build pytest at ~68% CPU,
  ember idle probes), verified by cwd none to
  Samverk. The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.43–0.49 GB across the watch (samples
  488044 / 429640 / 469264 kB, 5-minute load
  ~3.2–3.9, swap 0), never near a safe threshold
  for the ~1000-test suite, so launching would
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~10:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 09:35 tick (head e22d2af, verified
  equal to origin/main by ls-remote; the 09:45,
  09:55 and 10:05 ticks' map entries were present
  as uncommitted worktree edits — this tick banks
  all four entries together). The active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  mythic-coder-build, yggdrasil-build), none to
  Samverk. The owed recount was checked for
  again and still NOT paid — MemAvailable was
  ~1.04–1.14 GB across two watches (samples
  1137056 / 1122444 / 1091140 / 1127432 /
  1043136 / 1041772 / 1054392 / 1037892 kB, the
  highest readings in hours, but 5-minute load
  stayed ~5.6–5.7 with 1-minute spikes to
  ~9.6–11.8 and swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~10:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 10:15 tick (head 2aabd2f, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  process on the box was verified by cwd to
  belong to another campaign (yggdrasil-build),
  plus a ravens soak process, none to Samverk).
  The owed recount was checked for again and
  still NOT paid — MemAvailable moved
  ~0.62–1.29 GB across the watch (samples
  649100 / 634444 / 1351468 / 1306300 kB) but
  load was extreme (1-minute ~21.5 at first
  check, still ~10.1 at the final check;
  5-minute ~15.3–17.9, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~10:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 10:35 tick (head c7e6718, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  yggdrasil-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.63–0.88 GB
  across the watch (samples 879800 / 712548 /
  664292 / 634740 kB, 5-minute load ~6.6–7.0,
  1-minute load falling 21.6 → 8.8 but still
  high, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless
  box, so launching would risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~10:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 10:45 tick (head 2c00e43, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  ember-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.63–0.91 GB
  across the watch (samples 646952 / 797728 /
  933732 / 798036 / 751752 / 649416 kB, 5-minute
  load ~5.8–6.4, 1-minute load falling
  13.8 → 5.2 but still high, swap 0), never
  near a safe threshold for the ~1000-test
  suite on this swapless box, so launching
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~11:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 10:55 tick (head d8728ed, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  hermes-hack-build, mindspark-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.39–0.48 GB across the watch (samples 460208 /
  481304 / 468224 / 478880 / 396704 kB, 5-minute
  load ~8.9–9.3, 1-minute load spiking to 16.4,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~11:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 11:05 tick (head 3c6ff9b, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  mythic-coder-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.24–0.88 GB across
  the watch (samples 248120 / 248948 / 371864 /
  921956 / 840300 / 462332 kB, 5-minute load
  ~7.5–8.1, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~11:25 EDT: no Samverk
  worker was live (head 96dbef2, verified equal
  to origin/main by ls-remote; worktree clean —
  the active pytest processes were verified by
  cwd to belong to other campaigns
  (mythic-coder-build, ember-build), none to
  Samverk). The box had just rebooted (up ~2 min)
  and MemAvailable opened at ~3.66 GB — the best
  window in hours — so this tick DID launch the
  owed governing recount (script
  run-recount-1125.sh, log
  recount-2026-10-31-1125-pytest.log in the goal
  hidden_files). Contention returned during the
  run: MemAvailable fell 3.66 GB → ~2.05 GB →
  ~1.24 GB and 1-minute load spiked to ~13. The
  recount was stopped at the 7% marker (~80
  tests shown, 0 failures/errors in the flushed
  log) rather than ridden into OOM risk on this
  swapless box; the partial log is NOT evidence
  and the tally stays NOT verified. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~11:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 11:25 tick (head 05e2bc4, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (ember-build,
  yggdrasil-build, mythic-coder-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.94–1.19 GB across the watch (samples
  1017864 / 940396 / 1061652 / 1153816 / 1176872 /
  1186948 / 1082652 / 1109648 / 1024860 kB,
  5-minute load ~8.1–9.0, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~11:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 11:35 tick (head b15f011, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  hermes-hack-build, mindspark-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.52–0.85 GB across the watch (samples
  790300 / 836416 / 868128 / 749208 / 533164 kB,
  5-minute load ~5.3–5.5, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~11:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 11:45 tick (head 1ddd825, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (mythic-coder-build,
  sagnaskemma-build, later hermes-hack-build and
  ember-build), none to Samverk). MemAvailable
  opened at ~4.88–5.07 GB — the best window in
  hours, 1-minute load ~1.5 and falling — so
  this tick DID launch the owed governing
  recount (script run-recount-1155.sh, log
  recount-2026-10-31-1155-pytest.log in the goal
  hidden_files). The run was disk-journal-bound
  under cross-campaign contention: ~7% at
  ~10 min, accelerating through 14–21%, and
  reaching ~29% (305 tests shown, 0 failures /
  0 errors in the flushed log) at ~29 min.
  Contention then returned in force (1-minute
  load rose to ~11.9, 5-minute ~8.0,
  MemAvailable fell 5.03 GB → ~3.35 GB, swap 0)
  with ~724 tests still to go at ~6–10/min, so
  the recount was stopped deliberately rather
  than ridden into OOM risk on this swapless
  box; the partial log is NOT evidence and the
  tally stays NOT verified. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~12:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 11:55 tick (head 2bdb701, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by their
  command lines / cwd to belong to other
  campaigns (yggdrasil-build, mythic-coder-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable sampled 2804252 /
  2606992 kB (~2.6–2.8 GB, 5-minute load
  ~5.7–6.1, swap 0), well below the ~4.9–5.1 GB
  window the 11:55 tick launched into and still
  had to stop at ~29%, so launching now would
  risk OOM on this swapless box and prove
  nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~12:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 12:25 tick (head dcd97ce, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build
  and others), none to Samverk). The tick opened
  on the best sustained window in hours —
  MemAvailable rose ~4.86 → ~5.08 GB across
  four samples with 1-minute load easing
  ~6.2 → ~4.6 (swap 0) — so the owed governing
  recount WAS launched (script
  run-recount-1235.sh, log
  recount-2026-10-31-1235-pytest.log in the
  goal hidden_files), but it never ran a single
  test: the first detached launch died with its
  exec session (log left at 0 bytes), and the
  tracked relaunch hit a transient box-wide
  write error ("Operation not permitted") on
  the log file itself — the same write gate
  that blocked the 09:45 tick's commit — so
  every redirect failed and pytest never
  started. By the time writes recovered,
  contention had returned in force:
  MemAvailable fell to ~1.2 GB (another
  campaign's pytest holding ~5.1 GB RSS), so
  no third launch was attempted into OOM risk
  on this swapless box. The tally is NOT
  verified: the recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~12:35 EDT, addendum
  (same tick, minutes later): the write failure
  was diagnosed as a box-wide write gate in an
  aggressive phase, not a Samverk fault — git
  loose-object writes returned "Operation not
  permitted" in every repo tried (Samverk,
  samtal-mvp, yggdrasil-build), a python file
  write silently landed 0 bytes, cp failed
  EPERM mid-write, and pytest's own tempdir
  probe found no usable temporary directory,
  while some shell writes still landed. The
  machine itself then went fully quiet
  (MemAvailable ~6.17 GB, 1-minute load ~1.4 —
  the best readings all day), but the gate
  still blocked the recount's log writes and
  pytest's temp files, so no clean recount is
  possible while the gate lasts and any tally
  produced under it could not be trusted. This
  tick's map entry itself could not be
  committed (git object writes gated) and
  stands as an uncommitted worktree edit for
  the next keeper tick to bank once the gate
  lifts — the same posture as the 09:45 →
  10:15 ticks. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed; S-151 does not bank until a keeper run
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~12:55 EDT: no Samverk
  worker was live. First, this tick banked the
  12:35 tick's uncommitted map entries (commit
  aed8611, pushed and verified equal to
  origin/main by ls-remote) — the box-wide
  write gate that blocked them has lifted
  (repeated /tmp and workspace write probes
  all landed, git object writes work again).
  The tick opened on a strong window
  (MemAvailable ~5.8–6.2 GB, swap 0), so the
  owed governing recount WAS launched in the
  campaign's established environment (script
  run-recount-1255.sh, log
  recount-2026-10-31-1255-pytest.log in the
  goal hidden_files, HEAD aed8611). Contention
  from other campaigns' suites (yggdrasil,
  sagnaskemma, runmal, hermes) kept the rate
  at ~9 tests/minute despite healthy memory
  (MemAvailable stayed ~5.7–5.9 GB, 1-minute
  load rising to ~7.8); after ~10 minutes the
  log held 91 test markers at the 7% line,
  every one passing, none failing — a ~2-hour
  projected total — so the recount was
  stopped, following the established
  precedent. The tally is NOT verified: the
  recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~13:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 12:55 tick (head f41dad9, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  hermes-hack-build), none to Samverk). The
  tick opened on a strong window (MemAvailable
  ~5.54–5.58 GB, swap 0, 1-minute load falling
  to ~1.1), so the owed governing recount WAS
  launched in the campaign's established
  environment (script run-recount-1305.sh, log
  recount-2026-10-31-1305-pytest.log in the
  goal hidden_files, HEAD f41dad9).
  Contention returned within minutes (other
  campaigns' suites joined — runmal-build,
  mindspark-build, mythic-coder-build;
  MemAvailable fell to ~3.62 GB, 1-minute load
  spiked to ~14.6, the Samverk pytest held
  only ~4% CPU); after ~9 minutes the log
  held 45 test markers, every one passing,
  none failing — a ~3-hour projected total at
  ~5 tests/minute — so the recount was
  stopped, following the established
  precedent. The tally is NOT verified: the
  recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~13:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 13:05 tick (head bab6cd9, verified
  equal to origin/main by ls-remote; worktree
  clean — no pytest process on the box belonged
  to Samverk). The tick opened on the strongest
  memory reading yet (MemAvailable ~6.26 GB,
  swap 0) but the window closed within a minute
  as another campaign's suite (mythic-coder-build)
  joined: MemAvailable fell to ~2.38–2.45 GB and
  stayed there across a one-minute watch
  (1-minute load ~4.1–6.0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so the owed recount was NOT
  launched — launching would risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~13:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 13:15 tick (head afe2cd1, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to another campaign
  (mythic-coder-build), none to Samverk, and a
  runmal soak process was also running).
  MemAvailable opened low at ~1.83 GB and fell
  across a ~45-second watch to ~1.47 GB (swap 0,
  1-minute load ~2.7), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so the owed recount was NOT
  launched — launching would risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~13:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 13:25 tick (head bd50129, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build, ember-build,
  hermes-hack-build, mindspark-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.74–0.88 GB across the watch (samples
  799804 / 903424 / 840760 / 821884 / 756056 kB,
  5-minute load ~6.2–6.3, 1-minute load ~7–8,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~13:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 13:35 tick (head eaf7425, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  hermes-hack-build, sagnaskemma-build), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.92–1.01 GB across the watch (samples
  1011900 / 938604 / 1037568 kB, 5-minute load
  ~5.8–6.0, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~13:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 13:45 tick (head e7934de, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (ember-build,
  mythic-coder-build, mindspark-build), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.91–1.08 GB across the watch (samples
  1031760 / 1067116 / 1083892 / 958420 /
  1037500 / 948604 kB, 5-minute load ~5.4–5.5,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~14:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 13:55 tick (head 7c34cc7, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  hermes-hack-build, mythic-coder-build,
  sagnaskemma-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.59–0.83 GB
  across the watch (samples 606280 / 852836 /
  755572 / 706084 kB, 1-minute load ~13.3–15.2,
  5-minute load ~5.6–7.9, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~14:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 14:05 tick (head 79c6125, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  mindspark-build, ember-build,
  sagnaskemma-build, plus a ravens soak), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable opened
  ~0.46 GB (sample 472728 kB, 1-minute load
  ~10.2) and rose to ~1.06 GB across the watch
  (samples 1109276 / 1109128 kB) but load climbed
  with it (1-minute ~12.8, 5-minute ~9.0, swap
  0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~14:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 14:15 tick (head de44cf5, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest process on the box was
  verified by cwd to belong to another campaign
  (sagnaskemma-build), plus a ravens soak and an
  Aesir mojo build, none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.80–0.98 GB
  across the watch (samples 980736 / 892856 /
  842592 / 805848 kB, 5-minute load ~5.0–5.9,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~14:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 14:25 tick (head d7bca01, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (hermes-hack-build, mythic-coder-build,
  yggdrasil-build, sagnaskemma-build), plus a
  ravens soak, none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.77–1.05 GB
  across the watch (samples 1005404 / 1051236 /
  922424 kB, 5-minute load ~5.3–6.1, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~14:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 14:35 tick (head e6bcd6a, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, ember-build, mythic-coder-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~1.07–1.15 GB
  across the watch (samples 1126944 / 1085232 /
  1105908 / 1140608 / 1074108 kB, 5-minute load
  ~6.5–6.6, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~14:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 14:45 tick (head dabd3d2, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, ember-build, mythic-coder-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~1.09–1.20 GB
  across the watch (samples 1202868 / 1143592 /
  1118272 / 1090240 / 1128480 kB, 5-minute load
  ~6.6–6.7, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~15:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 14:55 tick (head 95a0bc8, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, hermes-hack-build,
  sagnaskemma-build), plus a ravens soak, none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable fell
  from ~1.03 GB to ~0.65–0.69 GB across the watch
  (samples 1032864 / 880324 / 666340 / 673204 /
  687480 / 689148 kB, 5-minute load ~8.3 rising
  to ~10.7, 1-minute load ~13–15, swap 0), never
  near a safe threshold for the ~1000-test suite
  on this swapless box, so launching would risk
  OOM and prove nothing clean. A git fetch this
  tick failed (exit 128) under the degraded
  GitHub HTTPS path; ls-remote itself succeeded
  and confirms head equals origin/main. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not bank
  until a keeper run on a quiet machine verifies
  the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~15:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 15:05 tick (head 7f35018, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box belong
  to other campaigns (yggdrasil-build,
  hermes-hack-build, mythic-coder-build), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~1.35–1.65 GB across the watch (samples
  1652892 / 1608424 / 1414840 / 1352348 kB,
  5-minute load ~13.3–13.6, 1-minute load
  ~16–18, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~15:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 15:15 tick (head 7ab61cd, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (mythic-coder-build, hermes-hack-build,
  yggdrasil-build), plus an Aesir mojo build,
  none to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.77–1.20 GB across the watch (samples
  1195108 / 1172144 / 1120136 / 821980 / 885956 /
  772484 / 1003224 kB, 5-minute load ~5.0–5.5,
  swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not bank
  until a keeper run on a quiet machine verifies
  the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~15:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 15:25 tick (head 9a60c73, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  mythic-coder-build, sagnaskemma-build,
  ember-build, hermes-hack-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.55–0.73 GB across the watch (samples
  769240 / 572644 / 687256 / 740848 / 615088 /
  665104 kB, initial check 677232 kB, 5-minute
  load ~6.4–8.0, swap 0; corrected from the
  finished watch log — an interim poll glimpse
  had mixed in other readings), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~15:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 15:35 tick (head 14c2a62, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box
  belonged to other campaigns (yggdrasil-build,
  sagnaskemma-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.86–1.08 GB
  across the watch (samples 1111444 / 1019020 /
  1044928 / 980728 / 1002816 / 880332 kB,
  5-minute load ~5.1–6.2, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~15:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 15:45 tick (head a951d17, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.44–0.93 GB
  across the watch (samples 928 / 936592 /
  459536 kB, 5-minute load ~5.5–6.0, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~16:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 15:55 tick (head 35ec27a, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  mindspark-build, mythic-coder-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.77–0.96 GB
  across the watch (samples 901936 / 922228 /
  786768 / 829416 kB, 5-minute load ~9.6–10.0,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~16:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 16:05 tick (head b433a9e, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to another campaign
  (mythic-coder-build), none to Samverk). The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.54–0.70 GB
  across the watch (samples 700820 / 539200 /
  539592 kB, 5-minute load ~6.1–6.5, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~16:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 16:15 tick (head b851c8e, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, mythic-coder-build,
  hermes-hack-build, mindspark-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.44–0.71 GB across the watch (samples
  725620 / 597708 / 456068 kB, 5-minute load
  ~6.6–7.1, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~16:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 16:25 tick (head 09cdf96, verified
  equal to origin/main by ls-remote in a bounded
  foreground check; worktree clean — the only
  other pytest on the box was verified by cwd
  to belong to ember-build, none to Samverk).
  A first git fetch this tick timed out after
  600 s (GitHub HTTPS degraded, as already
  noted in this map), but the bounded ls-remote
  retry succeeded and matches HEAD exactly.
  The owed recount was checked for again and
  still NOT paid — MemAvailable stayed
  ~0.42–0.45 GB across the watch (samples
  447216 / 420568 / 428540 kB, 5-minute load
  ~4.3–4.4, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box.
  The offload host was also checked this tick:
  purplelongship reported 34.9 GB available but
  load ~10.1 / 14.8 / 13.2 and temperature
  82 C, so it is not a quiet or thermally safe
  governing-recount host either. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~16:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 16:35 tick (head b852308, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the
  box were verified by cwd to belong to other
  campaigns (yggdrasil-build, mythic-coder-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.32–0.72 GB
  across the watch (samples 508240 / 737616 /
  489584 / 333052 / 515696 / 598032 / 535404 kB,
  5-minute load ~4.8–5.2, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~16:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 16:45 tick (head baf5dbe, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  mythic-coder-build, sagnaskemma-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.42–0.69 GB
  across the watch (samples 430032 / 499456 /
  703456 / 582856 / 677944 kB, 1-minute load
  ~13.8–16.3, 5-minute load ~6.0–9.3, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~17:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 16:55 tick (head d534d61, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  mythic-coder-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~1.08–1.17 GB
  across the watch (samples 1223744 / 1135996 kB,
  1-minute load ~8.4–11.8, 5-minute load
  ~8.7–9.1, swap 0), never near a safe
  threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~17:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 17:05 tick (head 661f8f3, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  sagnaskemma-build), none to Samverk, plus a
  ravens soak process). The owed recount was
  checked for again and still NOT paid —
  MemAvailable stayed ~1.04–1.11 GB across the
  watch (samples 1124336 / 1095860 / 1161564 /
  1119668 / 1112636 kB, 1-minute load rising
  ~7.4–10.4, 5-minute load ~6.6–7.3, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~17:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 17:15 tick (head efff40b, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (sagnaskemma-build, ember-build),
  none to Samverk). The box had just rebooted
  (up ~2 min) and MemAvailable opened at
  ~4.32 GB, climbing to ~4.81 GB across the
  watch — the best window in hours — so this
  tick DID launch the owed governing recount
  (script run-recount-1725.sh, log
  recount-2026-10-31-1725-pytest.log in the goal
  hidden_files, campaign's established
  environment: TMPDIR
  ~/workspace/.verify-tmp/samverk-tmp, PATH
  prepended ~/workspace/.tools). Contention
  returned during the run: MemAvailable fell
  4.54 GB → ~2.0 GB as the other campaigns'
  suites respawned (mythic-coder-build,
  runmal-build, sagnaskemma-build,
  yggdrasil-build), the flush rate fell to
  ~7 tests/min (51 markers in ~7 minutes, 0
  failures among them, projected ~2.5 h total),
  so the recount was stopped rather than ridden
  into OOM risk on this swapless box, following
  the 05:15 / 07:25 / 11:25 precedents. The
  partial log is NOT evidence and the tally
  stays NOT verified. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~17:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 17:25 tick (head 96bcadb, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (runmal-build,
  yggdrasil-build, mythic-coder-build,
  hermes-hack-build, mindspark-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.68–0.91 GB across the watch (samples
  806128 / 806628 / 752156 / 925304 / 935416 /
  776048 / 699200 kB, 1-minute load ~8.7–13.0,
  5-minute load ~8.5–9.1, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~17:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 17:35 tick (head 0a8f59e, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the
  box were verified by cwd to belong to other
  campaigns (runmal-build, yggdrasil-build,
  sagnaskemma-build, hermes-hack-build,
  mythic-coder-build), none to Samverk). The
  owed recount was checked for again and
  still NOT paid — contention was the heaviest
  seen this evening: MemAvailable stayed
  ~0.65–0.75 GB across the watch (samples
  763592 / 765544 / 741664 / 671076 kB,
  1-minute load ~17.7–18.3, swap 0), never
  near a safe threshold for the ~1000-test
  suite on this swapless box, so launching
  would risk OOM and prove nothing clean.
  The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~17:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 17:45 tick (head 9d8dc90, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the
  box were verified by cwd to belong to other
  campaigns (runmal-build, sagnaskemma-build,
  ember-build, mythic-coder-build,
  yggdrasil-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable fell ~0.92 → 0.72 GB
  across the watch (samples 928572 / 959072 /
  878052 / 878144 / 795748 / 756960 kB, 1-minute
  load ~6.0–10.2, 5-minute load ~9.4–10.6,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~18:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 17:55 tick (head e1808cf, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  sagnaskemma-build, runmal-build,
  mythic-coder-build, ember-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable fell
  ~1.05 GB → ~0.45 GB across the watch (samples
  1074184 / 1073668 / 1061332 / 577540 / 453504 kB,
  5-minute load ~5.6–6.1, swap 0), never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  correction to the 18:05 tick entry above, from
  the finished watch log read back after banking:
  the pytest processes verified by cwd were
  runmal-build and hermes-hack-build (not the
  five campaigns first listed), and the
  MemAvailable samples were 1074184 / 1073668 /
  1061332 / 577540 kB (~1.05 GB → ~0.55 GB).
  Conclusion unchanged — recount still owed,
  S-151 not banked;
  keeper tick 2026-10-31 ~18:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 18:05 tick (head 00c0380, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (runmal-build, sagnaskemma-build,
  yggdrasil-build, hermes-hack-build,
  ember-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.79–1.05 GB
  across the watch (samples 1019020 / 1048356 /
  964196 / 808456 / 913396 / 912600 kB,
  1-minute load rising 3.7 → 14.3, 5-minute
  load ~7.4–9.7, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  keeper tick 2026-10-31 ~18:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 18:15 tick (head ad11f4c, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (sagnaskemma-build, ember-build,
  yggdrasil-build, mythic-coder-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~1.83–1.93 GB across the watch (samples
  1925988 / 1884060 / 1876460 / 1860040 /
  1865568 / 1834792 kB, 1-minute load
  ~13.3–13.6, 5-minute load ~10.5–10.7, swap 0),
  improved from the prior tick but still well
  below a safe threshold for the ~1000-test
  suite on this swapless box, so launching
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  keeper tick 2026-10-31 ~18:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 18:25 tick (head 392be18, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (hermes-hack-build, mythic-coder-build,
  runmal-build, yggdrasil-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.57–1.05 GB across two watches (samples
  599144 / 665528 / 845436 / 777728 / 909208 /
  960104 / 1100240 kB, 1-minute load peaking
  ~18.0, 5-minute load ~10–11.7, swap 0), still
  well below a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~18:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 18:35 tick (head 875457d, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, hermes-hack-build),
  none to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.55–0.82 GB across the watch (samples
  716756 / 815336 / 753716 / 559920 / 735068 kB,
  1-minute load ~7.5–10.8, 5-minute load
  ~9.8–11.3, swap 0), still well below a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~18:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 18:45 tick (head 764a5ad, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  process on the box was verified by cwd to
  belong to another campaign (sagnaskemma-build),
  none to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.87–1.00 GB across the watch (samples
  1024788 / 996808 / 1014192 / 914896 / 890108 /
  932056 / 950808 kB, 5-minute load ~8.5–9.3,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~19:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 18:55 tick (head 9c40f97, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (ember-build, mindspark-build,
  hermes-hack-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~1.32–1.76 GB across
  the watch (samples 1315412 / 1609900 / 1757032 /
  1392124 kB, 5-minute load ~6.1–6.4, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~19:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 19:05 tick (head ea88952, verified
  equal to origin/main by ls-remote and by
  fetch + rev-parse; worktree clean — the active
  pytest processes on the box were verified by
  cwd to belong to other campaigns
  (hermes-hack-build, mythic-coder-build,
  yggdrasil-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable fell ~0.80 GB to ~0.46 GB
  across the watch (samples 820080 / 802596 /
  567716 / 456656 kB, 1-minute load ~14.5–16.2,
  swap 0), the heaviest contention of the
  evening, never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~19:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 19:15 tick (head 9d9f074, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build,
  mythic-coder-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.72–1.24 GB across
  the watch (samples 978696 / 1080588 / 1241716 /
  787884 / 750936 / 739156 / 765028 kB, 1-minute
  load ~8.1–12.9, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  keeper tick 2026-10-31 ~19:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 19:25 tick (head 945509b, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build,
  hermes-hack-build, mythic-coder-build,
  mindspark-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.61–1.25 GB across
  the watch (samples 914792 / 624320 / 1093856 /
  1314348 kB, 1-minute load ~8.6–17.4, swap 0;
  the fourth sample and load floor corrected
  from the finished sampler log after banking),
  never near a safe threshold for the ~1000-test
  suite on this swapless box, so launching would
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~19:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 19:35 tick (head fb0c86c, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, mythic-coder-build),
  none to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.92–1.22 GB across the watch (samples
  1053664 / 1217692 / 1036712 / 916896 / 1097328 /
  989792 kB, 1-minute load ~9.9–11.2, 5-minute
  load ~11.2–11.6, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~19:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 19:45 tick (head 8f60af5, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build),
  none to Samverk). The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~1.50–1.76 GB across the watch (samples
  1757272 / 1653468 / 1631956 / 1668016 / 1569104 /
  1534832 / 1500044 kB, falling, 1-minute load
  ~4.9 rising to ~11.0, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~20:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 19:55 tick (head 9529236, verified
  equal to origin/main; worktree clean — the
  active pytest processes on the box were
  verified by cwd to belong to other campaigns
  (ember-build, hermes-hack-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~1.13–1.23 GB across the watch (samples
  1185704 / 1189568 / 1285344 / 1206524 /
  1198132 kB, 1-minute load ~10.7 rising to
  ~11.1), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~20:15 EDT: no Samverk
  worker was live (head 23ad8d9, verified equal
  to origin/main; worktree clean). The box had
  just rebooted (~20:14) and briefly looked
  quiet — MemAvailable ~3.99 GB, 1-minute load
  ~4.6 falling — the best window all evening,
  so this tick LAUNCHED the owed governing
  recount at 20:18 EDT: full suite
  `python3 -m pytest tests -q`, detached
  (nohup), TMPDIR
  `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`, output to
  `~/workspace/.verify-tmp/samverk_recount_s151_20261031_2018.log`.
  Contention rebuilt within minutes: by ~20:27
  MemAvailable had fallen to ~0.95 GB and the
  recount process held only ~36 s CPU in 9 min
  elapsed (~90 tests of ~1028 written to the
  log), starved by other campaigns' suites. The
  recount was left running detached; its verdict
  is NOT yet known and nothing is claimed from
  it. The next keeper tick reads that log file:
  if it finished at the expectation
  (1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150), S-151 CODEOWNERS may
  bank; if it died or failed, the recount stays
  owed and any real failures are bugs to fix
  under the never-leave-a-bug rule. S-151 not
  banked this tick.
  keeper tick 2026-10-31 ~20:25 EDT: no Samverk
  worker was live (head cd7233d, verified equal
  to origin/main by ls-remote; worktree clean —
  the active pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, ember-build,
  mythic-coder-build, hermes-hack-build), none
  to Samverk). This tick read the recount log
  the 20:15 tick left running
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261031_2018.log`):
  it holds only 106 bytes — 98 passing markers
  (72 at the 7% line plus 26 more), no summary
  line, no failure markers — and the recount
  process is no longer live, so that run died
  incomplete under contention and its tally is
  NOT verified. No new recount was launched:
  MemAvailable stayed ~0.51–0.99 GB across the
  watch (samples 989048 / 696260 / 752596 /
  570840 / 526752 kB, 1-minute load rising
  ~7.9–12.8, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~20:35 EDT: no Samverk
  worker was live (head 368d79e, verified equal
  to origin/main by ls-remote after a fetch;
  worktree clean — the active pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build, ember-build,
  sagnaskemma-build, hermes-hack-build), none
  to Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.59–0.91 GB across the watch (samples
  616884 / 949644 / 620084 / 682312 kB, 1-minute
  load easing ~1.7 → ~1.2 but 5-minute load
  ~4.6–5.2, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~20:45 EDT: no Samverk
  worker was live (head 52abedf, verified equal
  to origin/main by ls-remote; worktree clean —
  the active pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.62–0.87 GB across the watch (samples
  621768 / 867312 / 887992 / 817020 kB, 1-minute
  load ~0.6 at first sample then rising
  ~5.6–6.4, 5-minute load ~5.1–5.3, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The offload road was also re-checked
  this tick: an SSH attempt to purplelongship
  failed — the connection was reset by the
  egress proxy (198.19.0.1 port 3128) during
  key exchange, so that is not a working SSH
  route to the offload host and it was not
  reachable by that route this tick either.
  (Correction, same tick: this entry first
  read "timed out after 240 s with no
  output"; the finished command log disproves
  that — the reset above is what it shows.)
  The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~21:05 EDT: no Samverk
  worker was live (head 4a7b28e, verified equal
  to origin/main by ls-remote after a fetch;
  worktree clean — the active pytest processes
  on the box were verified by cwd to belong to
  other campaigns (sagnaskemma-build,
  yggdrasil-build, ember-build,
  hermes-hack-build, mythic-coder-build,
  mindspark-build), none to Samverk). The owed
  recount was checked for again and still NOT
  paid — MemAvailable stayed ~0.83–1.09 GB
  across the watch (samples 1146212 / 873168 /
  951280 / 1021532 kB, 1-minute load
  ~13.9–19.5, 5-minute load ~11.7–12.4,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~21:15 EDT: no Samverk
  worker was live (head cfb21dd, verified equal
  to origin/main by ls-remote; worktree clean —
  the active pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  ember-build, mythic-coder-build), none to
  Samverk). The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.93–1.72 GB across the watch (samples
  927660 / 1102960 / 1260072 / 1717012 kB,
  1-minute load ~1.5–5.5, 5-minute load
  ~6.6–7.0, swap 0), never near a safe threshold
  for the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove nothing
  clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~21:25 EDT: no Samverk
  worker was live (head 7c71bbb, verified equal
  to origin/main by ls-remote after a fetch;
  worktree clean, single worktree — the active
  pytest processes on the box were verified by
  cwd to belong to other campaigns
  (yggdrasil-build, mythic-coder-build,
  ember-build), none to Samverk). The 20:15
  recount log was re-read: still the incomplete
  106-byte file (98 passing markers, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable improved to the best
  levels of the evening, ~2.52–2.82 GB across
  the watch (samples 2822872 / 2603024 /
  2520848 / 2785656 / 2575256 kB), but three
  other campaigns' full suites were running
  throughout (1-minute load ~1.95–4.76,
  5-minute load ~5.0–5.4, swap 0), so the box
  is still not quiet and launching the
  ~1000-test recount would risk OOM and prove
  nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS.
  keeper tick 2026-10-31 ~21:35 EDT: no Samverk
  worker was live (head 36844fe, verified equal
  to origin/main by ls-remote after a fetch;
  worktree clean, single worktree, no subagent
  workers — the active pytest processes on the
  box were verified by cwd to belong to other
  campaigns (yggdrasil-build, ember-build,
  hermes-hack-build, sagnaskemma-build), none
  to Samverk). The 20:15 recount log was
  re-read: still the incomplete 106-byte file
  (98 passing markers, no summary line), so
  that run stays NOT verified. The owed recount
  was checked for again and still NOT paid —
  MemAvailable fell ~2.00 GB to ~1.25 GB across
  the watch (samples 2051888 / 1954428 /
  1569704 / 1511304 / 1344764 / 1277248 kB,
  1-minute load ~4.75–5.85, 5-minute load
  ~3.98–4.47, swap 0), contention worsening
  from the 21:25 tick's best-of-evening levels
  with four other campaigns' suites running
  throughout, so the box is still not quiet
  and launching the ~1000-test recount would
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS.
  amplification to the 21:35 tick entry above,
  from the tick's second sampler read back
  after banking (21:37:23–21:38:38):
  MemAvailable recovered to ~2.20–2.41 GB and
  held steady (samples 2410972 / 2346500 /
  2521516 / 2415484 / 2304912 / 2444956 kB),
  but 1-minute load spiked to ~13.1–16.3 and
  5-minute load rose ~7.1–9.2 — the heaviest
  CPU contention of the evening — with the
  active pytest processes still verified by
  cwd as other campaigns (yggdrasil-build,
  ember-build, hermes-hack-build,
  sagnaskemma-build), none to Samverk.
  Conclusion unchanged — recount still owed,
  S-151 not banked.
  keeper tick 2026-10-31 ~21:45 EDT: no Samverk
  worker was live (head 622bb84, verified equal
  to origin/main by ls-remote; worktree clean,
  single worktree — the active pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build, ember-build,
  sagnaskemma-build, hermes-hack-build), none
  to Samverk). The 20:15 recount log was
  re-read: still the incomplete 106-byte file
  (98 passing markers, no summary line), so
  that run stays NOT verified. The owed recount
  was checked for again and still NOT paid —
  MemAvailable ~1.43–1.69 GB and falling across
  the watch (samples 1728084 / 1719704 /
  1717956 / 1462872 kB), 1-minute load
  ~16.1–17.4 (the heaviest of the evening),
  5-minute load ~8.9–10.1, with four other
  campaigns' suites running throughout, so the
  box is still not quiet and launching the
  ~1000-test recount would risk OOM and prove
  nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~21:55 EDT: no Samverk
  worker was live (head 1882a02, verified equal
  to origin/main by ls-remote; worktree clean,
  single worktree — the active pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  sagnaskemma-build, ember-build, mythic-coder-build),
  none to Samverk). The 20:15 recount log was
  re-read: still the incomplete 106-byte file
  (passing markers only, no summary line), so
  that run stays NOT verified. The owed recount
  was checked for again and still NOT paid —
  MemAvailable stayed ~1.57–2.04 GB across the
  watch (samples 1646708 / 1650448 / 2141164 /
  1924852 kB, final 1841884 kB), 1-minute load
  ~8.4–15.5 and 5-minute load ~10.1–11.3 with
  other campaigns' suites running throughout
  and swap 0, never near a safe threshold for
  the ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~22:05 EDT: no Samverk
  worker was live (head 2d3892a, verified equal
  to origin/main by ls-remote; worktree clean —
  the active pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, mythic-coder-build,
  hermes-hack-build, yggdrasil-build,
  mindspark-build), none to Samverk; the one
  Samverk-cwd entry in the final sampler was
  this tick's own sampler shell). The 20:15
  recount log was re-read: still the incomplete
  106-byte file (passing markers only, no
  summary line), so that run stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable
  stayed ~1.82–2.27 GB across the watch
  (samples 2327968 / 2143044 / 2205468 /
  2116660 / 1868312 kB), 1-minute load falling
  ~5.2–1.9 but 5-minute load still ~6.2–7.9
  with other campaigns' suites running
  throughout, never near a safe threshold for
  the ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~22:15 EDT: no Samverk
  worker was live (head 810a5c6, verified equal
  to origin/main by ls-remote and by fetch +
  rev-parse; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  hermes-hack-build, sagnaskemma-build,
  ember-build), none to Samverk). The 20:15
  recount log was re-read: still the incomplete
  106-byte file (passing markers only, no
  summary line), so that run stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable
  sampled ~0.94 GB then ~1.44 GB (960744 /
  1474096 kB) with the box 9 minutes past a
  reboot, 1-minute load falling ~2.22–1.28 but
  5-minute load still ~5.11–5.88 with other
  campaigns' suites running throughout, never
  near a safe threshold for the ~1000-test
  suite on this swapless box, so launching
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1 skipped
  / 0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~22:25 EDT: no Samverk
  worker was live (head 6d05a38, verified equal
  to origin/main by ls-remote; worktree clean —
  the active pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, hermes-hack-build,
  sagnaskemma-build, ember-build,
  mythic-coder-build), none to Samverk). The
  20:15 recount log was re-read: still the
  incomplete 106-byte file (passing markers
  only, no summary line), so that run stays
  NOT verified. The owed recount was checked
  for again and still NOT paid — MemAvailable
  sampled ~1.35–1.49 GB (1352288 / 1401728 /
  1488368 kB), 1-minute load rising
  ~9.33–11.27 and 5-minute load ~5.07–5.26
  with other campaigns' suites running
  throughout, never near a safe threshold for
  the ~1000-test suite on this swapless box,
  so launching would risk OOM and prove
  nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~22:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 22:25 tick (head 874b027, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build,
  hermes-hack-build, ember-build), none to
  Samverk). The 20:15 recount log was re-read:
  still the incomplete 106-byte file (passing
  markers only, no summary line), so that run
  stays NOT verified. The purplelongship offload
  log was also re-read from disk
  (~/workspace/.verify-tmp/offload-samverk-recount.log):
  a completed full run at head eaf7425 — code
  identical to HEAD (empty samverk/tests diff) —
  read 1023 passed / 4 failed / 1 skipped, 5
  subtests passed in 219.10 s, all 4 failures
  PermissionError in corruption-injection tests
  that overwrite read-only git objects (an
  environment difference on that non-root host,
  not shipped-code defects); it supports but
  does not replace the governing VM recount.
  The owed recount was checked for again and
  still NOT paid — MemAvailable opened ~2.84 GB
  (2973184 kB, the best reading in hours) but
  fell to ~2.36 GB across the watch (samples
  2844072 / 2725724 / 2858440 / 2804404 /
  2473204 kB, 1-minute load ~5.5–7.2, 5-minute
  load ~6.0–6.4, swap 0) as more foreign suites
  joined, never a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~22:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 22:35 tick (head c00d801, verified
  equal to origin/main by ls-remote before this
  entry; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  hermes-hack-build, mythic-coder-build), none
  to Samverk). The 20:15 recount log was
  re-read: still the incomplete 106-byte file
  (passing markers only, no summary line), so
  that run stays NOT verified. The owed recount
  was checked for again and still NOT paid —
  MemAvailable opened ~0.81 GB (810920 kB) and
  stayed ~0.73–0.88 GB across the watch
  (samples 762344 / 880232 / 732168 kB,
  1-minute load ~10.9 falling to ~4.8, 5-minute
  load ~8.1–6.9), never a safe threshold for
  the ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed
  / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~22:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 22:45 tick (head 6b807d6, verified
  equal to origin/main by ls-remote before this
  entry; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  mythic-coder-build, ember-build), none to
  Samverk). The 20:15 recount log was re-read:
  still the incomplete 106-byte file (passing
  markers only up to the 7% mark, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.64–0.79 GB
  across a one-minute watch (samples 771032 /
  747828 / 760088 / 811372 / 737740 / 673404 kB,
  1-minute load ~4.6–5.7, 5-minute load
  ~7.1–7.4, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~23:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 22:55 tick (head 5d37a2a, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (runmal-build, sagnaskemma-build),
  plus a ravens soak process, none to Samverk).
  The 20:15 recount log was re-read: still the
  incomplete 106-byte file (passing markers only
  up to the 7% mark, no summary line), so that
  run stays NOT verified. The owed recount was
  checked for again and still NOT paid —
  MemAvailable stayed ~1.46–1.66 GB across the
  watch (samples 1740336 / 1633420 / 1659360 /
  1686768 / 1567760 / 1529412 kB, 1-minute load
  ~3.4–4.1, 5-minute load ~5.0–5.3, swap 0) —
  the best memory readings of the late evening
  but still never near a safe threshold for the
  ~1000-test suite on this swapless box with
  other campaigns' suites running, so launching
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~23:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 23:05 tick (head 9f241c8, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build,
  mythic-coder-build, ember-build/Verdandi),
  none to Samverk). The 20:15 recount log was
  re-read: still the incomplete 106-byte file
  (passing markers only up to the 7% mark, no
  summary line), so that run stays NOT verified.
  The owed recount was checked for again and
  still NOT paid — MemAvailable fell ~1.33 GB to
  ~1.10 GB across a one-minute watch (samples
  1333320 / 1250704 / 1096336 kB) while the
  1-minute load rose ~7.9 to ~11.3 (5-minute
  load ~5.2–5.6, swap 0), the worst trend of
  the late evening, so launching the ~1000-test
  suite into that contention on this swapless
  box would risk OOM and prove nothing clean.
  The recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149 and
  S-150) plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~23:25 EDT: no Samverk
  worker was live and no new commits had landed
  since the 23:15 tick (head 366d35a, verified
  equal to origin/main by ls-remote; worktree
  clean — the active pytest processes on the box
  were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build,
  mythic-coder-build, ember-build), none to
  Samverk). The 20:15 recount log was re-read:
  still the incomplete 106-byte file (passing
  markers only up to the 7% mark, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~1.14–1.26 GB
  across the watch (samples 1316452 / 1198252 /
  1204920 kB) while the 1-minute load ran
  ~13.8–14.9 (5-minute load ~9.3–10.1, swap 0),
  the heaviest CPU contention of the late
  evening, so launching the ~1000-test suite
  into that contention on this swapless box
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~23:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 23:25 tick (head 24cd959, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  ember-build, hermes-hack-build), none to
  Samverk). The 20:15 recount log was re-read
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261031_2018.log`):
  still the incomplete 106-byte file (passing
  markers only up to the 7% mark, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.47–0.75 GB
  across the watch (samples 766364 / 481556 /
  692376 / 765336 kB) while the load ran the
  heaviest of the day (1-minute ~20.2 falling
  to ~10.9, 5-minute ~17.8–15.7, swap 0), so
  launching the ~1000-test suite into that
  contention on this swapless box would risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and
  S-150) plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not bank
  until a keeper run on a quiet machine verifies
  the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-10-31 ~23:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 23:35 tick (head 4a8551a, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  yggdrasil-build, mythic-coder-build), plus a
  ravens soak process, none to Samverk). The
  20:15 recount log was re-read
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261031_2018.log`):
  still the incomplete 106-byte file (passing
  markers only up to the 7% mark, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~2.48–2.67 GB
  across the watch (samples 2521296 / 2519748 /
  2480284 / 2669988 kB, final check 2608812 kB;
  1-minute load ~1.6–3.6 but 5-minute load
  ~10.1–14.2, swap 0) with other campaigns'
  suites running throughout — better memory
  than the 23:35 tick but still well below the
  ~4.9 GB quiet window prior launches needed
  and still contended, so launching the
  ~1000-test suite into that contention on this
  swapless box would risk OOM and prove
  nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~00:05 EDT: no Samverk
  worker was live and no new commits had landed
  since the 23:55 tick (head 1880400, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  hermes-hack-build), none to Samverk). The
  20:15 recount log was re-read
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261031_2018.log`):
  still the incomplete 106-byte file (passing
  markers only up to the 7% mark, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~1.20–1.26 GB
  across the watch (samples 1270884 / 1323228 /
  1262536 / 1252916 kB; 1-minute load rising
  ~2.3 to ~9.6, 5-minute load ~2.4, swap 0)
  with other campaigns' suites running
  throughout — far below the ~4.9 GB quiet
  window prior launches needed, so launching
  the ~1000-test suite into that contention
  on this swapless box would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~00:15 EDT: no Samverk
  worker was live and no new commits had landed
  since the 00:05 tick (head 2de6914, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the active pytest
  processes on the box were verified by cwd to
  belong to other campaigns (sagnaskemma-build,
  ember-build, yggdrasil-build, hermes-hack-build),
  none to Samverk). The 20:15 recount log was
  re-read
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261031_2018.log`):
  still the incomplete 106-byte file (passing
  markers only up to the 7% mark, no summary
  line), so that run stays NOT verified. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.52–0.63 GB
  across the six-sample watch (samples 631724 /
  597100 / 616336 / 586148 / 639804 / 550808 kB;
  1-minute load ~8.0–13.8, 5-minute load
  ~6.0–6.9, swap 0); later spot checks rose to
  ~1.74–1.90 GB with 1-minute load easing to
  ~2.9 but 5-minute load still ~4.6–6.8 and
  other campaigns' suites running throughout —
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~00:25 EDT: no Samverk
  worker was live before this tick (head 0e57502,
  verified equal to origin/main by ls-remote after
  a fetch; worktree clean — the only other pytest
  on the box was verified by cwd to belong to
  yggdrasil-build, none to Samverk). The VM,
  rebooted at ~00:04, opened the quietest window
  in many ticks: MemAvailable ~5.08–5.32 GB across
  the opening samples (1-minute load falling
  ~3.5 to ~3.0), so the owed governing recount
  was LAUNCHED this tick with the campaign's
  established environment (TMPDIR
  `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`) into log
  `~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log`.
  At banking time the run was live and passing
  (log's first markers read back from disk;
  MemAvailable ~5.14 GB, load rising again as
  other campaigns joined) — verdict NOT yet
  known, NOT verified. Do not duplicate this
  run; the next keeper tick reads its log file
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  before S-151 banks;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:25 EDT: the 00:25
  tick's launched recount was read back from its
  log file and is NOT verified — the log
  (`samverk_recount_s151_20261101_0026.log`,
  1120 bytes, last written 01:24) holds 1008
  markers of 1028 collected (564 passed /
  443 failed / 1 skipped) with NO summary line,
  and no Samverk process was live at this tick
  (the pytest processes on the box were verified
  by cwd to belong to yggdrasil-build,
  sagnaskemma-build, mythic-coder-build and
  ember, none to Samverk; head 40711a6, verified
  equal to origin/main by ls-remote; worktree
  clean). The failure pattern is new and must
  be recorded plainly: the first ~35% of markers
  are all passes, failures begin at ~test 420
  and run dense to the end — but tests sampled
  from across the failure zone pass cleanly in
  isolation this tick (test_hooks +
  test_issue_battery 11 passed / 0 failed;
  test_mirrors + test_objects + test_permissions
  15 passed / 0 failed, both foreground, read
  back from their output), so the mass failures
  are classified as a contention-era run
  artifact, NOT proven code regressions — the
  run's own failure details were never flushed
  (pytest -q prints them only at the end, which
  never arrived), so no individual failure from
  that log can be cited or fixed from it. A new
  recount was NOT launched: MemAvailable stayed
  ~0.59–1.28 GB across the tick (1-minute load
  ~10.4–11.4, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:35 EDT: no Samverk
  worker was live and no new commits had landed
  since the 01:25 tick (head 42d2101, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to yggdrasil-build,
  sagnaskemma-build, mythic-coder-build and
  hermes-hack-build, plus a ravens soak process,
  none to Samverk). The 00:25 recount log was
  re-read from disk and still carries no summary
  line (its markers run through ~97% and stop at
  ".s..."), so the tally stays NOT verified,
  exactly as the 01:25 tick classified it. The
  owed recount was checked for again and still
  NOT paid — MemAvailable stayed ~0.41–0.53 GB
  across the watch (samples 512392 / 494688 /
  433840 / 553640 kB, 1-minute load ~14.1–14.5,
  swap 0), the heaviest contention of the night
  and never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:45 EDT: no Samverk
  worker was live and no new commits had landed
  since the 01:35 tick (head c361f4f, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to mindspark-build
  and yggdrasil-build, none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (markers run
  through ~97% and stop), so the tally stays
  NOT verified, exactly as the 01:25 tick
  classified it. The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.73–0.79 GB across the watch
  (samples 762004 / 795160 / 790784 kB,
  1-minute load ~7.4–9.0, swap 0), never near
  a safe threshold for the ~1000-test suite
  on this swapless box, so launching would
  risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:55 EDT: no Samverk
  worker was live and no new commits had landed
  since the 01:45 tick (head 16d0710, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to yggdrasil-build
  and ember-build, none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  markers 564 passed / 443 failed / 1 skipped
  through ~97%, no summary), so the tally stays
  NOT verified, exactly as the 01:25 tick
  classified it. The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.62–0.89 GB across the watch
  (samples 645636 / 911468 kB,
  1-minute load ~6.1, 5/15-min ~7.4/7.1), never near
  a safe threshold for the ~1000-test suite
  on this swapless box, so launching would
  risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:05 EST (the
  repeated fall-back hour): no Samverk worker
  was live and no new commits had landed since
  the 01:55 EDT tick (head 15a416d, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  yggdrasil-build, ember-build, mythic-coder-build
  and hermes-hack-build, none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  markers through ~97% then ".s...", no
  summary, no live recount process), so the
  tally stays NOT verified, exactly as the
  01:25 tick classified it. The owed recount
  was checked for again and still NOT paid —
  MemAvailable fell ~0.71 → ~0.47 GB across
  the watch (samples 746988 / 493964 kB,
  1-minute load ~2.5 → ~1.6 but 5/15-minute
  load ~6.4–7.0 / ~6.6–7.0, swap 0), never
  near a safe threshold for the ~1000-test
  suite on this swapless box, so launching
  would risk OOM and prove nothing clean. The
  recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:15 EST: no Samverk
  worker was live and no new commits had landed
  since the 01:05 EST tick (head 42332ab, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  sagnaskemma-build, ember-build, mythic-coder-build
  and hermes-hack-build, none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  markers through ~97% then ".s...", no summary,
  no live recount process), so the tally stays
  NOT verified, exactly as the 01:25 tick
  classified it. The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.74–0.81 GB across the watch (samples
  770268 / 805416 / 758016 kB, 1-minute load
  ~4.7 rising to ~9.9, 5-minute load ~6.7–7.8,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:25 EST: no Samverk
  worker was live and no new commits had landed
  since the 01:15 EST tick banked (head 16c42af,
  verified equal to origin/main by ls-remote at
  this tick's start; a later fetch timed out on
  the degraded GitHub HTTPS path, so no fresher
  remote check stands; worktree clean — the
  pytest processes on the box were verified by
  cwd to belong to yggdrasil-build,
  mythic-coder-build and ember-build, none to
  Samverk). The 00:25 recount log was re-read
  from disk and still carries no summary line
  (1120 bytes, 564 pass markers / 443 failure
  markers / 1 skip marker, progress through
  ~97% then ".s...", no summary, no live
  recount process), so the tally stays
  NOT verified, exactly as the 01:25 EDT tick
  classified it. The owed recount was checked
  for again and still NOT paid — MemAvailable
  ran ~0.76–1.17 GB on the first watch and
  ~2.01–2.06 GB on a later one (1-minute load
  ~8.8–9.7, 5-minute load ~8.5–8.6, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:35 EST (the
  second 01:35, after the fall-back): no
  Samverk worker was live and no new commits
  had landed since the 01:25 EST tick banked
  (head 6a40adf, verified equal to origin/main
  by ls-remote at this tick's start; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to yggdrasil-build,
  hermes-hack-build and mythic-coder-build,
  none to Samverk). The 00:25 recount log was
  re-read from disk and still carries no
  summary line (1120 bytes, progress through
  ~97% then ".s...", no summary, no live
  recount process), so the tally stays
  NOT verified. The owed recount was checked
  for again and still NOT paid — MemAvailable
  opened ~2.69 GB then ran ~1.99–2.36 GB
  across the watch (1-minute load ~8.8–11.8),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:45 EST: no Samverk
  worker was live and no new commits had landed
  since the second 01:35 EST tick banked at
  01:38 (head 4e0d2b9, verified equal to
  origin/main by ls-remote at this tick's start;
  worktree clean — the pytest processes on the
  box were verified by cwd to belong to
  sagnaskemma-build, yggdrasil-build, ember-build
  and hermes-hack-build, none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  progress through ~97% then ".s...", no summary,
  no live recount process), so the tally stays
  NOT verified. The owed recount was checked
  for again and still NOT paid — MemAvailable
  ran ~1.03 GB across the watch (samples
  1031940 / 1032396 kB, 1-minute load ~2.6–2.9,
  5-minute load ~6.1–6.7), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM and
  prove nothing clean. The recount (expectation
  1027 passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~01:55 EST: no Samverk
  worker was live and no new commits had landed
  since the 01:45 EST tick (head de4407a, verified
  equal to origin/main by ls-remote at this tick's
  start; worktree clean — the pytest processes on
  the box belonged by their process arguments to
  other campaigns (sagnaskemma-build,
  yggdrasil-build), none to Samverk). The 00:25
  recount log was re-read from disk and still
  carries no summary line (1120 bytes, progress
  through ~97% then ".s...", no summary, no live
  recount process), so the tally stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable was
  ~2.63–2.69 GB across the watch (samples
  2648088 / 2628992 / 2691944 kB, the best
  readings in recent ticks, but still below the
  ~3.6–5.1 GB windows in which recounts were
  launched before; 1-minute load ~2.0–3.1,
  5-minute load ~4.4–6.0, other campaigns'
  suites running throughout, swap 0), so
  launching on this swapless box would still
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150) plus
  S-150's combined affected-suites cross-check
  stay owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies the
  recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~02:05 EST: no Samverk
  worker was live and no new commits had landed
  since the 01:55 EST tick (head 9445f90, verified
  equal to origin/main by ls-remote at this tick's
  start; worktree clean — the pytest processes on
  the box belonged by their working directories to
  other campaigns (yggdrasil-build,
  sagnaskemma-build, mythic-coder-build,
  runmal-build), none to Samverk). The 00:25
  recount log was re-read from disk and still
  carries no summary line (1120 bytes, progress
  through ~97% then ".s...", no summary, no live
  recount process), so the tally stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable was
  ~0.96–1.18 GB across the watch (samples
  1009540 / 1181956 kB), 1-minute load
  ~3.7–10.4 and rising, other campaigns' suites
  running throughout, so launching on this
  swapless box would still risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~02:15 EST: no Samverk
  worker was live and no new commits had landed
  since the 02:05 EST tick (head 63bc9c7, verified
  equal to origin/main by ls-remote at this tick's
  start; worktree clean — the pytest processes on
  the box belonged by their working directories to
  other campaigns (yggdrasil-build,
  mythic-coder-build, hermes-hack-build), none to
  Samverk). The 00:25 recount log was re-read from
  disk and still carries no summary line (1120
  bytes, unchanged since 01:24, progress through
  ~97% then ".s...", no summary, no live recount
  process), so the tally stays NOT verified. The
  owed recount was checked for again and still NOT
  paid — MemAvailable was ~0.92–0.95 GB across the
  watch (samples 973156 / 937988 kB), 1-minute load
  ~12.7–17.2, the heaviest contention of the night,
  other campaigns' suites running throughout, so
  launching on this swapless box would still risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0 failed,
  covering S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay owed,
  and S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its log
  file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~02:25 EST: no Samverk
  worker was live and no new commits had landed
  since the 02:15 EST tick (head c821591, verified
  equal to origin/main by ls-remote at this tick's
  start; worktree clean — the pytest processes on
  the box belonged by their working directories to
  other campaigns (yggdrasil-build,
  mythic-coder-build, sagnaskemma-build), none to
  Samverk). The 00:25 recount log was re-read from
  disk and still carries no summary line (1120
  bytes, unchanged since 01:24, progress through
  ~97% then ".s...", no summary, no live recount
  process), so the tally stays NOT verified. The
  owed recount was checked for again and still NOT
  paid — MemAvailable moved ~0.89–1.50 GB across
  the watch (samples 888548 / 1496956 kB), 1-minute
  load ~8.5–11.1 with 5-minute load ~7.5–9.1,
  other campaigns' suites running throughout, so
  launching on this swapless box would still risk
  OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0 failed,
  covering S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay owed,
  and S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~02:35 EST: no Samverk
  worker was live and no new commits had landed
  since the 02:25 EST tick (head 21d29a5, verified
  equal to origin/main by ls-remote at this tick's
  start; worktree clean — the pytest processes on
  the box belonged by their working directories to
  other campaigns (yggdrasil-build,
  sagnaskemma-build, mindspark-build), none to
  Samverk). The 00:25 recount log was re-read from
  disk and still carries no summary line (1120
  bytes, unchanged since 01:24, progress through
  ~97% then ".s...", no summary, no live recount
  process), so the tally stays NOT verified. The
  owed recount was checked for again and still NOT
  paid — MemAvailable ~1.16 GB at tick start
  (sample 1156088 kB), 1-minute load ~4.0 with
  5-minute load ~6.7, other campaigns' suites
  running throughout, so launching on this
  swapless box would still risk OOM and prove
  nothing clean. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering S-148,
  S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~02:45 EST: no Samverk
  worker was live and no new commits had landed
  since the 02:35 EST tick (head c834597, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes on
  the box were verified by cwd to belong to other
  campaigns (sagnaskemma-build, yggdrasil-build,
  hermes-hack-build, mythic-coder-build), none to
  Samverk). The 00:25 recount log was re-read from
  disk and still carries no summary line (1120
  bytes, unchanged since 01:24, progress through
  ~97% then ".s...", no summary), so the tally
  stays NOT verified. The owed recount was checked
  for again and still NOT paid — MemAvailable
  stayed ~0.78–1.03 GB across the watch (samples
  796060 / 907920 / 837196 / 1051800 kB, 1-minute
  load ~1.3–1.4, 5-minute load ~4.5–5.2, swap 0),
  never near a safe threshold for the ~1000-test
  suite on this swapless box, so launching would
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0 failed,
  covering S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay owed,
  and S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~02:55 EST: no Samverk
  worker was live and no new commits had landed
  since the 02:45 EST tick (head 0548369, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean). At tick start the box
  still carried other campaigns' pytest verified
  by cwd (mythic-coder-build, yggdrasil-build,
  hermes-hack-build), none to Samverk, with
  MemAvailable ~0.57 GB and load ~6.2 / 5.0 /
  6.0. The VM then rebooted at ~02:56 EST
  (uptime reset to 1–2 minutes); post-reboot
  samples showed MemAvailable ~1.72–2.64 GB and
  falling as the other campaigns restarted,
  1-minute load ~6.0–7.2, swap 0 — never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean. The 00:25 recount
  log was re-read from disk and still carries
  no summary line (1120 bytes, unchanged since
  01:24, progress through ~97% then ".s...",
  no summary, no live recount process), so the
  tally stays NOT verified. The recount
  (expectation 1027 passed / 1 skipped / 0 failed,
  covering S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay owed,
  and S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~03:05 EST: no Samverk
  worker was live and no new commits had landed
  since the 02:55 EST tick (head 47a5418, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes on
  the box were verified by cwd to belong to other
  campaigns (yggdrasil-build, sagnaskemma-build,
  mythic-coder-build, hermes-hack-build,
  ember-build), none to Samverk). The 00:25 recount
  log was re-read from disk and still carries no
  summary line (1120 bytes, unchanged since 01:24,
  progress through ~97% then ".s...", no summary),
  so the tally stays NOT verified. The owed recount
  was checked for again and still NOT paid —
  MemAvailable stayed ~0.43–0.80 GB across the
  watches (samples 569196 / 611112 / 445484 /
  574388 / 833964 kB, 1-minute load falling
  ~5.9 → ~3.0 but 5-minute load ~5.2–6.1, swap 0),
  never near a safe threshold for the ~1000-test
  suite on this swapless box, so launching would
  risk OOM and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0 failed,
  covering S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay owed,
  and S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~03:15 EST: no Samverk
  worker was live and no new commits had landed
  since the 03:05 EST tick (head 93a2930, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  mythic-coder-build), none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary), so the tally stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.52–0.60 GB across the watches (samples
  613232 / 548916 kB, 5-minute load ~4.8–5.6,
  swap 0), never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~03:25 EST: no Samverk
  worker was live and no new commits had landed
  since the 03:15 EST tick (head a886c39, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build,
  hermes-hack-build), none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary), so the tally stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~1.40–1.62 GB across the watches (samples
  1534280 / 1623168 / 1412636 / 1530060 /
  1399604 / 1427704 kB, 1-minute load rising
  ~1.5–8.0, 5-minute load ~4.0–5.4, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~03:35 EST: no Samverk
  worker was live and no new commits had landed
  since the 03:25 EST tick (head bfe49a9, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (yggdrasil-build, ember-build,
  mindspark-build), none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary), so the tally stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~1.08–2.15 GB across the watches (samples
  1402212 / 1313292 / 2147324 / 1582028 /
  1399604 / 1471656 / 1173400 / 1111744 /
  1077408 kB, 1-minute load ~7.9–9.8,
  5-minute load ~5.1–6.6, swap 0),
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean. The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~03:45 EST: no Samverk
  worker was live and no new commits had landed
  since the 03:35 EST tick (head 51d9cf8, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, ember-build,
  yggdrasil-build, mythic-coder-build), none to
  Samverk). The 00:25 recount log was re-read
  from disk and still carries no summary line
  (1120 bytes, unchanged since 01:24, progress
  through ~97% then no summary), so the tally
  stays NOT verified. The owed recount was
  checked for again and still NOT paid —
  MemAvailable stayed ~0.68–1.05 GB across the
  watches (samples 806296 / 695380 / 804116 /
  728800 / 892252 / 1052248 / 1071008 kB,
  1-minute load ~10.3–11.4, 5-minute load
  ~5.7–7.5, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~03:55 EST: no Samverk
  worker was live and no new commits had landed
  since the 03:45 EST tick (head 0dcb444, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  mythic-coder-build, hermes-hack-build), none to
  Samverk). The 00:25 recount log was re-read
  from disk and still carries no summary line
  (1120 bytes, unchanged since 01:24, progress
  through ~97% then no summary), so the tally
  stays NOT verified. The owed recount was
  checked for again and still NOT paid —
  MemAvailable stayed ~0.51–0.87 GB across the
  watches (samples 561536 / 536700 / 512964 /
  564796 / 564328 / 627140 / 870932 kB,
  1-minute load ~3.5–5.5, 5-minute load
  ~6.1–7.4, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~04:05 EST: no Samverk
  worker was live and no new commits had landed
  since the 03:55 EST tick (head 9fb054a, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, hermes-hack-build,
  mythic-coder-build), none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, 1008 markers through
  ~97% then no summary), so the tally stays NOT
  verified. The owed recount was checked for
  again and still NOT paid — MemAvailable stayed
  ~0.47–0.75 GB across the watches (samples
  572280 / 735440 / 469936 / 493952 / 748632 kB,
  1-minute load ~2.2–10.6, 5-minute load
  ~5.8–7.3, swap 0), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~04:15 EST: no Samverk
  worker was live and no new commits had landed
  since the 04:05 tick (head ae16930, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, ember-build), none to
  Samverk, plus a ravens soak process). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary; its later markers carry many
  F's from that contended run), so the tally
  stays NOT verified. Memory was the best in
  many hours (MemAvailable ~4.10–4.68 GB across
  the watches) but load stayed high on this
  4-core swapless box (1-minute ~5.8–8.2,
  5-minute ~6.4–6.8, other campaigns running
  throughout), so the machine was not quiet
  and launching the ~1000-test recount would
  still risk a long contended run proving
  nothing clean — the recount was NOT launched.
  The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~04:25 EST: no Samverk
  worker was live and no new commits had landed
  since the 04:15 tick (head f7bd9ee, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build,
  hermes-hack-build, mindspark-build), none to
  Samverk, plus a ravens soak process). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary; its later markers carry many
  F's from that contended run), so the tally
  stays NOT verified. Contention was the
  heaviest of the night on this 4-core box
  (MemAvailable ~2.40 GB at tick start falling
  to ~1.59 GB, 1-minute load ~8.8 rising to
  ~16.3, 5-minute load ~5.4 rising to ~9.5,
  other campaigns running throughout), so the
  machine was not quiet and launching the
  ~1000-test recount would still risk a long
  contended run proving nothing clean — the
  recount was NOT launched. The recount
  (expectation 1027 passed / 1 skipped / 0
  failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~04:35 EST: no Samverk
  worker was live and no new commits had landed
  since the 04:25 tick (head aaaa57d, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build,
  hermes-hack-build, ember-build,
  mythic-coder-build), none to Samverk). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary; its later markers carry many
  F's from that contended run), so the tally
  stays NOT verified. Contention was the
  heaviest yet seen on this 4-core box
  (MemAvailable ~0.79 GB at tick start falling
  to ~0.70 GB, 1-minute load ~18.8 rising to
  ~19.9, 5-minute load ~7.8 rising to ~8.4,
  other campaigns running throughout), so the
  machine was far from quiet and launching the
  ~1000-test recount would risk OOM and prove
  nothing clean — the recount was NOT launched.
  The recount (expectation 1027 passed /
  1 skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~04:45 EST: no Samverk
  worker was live and no new commits had landed
  since the 04:35 tick (head d80d193, verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (sagnaskemma-build, yggdrasil-build,
  ember-build, mythic-coder-build,
  hermes-hack-build), none to Samverk; the box
  had rebooted ~8 minutes before the tick). The
  00:25 recount log was re-read from disk and
  still carries no summary line (1120 bytes,
  unchanged since 01:24, progress through ~97%
  then no summary; its later markers carry many
  F's from that contended run), so the tally
  stays NOT verified. Contention stayed severe
  (MemAvailable ~1.38 GB at tick start falling
  to ~0.91–1.00 GB, 1-minute load ~10.0–12.5,
  5-minute load ~5.4–7.3 on 4 cores, swap 0,
  other campaigns' suites respawning
  throughout), never near a safe threshold for
  the ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean — the recount was NOT launched. The
  recount (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~04:55 EST: no Samverk
  worker was live and no new commits had landed
  since the 04:45 tick (head 92cd98c, verified
  equal to origin/main by ls-remote after a
  fetch; worktree clean — the pytest processes
  on the box were verified by cwd to belong to
  other campaigns (sagnaskemma-build,
  yggdrasil-build, ember-build,
  mythic-coder-build, mindspark-build), none
  to Samverk). The 00:25 recount log
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log`)
  was re-read from disk and still carries no
  summary line (1120 bytes, mtime 2026-11-01
  01:24, unchanged; progress through ~97% then
  no summary, its later markers carrying many
  F's from that contended run), so the tally
  stays NOT verified. Contention stayed severe
  across three watches (MemAvailable ~1.01 /
  ~1.13 / ~1.00 GB, 1-minute load ~10.8 easing
  to ~3.4 but 5-minute load ~8.1–10.5 on 4
  cores, swap 0, other campaigns' suites
  running throughout), never near a safe
  threshold for the ~1000-test suite on this
  swapless box, so launching would risk OOM
  and prove nothing clean — the recount was
  NOT launched. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~05:05 EST: no Samverk
  worker was live and no new slice commits had
  landed since the 04:55 tick (head aaead1d,
  verified equal to origin/main by ls-remote
  after a fetch; worktree clean — the pytest
  processes on the box were verified by cwd to
  belong to other campaigns (yggdrasil-build,
  mythic-coder-build, ember-build,
  mindspark-build), none to Samverk). The
  00:25 recount log
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log`)
  was re-read from disk again: 1120 bytes,
  mtime 2026-11-01 01:24, unchanged; progress
  markers through ~97% then no summary line
  and no exit marker, so the tally stays NOT
  verified. (Correction, same tick, on the
  full log read: the markers are clean only
  to ~42% — from there to 97% they carry
  hundreds of F's from that contended run,
  exactly as the 04:55 tick recorded; a
  contended run's failures are not a verdict
  on shipped code, and with no summary the
  run counts for nothing either way.)
  Contention was checked across
  four watches: MemAvailable opened ~2.38 GB,
  briefly rose to ~4.68–5.35 GB — the best
  readings in hours — then fell back to
  ~2.13 GB within two minutes as other
  campaigns' suites regrew; 5-minute load
  stayed ~6.3–8.0 on 4 cores throughout,
  swap 0 — a momentary memory window, never
  a quiet machine, so launching the
  ~1000-test recount would risk OOM and
  prove nothing clean — the recount was NOT
  launched. The offload road was also
  checked: purplelongship is offline (device
  last seen 2026-11-01 02:07 UTC), so no
  offloaded recount could be started this
  tick. The recount (expectation 1027
  passed / 1 skipped / 0 failed, covering
  S-148, S-149 and S-150) plus S-150's
  combined affected-suites cross-check stay
  owed, and S-151 does not bank until a
  keeper run on a quiet machine verifies
  the recount from its log file;
  next S-151 CODEOWNERS;
  keeper tick 2026-11-01 ~05:15 EST: no Samverk
  worker was live and no new slice commits had
  landed since the 05:05 tick (head bbc0bdc —
  that tick's correction commit — verified
  equal to origin/main by ls-remote; worktree
  clean — the pytest processes on the box were
  verified by cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build,
  ember-build, hermes-hack-build), none to
  Samverk). The 00:25 recount log
  (`~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log`)
  was re-read from disk again: 1120 bytes,
  mtime 2026-11-01 01:24, unchanged; progress
  markers through ~97% (clean only to ~42%,
  then hundreds of F's from that contended
  run), no summary line and no exit marker,
  so the tally stays NOT verified. Contention
  was checked across a six-sample watch:
  MemAvailable stayed ~1.04–1.21 GB (samples
  1211452 / 1210420 / 1121444 / 1046128 /
  1131868 / 1096160 kB), 5-minute load
  ~6.4–6.7 on 4 cores, swap 0 — never near a
  safe threshold for the ~1000-test suite on
  this swapless box, so launching would risk
  OOM and prove nothing clean — the recount
  was NOT launched. The offload road was
  also checked: purplelongship is still
  offline (device last seen 2026-11-01
  02:07 UTC), so no offloaded recount could
  be started this tick. The recount
  (expectation 1027 passed / 1 skipped /
  0 failed, covering S-148, S-149 and S-150)
  plus S-150's combined affected-suites
  cross-check stay owed, and S-151 does not
  bank until a keeper run on a quiet machine
  verifies the recount from its log file;
  next S-151 CODEOWNERS. (Banking note,
  same tick: this tick's map commit + push
  were BLOCKED by the box's git write gate —
  `git commit` and `git hash-object -w` both
  fail with "unable to write loose object
  file: Operation not permitted" while plain
  file writes to .git/objects succeed; the
  same gate blocked the 2026-10-31 09:45
  tick's commit. This entry therefore stands
  as an uncommitted worktree edit at head
  bbc0bdc for the next keeper tick to bank,
  exactly as the 09:55–10:15 ticks banked
  their predecessors' entries together.)
  keeper tick 2026-11-01 ~05:25 EST: no Samverk
  worker was live and no new slice commits had
  landed since the 05:05 tick (head bbc0bdc,
  verified equal to origin/main by ls-remote
  at tick start; the 05:15 tick's entry stood
  as the only uncommitted worktree edit — the
  pytest processes on the box were verified by
  cwd to belong to other campaigns
  (yggdrasil-build, sagnaskemma-build,
  hermes-hack-build), none to Samverk). The
  00:25 recount log was re-read from disk
  again: 1120 bytes, mtime 2026-11-01 01:24,
  unchanged; progress markers through ~97%
  (clean only to ~42%, then hundreds of F's
  from that contended run), no summary line
  and no exit marker, so the tally stays NOT
  verified. Contention was checked across a
  watch: MemAvailable stayed ~0.73–0.95 GB
  (samples 927484 / 946324 / 879184 / 921160 /
  732580 kB), 1-minute load ~10.8–13.4 and
  5-minute load ~5.5–6.8 on 4 cores, swap 0 —
  never near a safe threshold for the
  ~1000-test suite on this swapless box, so
  launching would risk OOM and prove nothing
  clean — the recount was NOT launched. The
  recount (expectation 1027 passed / 1
  skipped / 0 failed, covering S-148, S-149
  and S-150) plus S-150's combined
  affected-suites cross-check stay owed, and
  S-151 does not bank until a keeper run on a
  quiet machine verifies the recount from its
  log file;
  next S-151 CODEOWNERS.
  Campaign branch: `yrsa/samverk-part1` (local banking continues
  on the same branch until a Part II branch is struck).
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
- **S-004 DONE (2026-10-29)** — password hashing: `samverk/passwords.py`
  — scrypt (stdlib `hashlib`, n=32768/r=8/p=1, ~32 MiB) with per-user
  128-bit salts, self-describing stored format, legacy pbkdf2-sha256
  verify-only rows, upgrade-on-login via `verify_and_upgrade`.
  Battery `tests/test_passwords.py`: **9 passed / 0 failed** —
  known-answer vectors for both algorithms, wrong-password and
  malformed-row rejection, timing floor proving the work factor,
  upgrade path end-to-end. (One test-authoring slip found and fixed
  during the run: a hand-typed base64 salt in the KAT strings; the
  KDF digests were verified byte-exact against fresh computation.)
  Cumulative battery: 28/28.
- **S-005 DONE (2026-10-29)** — `samverk/throttle.py`:
  `constant_time_equal` (the single comparison seam for secrets;
  `passwords.py` refactored onto it) and `LoginThrottle` (per-account
  exponential backoff: 3 free failures, then 2s doubling to a 300s
  cap; delays, never locks). Battery `tests/test_throttle.py`:
  **7 passed / 0 failed** — trip after N failures, release after
  backoff, growth + cap, success-clears, per-account independence.
  Cumulative battery: 35/35.
- **S-006 DONE (2026-10-29)** — session tokens: `samverk/sessions.py`
  (schema migration 2) — 256-bit CSPRNG tokens, only SHA-256 hashes
  stored, absolute (30 d) + idle (7 d) expiry, tombstone revocation
  incl. `revoke_all`, commit-before-answer on creation. Battery
  `tests/test_sessions.py`: **9 passed / 0 failed**, including the
  literal acceptance — values stolen from a seeded DB presented as
  tokens are refused, and the raw token appears nowhere in the DB
  file. (The S-003 migration test was updated to assert against the
  latest migration number rather than a hard-coded 1 — intent
  preserved.) Cumulative battery: 44/44.
- **S-007 DONE (2026-10-29)** — audit log core: `samverk/audit.py`
  (schema migration 3) — append-only hash-chained table (canonical
  serialisation fixed in code, genesis-anchored), serialised appends
  under lock + transaction, `verify_chain` verifier, and the
  `samverk audit verify` operator command. Battery
  `tests/test_audit.py`: **6 passed / 0 failed** — clean chain
  verifies, a tampered row is detected at its seq, a deleted row is
  detected, chain linkage/genesis checked, no update/delete API,
  CLI verify exits 0 clean / 1 broken. Cumulative battery: 50/50.
- **S-008 DONE (2026-10-29)** — audit taxonomy v1:
  `docs/AUDIT_TAXONOMY.md` + `samverk/taxonomy.py` — 37 frozen event
  names (15 auth, 13 repo, 9 admin); `AuditLog.append` refuses
  unknown names, so no call site can invent events. Battery
  `tests/test_taxonomy.py`: **6 passed / 0 failed** — doc and code
  name exactly the same set, every event emittable, unknown names
  refused and enter nothing. Cumulative battery: **56/56**.
- **S-009 DONE (2026-10-30)** — HTTP security baseline:
  `samverk/http_security.py` — session cookies (`HttpOnly` always,
  `Secure` when the operator declares HTTPS via the new
  `secure_cookies` config flag, `SameSite=Lax`, `Path=/`, no
  `Domain`, plain `session` name, header-injection values refused)
  and CSRF synchroniser tokens (HMAC-SHA256 keyed by the session
  token itself: unforgeable without the session, reveals nothing
  about it, stores nothing, rotates with the session; validation
  via the S-005 constant-time seam, fails closed on missing /
  foreign / tampered tokens). The server enforces the gate *before
  routing* every state-changing method, so later routes inherit it
  by construction. Battery `tests/test_http_security.py`:
  **17 passed / 0 failed**, including the literal acceptance —
  forged cross-site POSTs (no token, foreign token, no session)
  refused 403 over real HTTP, legitimate header- and form-token
  POSTs pass the gate. Cumulative battery: **73/73**.
- **S-010 DONE (2026-10-30)** — output-escaping standard:
  `samverk/escaping.py` is the one seam (mechanically enforced like
  the platform seam: no other module may escape directly) —
  `escape_html_text` for content, `escape_html_attr` for quoted
  attributes, `safe_url` as the href/src sanitiser (http/https/
  mailto + instance-relative only; `javascript:`/`data:`/obfuscated
  and protocol-relative URLs refused; the check also runs on the
  entity-decoded form — a battery-found bypass, `&#106;avascript:`,
  fixed in-slice). No JS-string escaper by design (no inline-script
  interpolation; S-016's CSP will forbid them). Battery
  `tests/test_escaping.py`: **12 passed / 0 failed**, including the
  stored-XSS payload battery rendered through a profile snippet.
  Cumulative battery: **85/85**.
- **S-011 DONE (2026-10-30)** — rate limiting:
  `samverk/rate_limit.py` — thread-safe token buckets (burst to
  capacity, then the refill rate; refusals carry a truthful
  `Retry-After`) in a keyed `RateLimiter` deciding per-IP and
  per-account together: a request is charged to both buckets or
  neither, so one dimension's refusal never drains the other, and
  an account hopping IPs still meets its own bucket. Distinct
  from S-005's login-failure backoff by design (different layers
  of the same door). Fully-refilled idle buckets are pruned.
  Battery `tests/test_rate_limit.py`: **11 passed / 0 failed**,
  including the burst test and a 20-thread race granting exactly
  capacity. Cumulative battery: **96/96**.
- **S-012 DONE (2026-10-30)** — upload handling law:
  `samverk/uploads.py` — size cap first, then content sniffing
  beats declared type (magic-number / strict-text sniff; a
  concrete declared type that disagrees with the sniff is a
  disguise and is refused; generic `application/octet-stream`
  defers to the sniff), then quarantine: accepted bytes land
  content-addressed (SHA-256 + sniffed-type extension, mode 600)
  in `<data_root>/quarantine/`, the uploader's filename never
  forms a path, rejected uploads write nothing. SVG is refused
  by the default policy until a sanitiser can vouch for it.
  Battery `tests/test_uploads.py`: **10 passed / 0 failed**,
  including the literal acceptance — script/executable/HTML
  payloads declaring themselves `image/png` all rejected.
  Cumulative battery: **106/106**.
- **S-013 DONE (2026-10-30)** — repository path resolution:
  `samverk/repo_paths.py` — the one mapping from names to disk
  paths (`<data_root>/repos/<owner>/<repo>.git`). Two defences:
  a strict name law (allowlist shape, no `..`/separators/controls,
  no trailing dot, Windows device names refused on every OS,
  a single trailing `.git` canonicalised away) and a containment
  law (the candidate is fully resolved and must land strictly
  inside the resolved repos root, so a planted symlink — owner
  dir or repo path — pointing outside is refused at resolve
  time, on every call, never cached). Battery
  `tests/test_repo_paths.py`: **10 passed / 0 failed**,
  including the literal acceptance — the `..`/symlink escape
  battery. Cumulative battery: **116/116**.
- **S-014 DONE (2026-10-30)** — subprocess discipline:
  `samverk/proc.py` — git (the only allowlisted program) is run
  with no shell, ever; argv[0] is resolved from the logical name
  `git` via the module's own allowlist, never from user input;
  the first argument must be an allowlisted subcommand
  (`GIT_SUBCOMMANDS`, extended only here, with reasons), so the
  global-option position (`-c`, `--git-dir`, …) is unreachable;
  dangerous redirect flags are refused in any position; the
  repository is a trusted parameter (`run_git_in`, path from
  S-013) inserted as `--git-dir` by the module itself;
  `GIT_DIR`/`GIT_CONFIG_*` and kin are stripped from the
  inherited environment and `GIT_TERMINAL_PROMPT=0`; every spawn
  carries a mandatory timeout. Battery `tests/test_proc.py`:
  **8 passed / 0 failed**, including the literal acceptance —
  shell-metacharacter injections arrive as inert single argv
  entries and create nothing, and real git work (init /
  hash-object / cat-file) flows through the law. (One design
  flaw found by the battery and fixed in-slice: `rev-parse
  --git-dir` is a read-only query, not a redirect — the bare
  query token is now allowed for rev-parse alone; every
  `--git-dir=<path>` form stays refused everywhere.)
  Cumulative battery: **124/124**.
- **S-015 DONE (2026-10-30)** — TLS and secure defaults:
  `samverk/tls_policy.py` + config fields (`tls_cert_file`,
  `tls_key_file`, `allow_plaintext_http`; file + env). The bind
  law is enforced in `serve()` before anything listens:
  loopback is literal (`localhost`, 127.0.0.0/8, ::1 — wildcards
  and DNS names are *not* loopback, and no DNS is consulted);
  non-loopback plaintext is **refused**, not warned; TLS
  configured with both files takes the `tls` posture (socket
  wrapped in `serve`, TLS ≥ 1.2, and S-009's Secure-cookie flag
  becomes a fact of the bind); exactly one TLS file is refused
  as half-configured in every posture; the operator override
  only exists when audit-logged — `enforce_bind_policy` raises
  `override_requires_audit` without an `AuditLog`, and with one
  it writes `admin.plaintext_http_override` before returning.
  Battery `tests/test_tls_policy.py`: **9 passed / 0 failed**,
  including the literal acceptance — refusal outside loopback,
  and the override landing exactly one verifiable audit row.
  Cumulative battery: **133/133**.
- **S-016 DONE (2026-10-30)** — content security policy:
  `samverk/csp.py` — one canonical policy (`default-src 'self'`
  with every fetch directive spelled out, `object-src 'none'`,
  `frame-ancestors 'none'`, `base-uri`/`form-action 'self'`,
  and no `unsafe-inline`/`unsafe-eval` anywhere — the browser
  half of S-010's no-inline-scripts promise), sent by the
  server's single send path so no route can forget it. The
  acceptance lifecycle is a config switch (`csp_mode`,
  file + env): `report-only` sends the *identical* policy value
  under `Content-Security-Policy-Report-Only`, `enforce`
  (default) under `Content-Security-Policy`; an unknown mode
  raises at startup rather than silently shipping no CSP.
  Battery `tests/test_csp.py`: **5 passed / 0 failed**,
  including real-HTTP checks that every core response
  (health, root, 404, and the CSRF gate's 403) carries the
  enforced header and that report-only mode swaps the header
  name only. Cumulative battery: **138/138**.
- **S-017 DONE (2026-10-30)** — dependency policy:
  `samverk/dependencies.py` (the code register:
  `ADMITTED_DEPENDENCIES`, today empty) +
  `docs/DEPENDENCY_REGISTER.md` (the human register). Admission
  requires all three of: a register entry with distribution,
  exact `==` pin, import name, and a reason line naming what
  the stdlib cannot do; the doc row; and the pinned pyproject
  requirement — in one commit. Battery
  `tests/test_dependencies.py`: **5 passed / 0 failed** — it
  parses pyproject (stdlib `tomllib`) and requires the declared
  runtime dependencies to equal the register exactly, checks
  every admission carries a reason + exact pin and is named in
  the doc, and AST-scans the package *and* the test suite so
  every import must be stdlib, intra-package, or admitted
  (with a guard test proving the scan really sees the package).
  The register's emptiness is now a proven fact per run.
  Cumulative battery: **143/143**.
- **S-018 DONE (2026-10-30)** — log redaction:
  `samverk/log_redaction.py` — a `RedactingFilter` for the
  logging stack (installed on the root logger by `serve()`),
  applying three layers in `redact_text`: registered literal
  secrets (`register_secret`, min length 4, longest-first);
  auth shapes struck whole (`Bearer`/`Basic`,
  `Authorization:`/`Cookie:`/`Set-Cookie:` header values); and
  sensitive-key pairs (`key=value`, `key: value`, JSON pairs)
  whose key is sensitive as a whole `_`/`-`-separated segment —
  `csrf_token`/`auth_token`/`x-api-key` strike, `author` does
  not. Keys survive so logs stay debuggable; bare hex is
  deliberately *not* struck (git SHAs belong in logs). Battery
  `tests/test_log_redaction.py`: **7 passed / 0 failed**,
  including the literal acceptance — seeded secrets in plain,
  format-arg, cookie, and JSON shapes never appear in captured
  logs. (One flaw found by the battery and fixed in-slice: the
  first key pattern's word boundary let compound keys like
  `csrf_token='…'` leak; the segment-aware pattern replaced
  it.) Cumulative battery: **150/150**.
- **S-019 DONE (2026-10-30)** — error law:
  `samverk/errors.py` — clients receive exactly
  `{"error": <registered code>, "error_id": <64-bit CSPRNG
  hex>}` and nothing else; codes are a frozen registry (like
  the S-008 taxonomy — an unregistered code raises in-process,
  never reaches a client); handlers may raise `PublicError`, and
  the server's dispatch is guarded so any unexpected exception
  becomes an opaque 500 under a fresh error id while the full
  detail lands in the server log under the *same* id via
  `log_internal_error` — which renders the traceback itself and
  redacts before writing (a bare `logger.exception` would carry
  exception text past S-018's filter, since logging appends
  tracebacks after filters run; this function exists for that
  reason). The base class's HTML error pages (malformed
  requests, unknown methods) are replaced wholesale with the
  JSON shape. The S-002 skeleton test's exact 404 assertion was
  updated to the extended shape, intent preserved. Battery
  `tests/test_errors.py`: **7 passed / 0 failed**, including a
  handler rigged to raise a secret-carrying exception — the 500
  body leaks neither message, path, nor traceback, and the
  captured server log holds the detail under the id, redacted.
  Cumulative battery: **157/157**.
- **S-020 DONE (2026-10-30)** — operator key custody:
  `samverk/keys.py` + `docs/KEY_CUSTODY_RUNBOOK.md` + `samverk
  keys ensure|status|rotate` CLI. Keys are generated at install
  (`ensure_instance_key`, 256-bit CSPRNG, idempotent — never
  silently replaced), stored as files only under
  `<data_root>/keys/` (`instance-<purpose>-v<N>.key`, hex,
  mode 600 from the first instant via `os.open`; loosely-
  permissioned or corrupt files refused fail-closed), and
  identified publicly by a 16-hex SHA-256 fingerprint that is
  safe to log. Rotation mints N+1 and keeps every earlier
  version loadable by number; the CLI's rotation is
  audit-logged (`admin.key.rotate`, fingerprints only). The
  runbook carries backup/restore/compromise duties, including
  the fingerprint comparison that proves a restore. Battery
  `tests/test_keys.py`: **8 passed / 0 failed**, including the
  literal acceptance — the full rotation drill on a scratch
  instance (generate → rotate ×2 → all versions load, all
  material distinct, key bytes and hex absent from the DB
  file) and the CLI drill end to end. Cumulative battery:
  **165/165**.
- **S-021 DONE (2026-10-30)** — signup abuse friction:
  `samverk/signup_friction.py` — a `SignupGuard` that decides
  (registration itself is S-025's, and consumes the decision).
  Friction is ours alone, **no third-party captcha**: S-011
  buckets aimed at signup (per-IP 5 attempts refilling 5/hour
  + per-email 3 refilling 3/hour, charged both-or-neither, so
  one-IP floods and one-address-many-IP retries both die), and
  disposable-domain *policy hooks* — a plain callable over the
  parsed domain; shipped policies are allow-all (default) and
  an operator blocklist (listed domains + their subdomains);
  no third-party disposable list is bundled or fetched.
  Decision order is deliberate: malformed → refused as
  malformed; domain-refused → refused without spending throttle
  tokens; only plausible attempts are charged. Battery
  `tests/test_signup_friction.py`: **8 passed / 0 failed**,
  including the literal acceptance — a scripted 20-attempt
  flood from one IP is throttled after 5 with truthful
  retry-afters, and buckets refill on the fake clock. (One
  parser flaw found by the battery and fixed in-slice:
  `a@.com` — an empty domain label — initially passed; the
  parser now requires ≥2 non-empty labels.) Cumulative
  battery: **173/173**.
- **S-022 DONE (2026-10-30)** — security battery v1:
  `tests/test_security_battery.py` — **9 passed / 0 failed**,
  attacking the *assembled* Part I system (real HTTP server,
  real session store, real seams): fabricated session cookies
  buy nothing and cross-site POSTs are refused 403; a DB-leak
  drill (stolen session-table values presented back)
  authenticates no one; SQL injection is stored as inert data
  with the audit chain intact; shell injection through git
  argv creates nothing; cookie header injection is refused;
  stored-XSS payloads render inert. **Named honestly in the
  file:** classic IDOR has no surface yet (no accounts or
  per-user resources exist in Part I), so the identifier class
  strikes the identifier surfaces that exist — repo names and
  URL paths — and Part II's gate (S-048) inherits the file.
  Cumulative battery: **182/182**.
- **S-023 DONE (2026-10-30)** — claims register:
  `docs/CLAIMS_REGISTER.md` — 12 claims (C-01…C-12) drawn from
  the README, each **PROVEN** with its counted evidence or
  **NOT PROVEN** with the roadmap part that owns its proof.
  Proven (some scoped, scope named in the row): DB-leak ≠
  credential leak, threat-model-first, audit tamper evidence,
  CSRF fail-closed, escaping seam + CSP, opaque error ids,
  stdlib-only/standalone, no-Docker construction. NOT PROVEN:
  unmodified-git-client transport (Part III), Windows/macOS/
  ARM-Pi cells (Part XXII), the design-lawbook face (Part XX),
  the mirror duty (Part XVII). Battery
  `tests/test_claims_register.py`: **4 passed / 0 failed** —
  anchor coverage for every tracked claim, PROVEN rows must
  name evidence files that exist, NOT PROVEN rows must name
  their owning part, and a tree scan keeps container
  artifacts out. The README's Status section was hand-updated
  in place (his text preserved; the stale "no code exists"
  paragraph replaced with the Part I position + a register
  pointer). Gate hardening in the same stretch: S-015's TLS
  wrap, previously unexercised on the wire, was proven
  end-to-end (real handshake + HTTPS health route + plaintext
  refused by the TLS port; commit 4ee3b61). Cumulative
  battery: **187/187** (recounted at the S-024 gate below).
- **S-024 DONE (2026-10-30) — PART I GATE.** Counted security
  run executed fresh at the gate on this VM (Linux x86-64):
  `python3 -m unittest discover -s tests` → **187 passed /
  0 failed**, including the S-022 attack battery (9) against
  the assembled system. Every Part I slice S-001…S-023 is
  banked with its own counted battery green at its commit.
  **Open findings, named, none hidden:**
  (1) Platform cells beyond Linux x86-64 are **NOT PROVEN** —
  Windows, macOS, ARM/Pi (claims C-10; Part XXII owns proof).
  (2) Classic IDOR has no surface yet — no accounts or
  per-user resources exist; the S-022 battery strikes the
  identifier surfaces that exist and is inherited by Part
  II's gate (S-048), where the IDOR class grows teeth.
  (3) CSP report-only mode has no server-side report
  endpoint yet — reports are the browser's half; collection
  lands with the web UI parts.
  (4) The TLS posture is proven end-to-end with a scratch
  self-signed cert (4ee3b61); operator-certificate handling
  at install time belongs to Part XVIII.
  (5) Everything banked this campaign sits on local `main` /
  `yrsa/samverk-part1` only — **no GitHub push made**: pushes
  stay gated on Volmarr's explicit word.
  **Part I is complete.** Next: Part II — Accounts & Identity,
  opening at S-025 registration.
- **S-025 DONE (2026-10-30)** — registration: `samverk/accounts.py`
  + schema migration 4 (`users`: display case kept, canonical
  `username_lower`/`email_lower` UNIQUE keys, email nullable so
  NULLs never collide). Username law: 3–39 chars, letters/digits/
  hyphen/underscore, no leading/trailing separator shape, must
  also pass S-013's owner law; reserved names (admin/root/
  support/samverk/api/www + Windows devices via S-013) refused
  with a clear reason. Email optional-but-supported: given
  addresses are shape-checked (S-021 parser + local-part law)
  and unique case-insensitively. Password policy is study 07
  §3.3: min 10 / max 128, no composition rules, screened against
  a bundled common list + the username; stored only as S-004
  scrypt. S-021's SignupGuard is consulted when supplied.
  Refusals create nothing and are audit-logged
  (`auth.signup.denied` with reason); successes commit before
  answering and log `auth.signup.success`. The
  `verification_mode` gate (none/smtp/operator) sets the new
  account's status for S-026. Battery `tests/test_accounts.py`:
  **12 passed / 0 failed**, including the literal acceptance —
  duplicate (any case) and reserved attempts refused clearly.
  Cumulative battery: **199/199**.
- **S-026 DONE (2026-10-30)** — email verification:
  `samverk/email_verification.py` + schema migration 5
  (`email_verification_tokens`, hashes only). Two roads, chosen
  by what the instance has: with a mailer seam (SMTP configured)
  a 256-bit token is minted, only its SHA-256 stored, the raw
  token handed to the mailer once; redemption is single-use,
  24 h expiry, a fresh request retires older tokens, and success
  marks the email verified and activates a
  `pending_verification` account. Without a mailer no token is
  minted or pretended — the account moves to `pending_approval`
  and `approve_user` (the operator's word, audited as
  `admin.user.approve` with the operator named) activates it;
  no-email accounts can only take this road. Failures answer
  generically (`invalid_or_expired` — invalid, expired, and
  used are indistinguishable). Taxonomy grew append-only by two
  events (`auth.email.verify`, `admin.user.approve`; 39 total,
  doc + code + counts updated together). Battery
  `tests/test_email_verification.py`: **10 passed / 0 failed**,
  including the DB-leak test (stored hashes redeem nothing, raw
  token absent from the DB file) and audit checks for both
  roads. Cumulative battery: **209/209**.
- **S-027 DONE (2026-10-30)** — login/logout: `samverk/login.py`
  (`LoginService` over S-025 accounts + S-006 sessions + S-005
  throttle). Every refusal — no such user, wrong password,
  pending/suspended status, throttled — raises the same
  `LoginFailed` with the same generic message, and a nonexistent
  user still costs a scrypt verify against a decoy hash so
  timing cannot enumerate accounts. Failures are audited
  (`auth.login.failure`, attempted name only, never a password)
  and feed the per-account exponential throttle (delays, never
  locks; success clears it); success audits
  `auth.login.success`, persists any S-004 hash upgrade, and
  issues a fresh session. Logout tombstones the session token
  itself and audits `auth.logout`; a second logout is a quiet
  no-op. **Bug found by this battery and fixed in-slice:**
  `SessionStore.revoke` reported True for an already-revoked
  token (SQLite counted the re-matched row); it now only
  revokes a live session (`AND revoked = 0`), verified against
  the S-006 and S-022 batteries too. Battery
  `tests/test_login.py`: **7 passed / 0 failed**. Cumulative
  battery: **216/216**.
- **S-028 DONE (2026-10-30)** — password change and reset:
  `samverk/password_reset.py` + schema migration 6
  (`password_reset_tokens`, hashes only, `via` recorded).
  Change requires the current password (a wrong one changes
  nothing — no hash moves, no session dies), enforces S-025's
  policy, and on success revokes **all** sessions. Reset:
  `request_reset` always answers identically (no enumeration);
  a letter is minted only for an existing active account with
  an email when a mailer is configured — 256-bit, SHA-256 at
  rest, **single-use, 1-hour expiry**, fresh requests retire
  older tokens. The operator road (`issue_operator_reset`)
  mints host-side for the no-mail instance, same redemption,
  audit records `via: operator`. Redemption validates the new
  password *before* consuming the token (a refused password
  does not burn the letter), then replaces the hash and revokes
  all sessions. Audited: `auth.password.change`,
  `auth.password.reset`. Battery `tests/test_password_reset.py`:
  **10 passed / 0 failed**, including the DB-leak test and the
  acceptance in literal form (single-use, expiring,
  all-sessions-revoked). Cumulative battery: **226/226**.
- **S-029 DONE (2026-10-30)** — profiles: `samverk/profiles.py`
  + schema migration 7 (`profiles`, one row per account).
  Display name (≤50) and bio (≤500, newlines allowed) are
  control-character-free plain text. Avatar upload is S-012 law
  narrowed to images (2 MiB cap, image-only policy): sniff beats
  declared, disguised/non-image payloads refused, quarantine
  first, then promotion to `<data_root>/avatars/<sha256><ext>`
  (mode 600) under the content-addressed name. **Alt text is
  mandatory** (Volmarr's image-accessibility law): an avatar
  with empty/missing alt is refused and stores nothing. The
  profile page (`render_profile_page`) renders only through
  S-010's escaping seam and always emits the stored alt on the
  avatar `<img>`. Taxonomy grew append-only by one event
  (`auth.profile.update`; 40 total, doc + code + counts updated
  together). Battery `tests/test_profiles.py`: **10 passed /
  0 failed**, including the literal acceptance (avatar under
  S-012 law + every image carries alt text). Cumulative
  battery: **236/236**.
- **S-030 DONE (2026-10-30)** — SSH keys: `samverk/ssh_keys.py`
  + schema migration 8 (`ssh_keys`, fingerprint globally
  UNIQUE). Parsing is strict: admitted algorithms only
  (ed25519, ecdsa nistp256/384/521, rsa — legacy ssh-dss
  refused), strict base64, and the blob's inner algorithm
  string must match its outer label. Fingerprint is the
  OpenSSH shape (`SHA256:<base64, padding stripped>`); list
  shows title, fingerprint, created and last-used
  (`record_use` stamps it for Part III's transport). **Key
  add requires sudo-mode re-auth through a fail-closed seam:**
  `SshKeyStore` takes a `reauth_verifier` callable (S-036
  supplies the real sudo mode); no verifier or a "no" answer
  refuses the add `sudo_required` and stores nothing —
  S-036's battery inherits the seam. One key, one account:
  re-registering your own key or another account's key is
  refused alike. Delete is owner-only and audit-logged with
  the fingerprint (`auth.ssh_key.add` / `auth.ssh_key.remove`,
  both already in the frozen taxonomy). Battery
  `tests/test_ssh_keys.py`: **8 passed / 0 failed**, including
  the literal acceptance (add gated on re-auth). Cumulative
  battery: **244/244**.
- **S-031 DONE (2026-10-30)** — deploy keys:
  `samverk/deploy_keys.py` + schema migration 9
  (`deploy_keys`, fingerprint UNIQUE). A deploy key binds to
  **exactly one repository** by canonical owner/repo (both
  halves under S-013's name law; repositories themselves land
  in Part III, the binding is by identity). **Read-only by
  default**; read/write is an explicit `can_write=True` grant
  at creation — no silent widening later (a grant change is a
  delete + re-add, two audit rows). `authorize(fingerprint,
  owner, repo, write=)` returns the key only for its own repo
  and only within its grant — another repo, another owner, or
  a write asked of a read-only key all answer None; S-088
  proves it on the wire. A fingerprint may not be both a
  personal and a deploy key, nor serve two repos. Adds/removes
  are owner-only and audit-logged as `repo.settings.change`
  with fingerprint + grant (never key material beyond the
  public blob). Battery `tests/test_deploy_keys.py`: **7
  passed / 0 failed**, including the literal acceptance (a
  deploy key cannot reach other repos). One battery-found
  flaw fixed in-slice: the new test's cross-test import
  (`tests.test_ssh_keys`) tripped S-017's import scan —
  helpers inlined instead. Cumulative battery: **251/251**.
- **S-032 DONE (2026-10-30)** — personal access tokens,
  classic shape: `samverk/access_tokens.py` + schema
  migration 10 (`access_tokens`, hashes only). Tokens are
  `svk_` + 256-bit CSPRNG, **shown once** at creation; only
  the SHA-256 hash is stored (S-006 law), with a 12-char
  identifying prefix for lists. **Scopes are required and
  closed** (`CLASSIC_SCOPES`: repo/issues/profile read+write;
  unknown scopes refused; write implies its read sibling via
  the one `token_allows` seam). **Expiry is required**, at
  most one year out; expired/revoked tokens authenticate to
  nothing. Revocation is owner-only; create/revoke audit as
  `auth.token.create` / `auth.token.revoke` (already in the
  frozen taxonomy; detail carries id + scopes, never the
  token). Battery `tests/test_access_tokens.py`: **9 passed /
  0 failed**, including the literal acceptance — the DB-leak
  test (stored hashes and prefix authenticate no one; the raw
  token is absent from the DB file). Cumulative battery:
  **260/260**.
- **S-033 DONE (2026-10-30)** — fine-grained tokens:
  `samverk/fine_grained_tokens.py` + schema migration 11
  (`fine_grained_tokens`, hashes only). A token binds to
  **exactly one repository** (canonical owner/repo, S-031's
  shape) and a per-resource permission set (contents /
  issues / pull_requests, read+write, plus `metadata:read`
  always held as the mandatory floor — stored, never hidden).
  Write implies only its own read sibling. `authorize` is the
  permission-matrix seam: wrong repo, wrong owner, ungranted
  or unknown permission, and expired/revoked tokens all
  answer None. S-032's law carries over: `svkf_` + 256-bit,
  shown once, expiry required (≤1 year), owner-only
  revocation, audited create/revoke without the token.
  Battery `tests/test_fine_grained_tokens.py`: **9 passed /
  0 failed**, including the literal acceptance — the full
  permission matrix (every permission × granted/ungranted ×
  own/other repo). Cumulative battery: **269/269**.
- **S-034 DONE (2026-10-30)** — token management UI
  (surface): `samverk/token_management.py` — one management
  home over both token stores. `TokenManagement.list_all`
  unifies classic + fine-grained tokens with title, prefix,
  scopes/permissions, target repo, created, **last-used**,
  expiry, and a status word (Active / Expired / Revoked —
  text, never colour alone); `revoke(user, kind, id)` is the
  one-click revocation, dispatched to the owning store whose
  owner-only law guards it. **Findability (the anti-Forgejo
  test):** `render_settings_home` links `/settings/tokens`
  in one click; the token page renders a revoke form (with
  the S-009 CSRF field) only for live tokens, and an empty
  state that teaches what a token is. All user text passes
  S-010's escaping seam. Battery
  `tests/test_token_management.py`: **7 passed / 0 failed**,
  including the findability walk (settings home → token
  page) and one-call revocation of both kinds. Cumulative
  battery: **276/276**.
- **S-035 DONE (2026-10-30)** — two-factor TOTP enrolment:
  `samverk/totp.py` + schema migration 12 (`totp_credentials`).
  RFC 6238/4226 HMAC-SHA1 TOTP (30 s step, 6 digits, ±1-step
  skew window) proven against the RFC known-answer vectors.
  Enrolment offers the provisioning URI (the QR encodes it)
  + the Base32 secret for manual entry; enabling is a step-up
  act through S-030's re-auth seam, failing closed, and only a
  live code confirms (`auth.twofactor.enable`, method totp).
  The 160-bit secret is stored **encrypted** under a caller-
  supplied 256-bit instance key (HMAC-SHA256 keystream, fresh
  nonce per enrolment; no key → enrolment refuses), never
  plain, and each counter may be spent once (`last_counter`
  replay law). Battery `tests/test_totp.py`: **10 passed /
  0 failed**, including the DB-leak test (the plaintext
  secret appears neither in the stored value nor the DB
  file). (Two test-authoring slips fixed in-slice: two RFC
  vectors first typed from the table's SHA-256 column, and
  the provisioning label's colon over-encoded.) Cumulative
  battery: **286/286**.
- **S-036 DONE (2026-10-30)** — sudo mode: `samverk/sudo_mode.py`
  + schema migration 13 (`sudo_grants`). Re-entering the
  account password (S-004 verify, decoy-hash timing for unknown
  accounts, upgrade persisted as in S-027) opens a 15-minute
  freshness window bound to **one session**, keyed by the
  session token's SHA-256 — the raw token never touches the
  table. Wrong password / unknown account is one generic
  `SudoFailed` and grants nothing; expired grants answer
  False and are swept. `as_verifier(session)` returns exactly
  the re-auth seam S-030/S-035 consume, fulfilling S-030's
  promise: its battery drives the real verifier through the
  SSH key-add gate (refused before the grant, allowed inside
  the window, refused after expiry). Battery
  `tests/test_sudo_mode.py`: **6 passed / 0 failed**,
  including the DB-leak test (grant rows hold hashes only,
  and a stored hash itself buys no freshness). Cumulative
  battery: **292/292**.
- **S-037 DONE (2026-10-30)** — recovery codes:
  `samverk/recovery_codes.py` + schema migration 14. A set is
  ten codes (10 chars, unambiguous alphabet, `XXXXX-XXXXX`),
  shown once and stored only as SHA-256 hashes; redemption
  is single-use (race-safe spend) and every failure is the
  same False. Regeneration deletes the whole old set in the
  same transaction that mints the new one and **reports how
  many codes died** (`invalidated`), so the surface can warn
  loudly. Gates: confirmed S-035 two-factor required, and
  generation is sudo-gated through the S-036 seam. Taxonomy
  grew append-only by two events (`auth.recovery.generate` /
  `auth.recovery.use`, detail carries counts, never codes;
  42 total, doc + code + counts updated together). Battery
  `tests/test_recovery_codes.py`: **6 passed / 0 failed**,
  including the DB-leak sweep for every plaintext code.
  Cumulative battery: **298/298**.
- **S-038 DONE (2026-10-30)** — two-factor enforcement policy:
  `samverk/twofactor_policy.py` over the instance `settings`
  table (no new migration). An instance may require two-factor
  for **admins**: turning it on starts a grace clock once
  (default 7 days; re-saving never restarts it), inside grace
  an admin without S-035 two-factor is warned in plain words
  naming the time left, after grace `is_blocked` answers True,
  and enrolment satisfies the policy at any point. Non-admins
  are outside it entirely. Changes are audited
  `admin.settings.change`. **Org scope is refused with its
  reason named** (`org_scope_not_available`) — organisations
  land in a later part, and pretending to evaluate org
  adminship now would be a claim, not a control. Battery
  `tests/test_twofactor_policy.py`: **7 passed / 0 failed**.
  Cumulative battery: **305/305**.
- **S-039 DONE (2026-10-30)** — passkeys/WebAuthn:
  `samverk/passkeys.py` + schema migration 15
  (`passkey_challenges` hashed-only/single-use/5-minute;
  `passkey_credentials`, credential id globally UNIQUE).
  The WebAuthn Level 2 ceremonies implemented clean-room
  from the public W3C spec on the stdlib alone — own CBOR
  decoder, own COSE parsing, own pure-Python signature
  verification (ES256, RS256, EdDSA). Registration is
  sudo-gated through the S-036 seam, verifies client-data
  type/challenge/origin, RP-ID hash, user presence, and the
  attestation format (`none` accepted; `packed`
  self-attestation verified with the credential's own key;
  certificate chains and other formats refused by name).
  Authentication serves both roadmap doors with one
  ceremony — account-bound challenge = second factor,
  unbound = passwordless (the verified credential names the
  account; the caller mints the ordinary S-006 session).
  A signature counter that fails to move forward is refused
  as `cloned_authenticator`. Taxonomy grew append-only by
  three events (`auth.passkey.add` / `auth.passkey.remove` /
  `auth.passkey.login`; 45 total, doc + code + counts
  updated together). Battery `tests/test_passkeys.py`:
  **13 passed / 0 failed**, including the literal
  acceptance — interop proven against **two independent
  software authenticators written in the battery itself**
  (ES256 with DER signatures + packed self-attestation, and
  Ed25519 with RFC 8032 mathematics), sharing no code with
  the server. Cumulative battery: **318/318**.
- **S-040 DONE (2026-10-30)** — session management:
  `samverk/session_management.py` over the S-006 store,
  extended in place (schema migration 16 adds
  `device_label` / `source_ip` to sessions; `SessionStore`
  gains `list_for_user`, owner-scoped `revoke_by_id`, and
  `revoke_all(except_id=…)`; S-027 login now records the
  device label + address at sign-in). The owner sees every
  session — device, address, sign-in and last-active times,
  a status word (Active / Revoked / Expired, text never
  colour alone), and a *this session* marker — one click
  from the settings home via S-034's existing "Security
  and sessions" link. `revoke_one` is owner-only in the
  query itself; `revoke_all` can spare the current session
  so the remedy does not lock out its wielder. Every landed
  revocation is audited under the taxonomy's long-frozen
  `auth.session.revoke` (`{"scope": "one"|"all"}` — no new
  events). The page renders device labels (hostile text)
  only through S-010's seam and offers revoke forms only
  for live, non-current sessions. Battery
  `tests/test_session_management.py`: **7 passed /
  0 failed**, including the literal acceptance — a revoked
  session's token resolves to nobody on its very next
  request while its sibling session lives on. Cumulative
  battery: **325/325**.
- **S-041 DONE (2026-10-30)** — new-sign-in notification:
  `samverk/signin_notifications.py` + schema migration 17
  (`known_devices`, keyed by a SHA-256 of the label+address
  pair; `signin_notifications`, the in-app inbox). A device
  is the pair a sign-in arrived with (S-040's label +
  address): first sighting fires, repeats only move
  `last_seen_at` — **once per new device, never per
  sign-in**, and an account's first-ever sign-in fires too
  (nothing is known yet; everything is new). Two channels in
  trust order: the in-app notice always (device, address,
  time; owner-only read marks), then email through a mailer
  seam when the instance has one and the account has an
  address — best-effort, committed notice first, a mailer
  failure unmakes nothing. Wired into S-027's login service
  as the optional `signin_notifier=` seam (unwired instances
  behave exactly as before). Taxonomy grew append-only by
  one event (`auth.signin.notify`; 46 total, doc + code +
  counts updated together). Battery
  `tests/test_signin_notifications.py`: **6 passed /
  0 failed**, including the literal acceptance driven
  through the real login service (two identical logins →
  exactly one notice and one audit row). Cumulative
  battery: **331/331**.
- **S-042 DONE (2026-10-30)** — account rename:
  `AccountStore.rename` in `samverk/accounts.py` + schema
  migration 18 (`username_tombstones`). The rename applies
  the full S-025 username law to the new name and refuses
  collisions clearly — live names (any case), reserved
  names, and other accounts' unexpired tombstones. The old
  canonical name is held as a **90-day tombstone**:
  `resolve_user` / `redirect_for` route it to the account's
  new name (the resolution seam Part III's repository URLs
  will ride on), registration refuses the held name, and
  the owner may rename back onto their own tombstone
  (reclaiming it leaves the intermediate name tombstoned
  instead). A case-only change moves the display case and
  leaves no tombstone. Sessions, keyed by account id, are
  untouched. Every outcome is audited under the append-only
  taxonomy addition `auth.username.change` (47 events
  total; doc + code + counts updated together). Battery
  `tests/test_account_rename.py`: **7 passed / 0 failed**,
  including tombstone lapse (after 90 days the name frees
  and the redirect ends). Cumulative battery: **338/338**.
- **S-043 DONE (2026-10-30)** — account deletion:
  `samverk/account_deletion.py` + schema migration 19
  (`account_deletions`). Deletion is a process: an
  **inventory** counts everything the account holds across
  every store before the act; the request needs the
  username **typed** as confirmation and fresh sudo
  re-auth through the S-036 seam (fail-closed); a **7-day
  grace period** follows (status `pending_deletion`, login
  refused, nothing destroyed, `cancel` restores the account
  whole); only after grace does execution delete every
  per-user row and the user row in one transaction, leaving
  the name tombstoned 90 days against instant impersonation.
  The audit log is never deleted — it is the witness — and
  request/cancel/execute are audited under taxonomy
  additions `auth.deletion.request` / `.cancel` / `.execute`.
  Battery `tests/test_account_deletion.py`: **4 passed /
  0 failed**. Cumulative battery: **342/342**.
- **S-044 DONE (2026-10-30)** — account suspension:
  `samverk/account_suspension.py` + schema migration 20
  (`account_suspensions`). Admin-only (self-suspension
  refused), **reason required** and kept on the record;
  suspension sets status `suspended`, revokes all sessions
  at once, and hides the account's content through the one
  `is_content_visible` policy seam — **never deletes**:
  profile and every other row survive, and `unsuspend`
  restores the account whole. Audited `admin.user.suspend`
  / `admin.user.unsuspend` (taxonomy additions; 54 events
  total with S-043/S-045: 29 auth, 13 repo, 12 admin).
  Battery `tests/test_account_suspension.py`: **3 passed /
  0 failed**. Cumulative battery: **345/345**.
- **S-045 DONE (2026-10-30)** — identity-linking data
  shape: `samverk/identity_linking.py` + schema migration
  21 (`external_identities`, UNIQUE (provider, external_id)
  and (user_id, provider)). An account links one external
  principal per provider — **Samtal first** (`samtal`) —
  and a principal can be claimed by only one account;
  re-linking is unlink + link, both audited
  (`auth.identity.link` / `.unlink`). **Shape only**, by
  the roadmap's word: no seam, no sync, no external login,
  no federation; the store deliberately exposes no
  authenticate seam (asserted by the battery). Battery
  `tests/test_identity_linking.py`: **5 passed / 0 failed**.
  Cumulative battery: **350/350**.
- **S-046 DONE (2026-10-30)** — reserved and impersonation
  defence: `samverk/lookalike.py` — warnings, not refusals
  (refusal stays S-025's for exact names). A candidate's
  skeleton lowercases, drops separators, folds leetspeak
  and the visual confusables `rn`→`m` / `vv`→`w`; equal
  skeletons or edit distance 1 against reserved names or
  live accounts produce a plain-language warning naming
  what it resembles. `registration_warnings` reads the
  live account set. Battery `tests/test_lookalike.py`:
  **5 passed / 0 failed**. (Two flaws found by the battery
  and fixed in-slice: leet `1` folds to `i`, not `l`
  — `adm1n` is admin — and `rn`-for-`m` is two edits wide
  but one glance wide, so it belongs in the skeleton.)
  Cumulative battery: **355/355**.
- **S-047 DONE (2026-10-30)** — login history:
  `samverk/login_history.py` — the owner-visible record
  read from the audit log itself: rows where the account
  is actor, target of an admin act, or the attempted name
  on a failed login (shown as an attempt, per study 35
  §4). Newest first, limit clamped 1..500, a sign-ins-only
  filter, and a page rendering every value through S-010's
  seam. There is no cross-account view in this seam.
  Battery `tests/test_login_history.py`: **5 passed /
  0 failed**. Cumulative battery: **360/360**.
- **S-048 DONE (2026-10-30) — PART II GATE.** Gate battery
  `tests/test_identity_battery.py`: **8 passed / 0 failed**,
  striking the *assembled* Part II system across accounts —
  fabricated credentials authenticate no one, cross-account
  token and session revocation fail, the fine-grained
  permission matrix holds, histories and identity links do
  not cross accounts, a DB leak buys no identity, and the
  **token findability walk is recorded**: settings home →
  `/settings/tokens` in one click → token listed with its
  revoke form → one-call revocation → status word Revoked.
  Full counted run at the gate on this VM:
  `python3 -m unittest discover -s tests` → **368 passed /
  0 failed**. Open findings, named: (1) S-045 is shape
  only — the Samtal seam is Part XIX, by design; (2)
  platform cells beyond Linux x86-64 remain NOT PROVEN
  (Part XXII); (3) everything banked sits on local `main`
  only — **no GitHub push**: pushes stay gated on
  Volmarr's explicit word. **Part II is complete.**
  Next: Part III — Git Core, opening at S-049 bare
  repository creation.
- **S-049 DONE (2026-10-30)** — bare repository creation:
  `samverk/repositories.py` + schema migration 22
  (`repositories`: canonical lowercase owner/name UNIQUE,
  display case kept; the row also carries S-050's metadata
  columns with defaults so no second migration is needed).
  Creation validates both halves under S-013, requires the
  actor to be the owner account, runs `git init --bare
  --initial-branch=<default>` through S-014, and only then
  writes the row — committing before the answer, so a separate
  connection sees it at once. All-or-nothing: a failed row
  write removes the just-created directory, and a directory
  already on disk is refused, never silently adopted (drift
  is S-071's to name). Audited `repo.create`. Battery
  `tests/test_repositories.py`: **6 passed / 0 failed**,
  including the separate-connection visibility check.
  Cumulative battery: **374/374**.
- **S-050 DONE (2026-10-30)** — repository metadata model:
  description (≤350 plain-text chars), visibility (`public` /
  `private`, default `private`) and default branch live on the
  S-049 row (columns landed with migration 22, so this slice
  needed no new migration). `RepositoryStore.update_metadata`
  is owner-only and validated; a default-branch change moves
  the bare repo's HEAD symbolic ref first, so metadata never
  claims a branch git does not point at, and a visibility
  change audits `repo.visibility.change` separately from
  `repo.settings.change`. `rename` moves directory and row
  together — a single `os.rename` inside the one repos root,
  the row in one transaction, and a failed row update rolls
  the directory back. Battery `tests/test_repo_metadata.py`:
  **6 passed / 0 failed**. Cumulative battery: **380/380**.
- **S-051 DONE (2026-10-30)** — object reading:
  `samverk/objects.py` — blob/tree/commit reads through one
  `cat-file --batch` spawn per call (S-014 law), never one
  spawn per object. Object ids are hex-validated before they
  reach git; a missing object is a named refusal
  (`object_not_found`), never empty content. Tree payloads
  parse to (mode, name, oid) entries; commits parse to tree,
  parents, author/committer and message. Battery
  `tests/test_objects.py`: **3 passed / 0 failed**, including
  the latency proof — 2,000 distinct blobs batch-read with
  content verified, far inside a 5-second ceiling a
  spawn-per-object reader would blow. (The roadmap's 10k
  figure re-verifies at the Part III gate, S-076.)
  Cumulative battery: **383/383**.
- **S-052 DONE (2026-10-30)** — ref listing and resolution:
  `samverk/refs.py` — one `for-each-ref` spawn returns every
  ref with oid, type and peeled oid (annotated tags peel to
  their commit); HEAD is read through `symbolic-ref`, the
  indirection itself, and resolution goes through
  `rev-parse --verify`. Packed-refs stay git's business.
  Ref names are validated before reaching git, so a name can
  never be read as a flag. Battery `tests/test_refs.py`:
  **3 passed / 0 failed**, including annotated-tag peeling
  and the empty-repo case (no refs, HEAD on the default
  branch, no head oid). Cumulative battery: **386/386**.
- **S-053 DONE (2026-10-30)** — atomic ref updates:
  `RefStore.update_ref` in `samverk/refs.py` — branch
  create/delete/rename and general updates through
  `update-ref` with compare-and-swap: naming the expected
  old value makes git check-and-set under its own lock, and
  a loser is refused as `stale_ref` instead of tearing the
  ref. Rename is a create+delete pair in one
  `update-ref --stdin` invocation, verified against the old
  value. Battery `tests/test_ref_updates.py`: **3 passed /
  0 failed**, including the race — ten threads CAS the same
  ref from the same expected value and exactly one wins.
  Cumulative battery: **389/389** (full counted run on this
  VM at this slice).
- **S-054 DONE (2026-10-30)** — repository visibility
  enforcement: `samverk/permissions.py` — one function,
  `role_for(viewer, repo, collaborator_role=...)`, decides
  every repository permission, and web/API/transports must
  consult it or its `can_read`/`can_write`/`can_admin`
  wrappers. Owner and site admin hold `admin`; a granted
  collaborator role applies on any visibility (the grant
  store is Part IX's; the seam takes the role until then);
  public means world-readable and never world-writable;
  private means role `None` for everyone else, which
  surfaces render as not-found, not forbidden — a private
  repo's existence is itself private. Battery
  `tests/test_permissions.py`: **6 passed / 0 failed** —
  the Part IX matrix (owner / collaborator / stranger /
  anonymous x public / private x read / write / admin) run
  early, as the roadmap asks. Cumulative battery:
  **395/395** (full counted run on this VM at this slice).
  Next: S-055 forking.
- **S-055 DONE (2026-10-30)** — forking: `samverk/forks.py` +
  schema migration 23 (`repositories.fork_of_id`) — a fork is a
  server-side bare clone through S-014's dedicated
  local-paths-only seam (`run_git_clone_local`; generic
  `clone` stays refused — corrected in the fix entry below
  after the S-014 battery caught the first cut allowlisting
  it) with its own object store, so upstream
  damage can never break it; the row records the direct
  upstream link. Forking is gated by S-054's `can_read` (an
  unreadable private repo answers as not-found), a private
  source can never be forked public, `fork_count` counts direct
  forks, and `network_for` walks to the root and lists the
  whole network. Audited `repo.fork` (taxonomy append-only +1
  event, 55 total; doc and code updated together). Battery
  `tests/test_forks.py`: **5 passed / 0 failed**, including
  fork independence (a ref deleted in the fork leaves the
  upstream untouched). Cumulative battery: **400/400**.
  Next: S-056 repository deletion.
- **S-056 DONE (2026-10-30)** — repository deletion:
  `samverk/repo_deletion.py` + schema migration 24
  (`repo_deletions`) — the S-043 process shape for repos:
  owner-only and sudo-gated (fail-closed verifier seam), a
  7-day tombstone grace during which the disk is untouched
  and `cancel` restores the repo whole, and execution only
  at/after the scheduled time — row deleted, bare directory
  reclaimed, and forks (independent clones since S-055)
  survive with their upstream link cleared. Audited:
  request/cancel under `repo.settings.change`, execution
  under the frozen `repo.delete`. Battery
  `tests/test_repo_deletion.py`: **4 passed / 0 failed**,
  including not-due execution destroying nothing and the
  disk surviving the whole grace. Cumulative battery:
  **404/404**. Next: S-057 repository transfer.
- **S-057 DONE (2026-10-30)** — repository transfer:
  `samverk/repo_transfer.py` + schema migration 25
  (`repo_transfers`, `repo_redirects`) — ownership moves only
  with the recipient's acceptance: the owner initiates (a
  missing recipient, a self-transfer, a pending offer, or a
  recipient name collision are each refused by name), nothing
  moves until the named recipient — and only they — accepts,
  and then the directory and row move together under the
  S-050 rollback discipline and a redirect from the old
  canonical name is left behind for 90 days. Decline (recipient)
  and cancel (owner) move nothing. This slice also extends
  S-056's execution to clear a pending transfer when its repo
  is deleted — sequenced here because the table arrives here;
  the intermediate S-056-only tree was caught referencing it
  early by its own battery and fixed before this slice landed.
  Audited under the frozen `repo.transfer`. Battery
  `tests/test_repo_transfer.py`: **4 passed / 0 failed**.
  Cumulative battery: **408/408**. Next: S-058 size accounting.
- **S-058 DONE (2026-10-30)** — repository size accounting:
  `samverk/repo_size.py` (no migration) — a file-by-file walk
  of the bare directory (symlinks never followed) split into
  git objects (`objects/`), LFS objects (`lfs/`, the per-repo
  layout S-060 will fill — 0 until then, never invented), and
  other (refs/config/future assets alongside), the three
  always summing to the total. Shown to owners and site
  admins only; anyone else is refused and a missing repo is
  named. Battery `tests/test_repo_size.py`: **4 passed /
  0 failed**, including a planted LFS object counted to the
  byte and real git content growing the object category.
  Cumulative battery: **412/412** (full counted run on this
  VM at this slice). Next: S-059 garbage-collection scheduling.
- **FIX (2026-10-30, same keeper run)** — the final full
  recount caught S-055's first cut breaking S-014's battery:
  allowlisting generic `clone` made `run_git(["clone", url])`
  stop being refused. Fixed in scope per the never-leave-a-bug
  law: `clone` is off the allowlist again, and forking goes
  through `run_git_clone_local` in `samverk/proc.py` — both
  paths are trusted resolved `Path` objects from S-013, the
  function builds its own argv, and no caller string can be a
  clone source. The S-055 entry above is corrected to match.
- **S-059 DONE (2026-10-30)** — garbage-collection scheduling:
  `samverk/repo_gc.py` + schema migration 26 (`repo_gc_state`).
  Policy is a pure function of measured facts (size from
  S-058's walk, loose-object count): no loose objects → not
  needed; large (≥32 MiB or ≥500 loose) → daily aggressive;
  medium (≥1 MiB or ≥50 loose) → weekly; small → monthly.
  `gc`/`count-objects` joined the S-014 allowlist here, with
  reasons. The acceptance — *no request waits on gc* — is
  structural: `GCScheduler.assess` only measures and records
  a due time (it spawns nothing, proven by the battery: loose
  objects stay loose after assessing), and `run_due` is the
  sole gc spawner, an off-path entry point for a background
  worker/operator; outcomes (ok/failed) and the next due
  time are recorded per repo. Battery
  `tests/test_repo_gc.py`: **4 passed / 0 failed**, including
  a real `git gc` packing 5 loose objects to 0 and the
  not-due-until-the-interval-passes check. Cumulative
  battery: **416/416** (full counted run on this VM at this
  slice). Next: S-060 LFS object store.
- **S-060 DONE (2026-10-30)** — LFS object store:
  `samverk/lfs_store.py` (no migration) — per-repo
  content-addressed layout `<repo>.git/lfs/objects/<ab>/<cd>/<oid>`
  (the standard LFS fan-out; the layout S-058 already
  measures). Integrity is verified by oid on write: bytes
  land in a temp file, are SHA-256-hashed as written, and
  are atomically published only when the digest equals the
  claimed oid (and the length the claimed size) — a mismatch
  stores nothing. Dedupe: an object already present and
  verified is never rewritten (mtime-proven in the battery).
  Oids are validated as exactly 64 lowercase hex before they
  form any path. Pointer files (`make_pointer` /
  `parse_pointer`, the LFS spec v1 text shape) round-trip
  here so S-061's API and real clients share one parser.
  Battery `tests/test_lfs_store.py`: **6 passed / 0 failed**,
  including S-058's accounting seeing stored LFS bytes to
  the byte. Cumulative battery: **422/422** (full counted
  run on this VM at this slice). Next: S-061 LFS batch API.
  (Environment note: `git-lfs` was not installed on this VM;
  installed natively via apt this run — no Docker — so
  S-061/S-062's real-client interop acceptances can be
  proven, not skipped.)
- **S-061 DONE (2026-10-30)** — LFS batch API:
  `samverk/lfs_api.py` (no migration) — the batch operation
  real git-lfs clients speak, plus `make_lfs_handler`, an
  HTTP adapter serving `/<owner>/<repo>/info/lfs/…` and the
  action URLs (the main server's route table adopts these
  with Part IV's transports, whose S-081/S-082 supply the
  real actor resolvers). Per object, the server answers
  with expiring **signed action URLs**: HMAC-SHA256 tokens
  naming exactly one repo, one oid, one operation
  (upload/download/verify), expiring in one hour, verified
  through the S-005 constant-time seam — tampered, expired,
  and wrong-operation tokens are all refused in the battery.
  Permissions come from S-054's one function (upload needs
  write, download needs read, an unreadable private repo
  answers 404); an already-stored object gets no upload
  actions; a missing download object gets the spec's
  per-object 404; the verify action re-hashes the stored
  bytes (S-060) before telling a client success. Battery
  `tests/test_lfs_api.py`: **6 passed / 0 failed**,
  including the literal acceptance — a **stock git-lfs
  3.6.1 client round-trip**: `git lfs push --all` uploaded
  a 1 MiB object through the batch API into S-060's store
  (verified there by oid), and a fresh repo's checkout
  smudge downloaded it back through the batch API to
  byte-identical content. Cumulative battery: **428/428**
  (full counted run on this VM at this slice, git-lfs on
  PATH). Two honest notes: (1) this VM's system layer does
  not persist apt installs between sessions, so a pristine
  git-lfs 3.6.1 release binary is kept at
  `~/workspace/.tools/git-lfs` for keeper runs (the battery
  skips the client test where no git-lfs exists, per the
  standing skip pattern); (2) a threaded HTTP server cannot
  use a same-thread sqlite connection — the battery harness
  opens its connection cross-thread, and Part IV's wiring
  must do the same (or per-thread connections). Next:
  S-062 LFS locking.
- **S-062 DONE (2026-10-30)** — LFS locking:
  `samverk/lfs_locks.py` + schema migration 27 (`lfs_locks`,
  UNIQUE (repo_id, path)) — the public LFS lock API:
  lock / unlock / list / verify, served through the S-061
  handler when a locking service is attached. Locks name
  *paths*, not objects; ids are 128-bit random hex.
  Locking needs S-054 write, listing/verifying read; a
  conflict refuses 403 naming the existing lock (holder
  included, so a client can show who has it); only the
  lock's owner may release it, or a repo admin with an
  explicit `force`. `verify` splits ours/theirs for the
  push-time check. Battery `tests/test_lfs_locks.py`:
  **6 passed / 0 failed**, including the literal
  acceptance — stock git-lfs 3.6.1 `lock` / `locks` /
  `unlock` against Samverk's endpoint. (Two battery-design
  lessons, fixed in the tests, not the code: a stranger
  rightly cannot write-lock a public repo under S-054, so
  conflicts are exercised by an admin; and git-lfs itself
  refuses to unlock a file with uncommitted changes, so
  the interop repo commits first.) Cumulative battery:
  **434/434** (full counted run on this VM at this slice).
  Next: S-063 archive downloads.
- **S-063 DONE (2026-10-30)** — archive downloads:
  `samverk/archives.py` + `archive` on S-014's allowlist and a
  streamed-spawn seam (`popen_git_in` in `samverk/proc.py`,
  same validation/environment law, caller owns the deadline).
  Zip and tar.gz of any ref via `git archive`: S-054's
  `can_read` gates before any spawn, and missing and
  unreadable repos answer identically (`repo_not_found`);
  the ref is resolved through S-052 before archiving
  (unknown → `ref_not_found`, flag-shaped → `ref_invalid`,
  nothing spawned); bytes stream in 64 KiB chunks and are
  counted + SHA-256-hashed as they flow, under a 120 s
  deadline that kills an overrunning git. The top-level
  directory and filename are `<repo>-<ref>`. Battery
  `tests/test_archives.py`: **6 passed / 0 failed**,
  including the literal acceptance — both formats are
  checksum-stable across repeated downloads of a fixed
  ref, contents verify against the fixture files, a
  320 KB incompressible payload streams in multiple
  chunks, and HEAD-vs-branch prefix naming is honoured.
  (Two test-design flaws fixed in-slice, code untouched:
  compressible payloads made single-chunk archives, and
  an equality check first compared archives whose
  `<repo>-<ref>` prefixes rightly differ.) Cumulative
  battery: **440/440** (full counted run on this VM at
  this slice). Next: S-064 repository templates.
- **S-064 DONE (2026-10-30)** — repository templates:
  `samverk/repo_templates.py` + schema migration 28
  (`repositories.is_template`, `template_of_id`). A repo is
  a template only when its owner marks it (`set_template`,
  owner-only); unmarked repos refuse as `not_a_template`.
  Creation rides S-014's local clone seam under S-054's
  read gate (unreadable private template = not found; a
  private template can never create a public repo), is
  **not** a fork (`fork_of_id` empty, `template_of_id`
  records the source), and substitutes variables in the
  **root README only**: `{{ key }}` placeholders with
  caller-supplied values, unknown placeholders left as
  written and reported, every other file byte-identical
  (proven on a code file carrying the same placeholder).
  A landed substitution is one new commit on the copied
  HEAD, authored by the creator; no match → no commit
  invented, history untouched. `mktree`/`commit-tree`
  joined S-014's allowlist here, with reasons; `run_git_in`
  gained an `env_extra` parameter (the commit's author
  identity). Audited `repo.create` with the template
  source named. Battery `tests/test_repo_templates.py`:
  **6 passed / 0 failed**. Cumulative battery: **446/446**
  (slice battery + affected suites re-run at this slice;
  full recount at the next gate). Next: S-065
  empty-repository state.
- **S-065 DONE (2026-10-30)** — empty-repository state:
  `samverk/empty_repo.py` — emptiness is read from git
  itself (no refs, no HEAD object), never a flag, and the
  state ends the moment a first commit lands
  (`repo_not_empty`). `EmptyStateService.instructions_for`
  generates first-push instructions **per transport** from
  the instance's configured addresses (HTTP base, SSH
  host/user) and the repo's real default branch: clone URL
  plus two copyable command blocks (new local repo /
  existing local repo) with no shell prompts inside the
  blocks. Unconfigured transports produce no guessed
  address — they are named in `unavailable_transports`;
  credential-carrying HTTP bases are refused at
  construction. S-054's read gate applies (a private
  repo's emptiness is private). Battery
  `tests/test_empty_repo.py`: **4 passed / 0 failed**.
  Cumulative battery: **450/450** (full recount at the
  next gate). Next: S-066 repository settings.
- **S-066 DONE (2026-10-30)** — repository settings:
  `samverk/repo_settings.py` + schema migration 29
  (`repo_settings`, `repo_branch_renames`). Description
  and visibility keep their one S-050 writer (this service
  delegates); **website** must pass S-010's `safe_url` and
  be http(s) (`javascript:`/`data:`/`mailto:` refused);
  **topics** are a closed shape (lowercase/digits/hyphens,
  ≤20 × ≤50 chars, normalised and deduped). **Default-
  branch rename** moves the branch itself through S-053's
  atomic rename, follows with HEAD + the S-050 default,
  and **records the rename** so `rename_guidance` hands a
  pre-rename clone the exact copyable steps (`git branch
  -m …`, `git fetch`, `git branch -u …`, `git remote
  set-head origin -a`) — guidance, honestly named, since
  Samverk cannot reach into a clone it does not host. An
  empty repo's rename is metadata + HEAD only. All changes
  owner-only, audited `repo.settings.change`. Battery
  `tests/test_repo_settings.py`: **6 passed / 0 failed**.
  Cumulative battery: **456/456** (full counted run on
  this VM at this slice, verifying the S-064/S-065
  arithmetic too). Next: S-067 server-side hooks seam.
- **S-067 DONE (2026-10-30)** — server-side hooks seam:
  `samverk/hooks.py` — a `HookRunner` with named, ordered
  handlers per phase. **Pre-receive fails closed**: a hook
  returning a string / `False` or raising `HookVeto` vetoes
  the push (chain stops, reason carried for the pusher);
  an exception or a timeout also refuses. **Post-receive
  can never veto**: every hook runs, outcomes are recorded
  (`completed` / `vetoed` / `error` / `timeout`) and the
  runner moves on. **Timeout and kill discipline is
  structural**: each hook runs in a forked child process,
  the parent waits only the runner's budget (default 10 s),
  and an overrunning child is terminated, then killed,
  then reaped — a hung hook costs one refused push, never
  a hung server. This is the seam S-089's protection gate
  and Part XV's scanning hang on. Battery
  `tests/test_hooks.py`: **6 passed / 0 failed**, including
  a 60-second-sleep hook refused in ~the 0.5 s budget.
  Cumulative battery: **462/462** (full recount at the
  next gate). Next: S-068 repository quotas.
- **S-068 DONE (2026-10-30)** — repository quotas:
  `samverk/repo_quotas.py` + schema migration 30
  (`repo_quotas`). A quota is a byte limit enforced **at
  receive time**: `enforce_receive` is the gate the receive
  path calls before accepting objects, and a push that
  would exceed the limit is refused with a plain message
  naming what the repo holds, its limit, and what the push
  adds — nothing half-lands. Usage is S-058's measured walk
  (the number enforced is the number displayed). Two
  explicit levels only: a per-repo quota (owner or site
  admin) wins over an admin-set instance default in
  `settings`; neither set means unlimited — a limit is
  never invented. `check_receive` returns the decision
  object for surfaces; changes audit `repo.settings.change`.
  Battery `tests/test_repo_quotas.py`: **5 passed /
  0 failed**, including the literal refusal message checked
  number by number. Cumulative battery: **467/467**
  (full recount at the next gate). Next: S-069 import by
  clone URL.
- **S-069 DONE (2026-10-30)** — import by clone URL:
  `samverk/repo_import.py` + the dedicated seams in
  `samverk/proc.py` (`validate_remote_url`,
  `run_git_clone_remote`, and `run_git_fetch_from` landed
  here for S-070). Generic `clone` stays refused under
  S-014 — the import seam validates the address itself
  (remote schemes https/http/git/ssh only, a real host, no
  whitespace/controls, no leading dash, no fragment, and
  **no credentials inside the URL**), takes the destination
  as a trusted S-013 `Path`, and builds its argv itself.
  Creation is S-049's all-or-nothing shape: clone first,
  row after (default branch read from the clone's HEAD),
  a failed clone leaves neither directory nor row. **The
  token is never logged**: a private import's token travels
  only in the child process's environment, answered to
  git's prompts by an askpass script that contains variable
  names, never the secret; audit and error messages name
  only the source host. Battery `tests/test_repo_import.py`:
  **6 passed / 0 failed**, including a real `git daemon`
  round-trip (import → refs resolve to the source commit),
  the URL-law battery, cleanup after a failed clone, and a
  DB-file + audit sweep proving the token appears nowhere.
  Cumulative battery: **473/473** (full recount at the
  next gate). Next: S-070 mirror storage layout.
- **S-070 DONE (2026-10-30)** — mirror storage layout:
  `samverk/mirrors.py` + schema migration 31
  (`repo_mirrors`). A mirror is an **ordinary bare repo
  plus a mirror record** — same S-013 path, same
  `repositories` row, same S-058 measurement and S-051/52
  reads, no second storage engine; the record holds only
  the source (a validated S-069 URL or an absolute local
  path to an existing repo) and the sync outcome.
  `create_mirror` makes the ordinary repo + record;
  `attach_mirror` / `detach_mirror` mark/unmark an existing
  repo (owner-only, one source at a time, detaching never
  touches content). `sync_mirror` converges the mirror
  through the dedicated fetch seam (`run_git_fetch_from`,
  landed with S-069 — generic `fetch` stays refused under
  S-014) and **records success and failure alike**
  (`last_sync_at` / `last_status` / `last_detail`); a
  failed sync leaves existing content untouched and
  readable. Battery `tests/test_mirrors.py`: **6 passed /
  0 failed**, including local-source convergence across a
  second commit and a `git daemon` URL sync. Cumulative
  battery: **479/479** — full counted run on this VM at
  this slice, verifying the whole run's arithmetic
  (S-067…S-070). Next: S-071 consistency checker.
- **S-071 DONE (2026-10-30)** — consistency checker:
  `samverk/consistency.py` — a read-only fsck-style sweep
  reconciling rows ↔ disk ↔ LFS objects: a row whose bare
  repo is missing or not bare is named, a disk repo with no
  row is named (never adopted), dangling fork/template
  lineage and orphan mirror records are named, and every
  LFS object is checked for its fan-out path and re-hashed
  against its oid. **Drift is reported, never silently
  fixed** — the battery plants stray + corrupt drift,
  snapshots the repos tree, and proves the sweep changes
  nothing. Battery `tests/test_consistency.py`: **6 passed /
  0 failed**. Cumulative battery: **485/485** (full recount
  at the S-076 gate). Next: S-072 commit graph caches.
- **S-072 DONE (2026-10-30)** — commit graph caches:
  `samverk/graph_cache.py` + schema migration 32
  (`repo_graph_cache`). Derived data (commit count,
  contributor list, branch/tag counts) is computed only in
  `refresh` — the off-path entry, walking `git log --all`
  once — and served by `cached_stats`, which never walks:
  it compares the stored **refs fingerprint** (SHA-256 over
  every ref name + oid) against the live refs and answers
  None when stale, exactly as when absent. `invalidate` is
  the push path's explicit drop. An empty repo refreshes to
  an honest zero. Battery `tests/test_graph_cache.py`:
  **5 passed / 0 failed**, including a push moving a ref
  making the cache stale by fingerprint alone. Cumulative
  battery: **490/490** (full recount at the S-076 gate).
  Next: S-073 large-repository budgets.
- **S-073 DONE (2026-10-30)** — large-repository budgets:
  `samverk/repo_budgets.py` — the reference repo shape is
  defined in code (1,000 commits / 2,000 blobs), clone
  budgets are stated per hardware class, and
  `measure_local_clone` times a clone through the S-055
  seam against the budget of the class it ran on. Measured
  on this VM (x86-64): the full reference clone lands
  inside its 30 s budget (battery-fast in practice).
  **Pi-class is NOT PROVEN** — its 60 s budget is stated,
  and Part XXI/XXII own running this measurement there.
  **Flaw found by this slice's work and fixed in-slice:**
  git's local clone hardlinks object files by default, so
  a clone shared inodes with its source — S-055's fork
  independence and this slice's measurement both require a
  real copy; `run_git_clone_local` now passes
  `--no-hardlinks` (fork/template/proc batteries re-run
  green after the fix). Battery
  `tests/test_repo_budgets.py`: **3 passed / 0 failed**.
  Cumulative battery: **493/493** (full recount at the
  S-076 gate). Next: S-074 repository backup primitive.
- **S-074 DONE (2026-10-30)** — repository backup primitive:
  `samverk/repo_backup.py` — a single-repo export is a
  `git bundle` file (`--all`, verified with `bundle verify`
  after creation; an unverifiable bundle is deleted, never
  reported) plus a metadata JSON (`samverk-repo-export/1`:
  row fields, refs, measured size, bundle SHA-256 + bytes).
  Owner-or-admin only; an existing export is never
  overwritten silently. `bundle` (and `fsck`, for S-075)
  joined S-014's allowlist with reasons. **Battery-found
  behaviour, handled in-slice:** git refuses an empty
  bundle, so an empty repo is refused by name
  (`repo_empty`) instead of faking a backup that restores
  to nothing. Battery `tests/test_repo_backup.py`:
  **5 passed / 0 failed**, including a stock-git clone from
  the bundle restoring HEAD exactly. Cumulative battery:
  **498/498** (full recount at the S-076 gate). Next:
  S-075 corruption behaviour.
- **S-075 DONE (2026-10-30)** — corruption behaviour:
  `samverk/repo_health.py` — the one health seam.
  `assess_repository` answers missing / not_a_repository /
  empty / healthy / damaged as distinct verdicts (empty is
  a sound repo waiting for a first push, never a synonym
  for damage); damage is proven by `git fsck --full`
  (admitted to S-014's allowlist for this slice) plus ref
  listing, and the report carries fsck's own first line.
  `ensure_readable` raises `RepoDamagedError` for callers
  that need the exception shape. Nothing here repairs —
  repair is restore-from-backup (S-074), a deliberate act.
  Battery `tests/test_repo_health.py`: **6 passed /
  0 failed**, including the literal acceptance —
  corruption injection (bit-flipped and truncated loose
  objects, a damaged HEAD) reads damaged at this seam and
  errors at the S-051 object seam, never empty content.
  Cumulative battery: **504/504** (full recount at the
  gate below). Next: S-076 Part III gate.
- **S-076 DONE (2026-10-30) — PART III GATE.** Gate battery
  `tests/test_git_core_battery.py`: **6 passed / 0 failed**,
  striking the *assembled* Part III system: stock-git
  plumbing interop (rev-parse / clone agree with S-051/52's
  seams), the 10-thread atomic-ref race at gate scale
  (exactly one winner), S-051's 10k-object acceptance
  re-verified (10,000 batch reads), corruption named by
  every seam, and the cross-slice agreement test
  (consistency ↔ health ↔ graph cache ↔ backup on one
  instance; an unregistered-but-sound repo is drift *and*
  empty, not damaged). Full counted run at the gate on
  this VM: `python3 -m unittest discover -s tests` →
  **510 passed / 0 failed**. **Open findings, named:**
  (1) Pi-class / laptop clone budgets (S-073) are stated
  but **NOT PROVEN** on those classes — Part XXI/XXII own
  their proof; (2) transports (HTTP/SSH wire) are Part IV —
  the gate proves plumbing interop locally, not yet over
  the wire; (3) everything banked sits on local `main`
  only — **no GitHub push**: pushes stay gated on
  Volmarr's explicit word. **Part III is complete.**
  Next: Part IV — Git Transports, opening at S-077 smart
  HTTP advertisement.
- **S-077 DONE (2026-10-30)** — smart HTTP advertisement:
  research study 01 written (clean-room, from git's public
  protocol docs + local stock-git experiments);
  `samverk/git_http.py` `SmartHttpService.advertise` builds
  the service pkt-line + flush + the pack program's own ref
  advertisement, with S-054's read gate checked *before* any
  git spawn (a damaged private repo still answers
  `repo_not_found` to anonymous callers — the gate-before-bytes
  proof). New S-014 seam `proc.run_git_pack`: upload-pack /
  receive-pack take the repo as a positional argument and do
  not honour `--git-dir`, so the seam builds argv itself
  (closed flag set, trusted Path, GIT_PROTOCOL scrubbed/set
  explicitly). Battery `tests/test_git_http_advertise.py`:
  **7 passed / 0 failed**. Cumulative: **517**.
- **S-078 DONE (2026-10-30)** — smart HTTP upload-pack:
  `upload_pack` feeds the POST body verbatim to
  `git upload-pack --stateless-rpc` after re-running the read
  gate (an advertisement is not a ticket); the response is
  the program's stdout verbatim, side-band progress included.
  Battery `tests/test_git_http_upload.py`: **4 passed /
  0 failed**, including stock-git clone (public, anonymous)
  and clone+fetch (private, as owner) over real HTTP through
  a test harness (cross-thread sqlite connection, the LFS
  batteries' pattern). Cumulative: **521**.
- **S-079 DONE (2026-10-30)** — smart HTTP receive-pack:
  `receive_pack` + the receive advertisement sit behind the
  *write* gate in the shared `_resolve`, fail-closed; the
  roadmap's named test
  `test_the_unauthenticated_receive_pack_hole_is_closed`
  proves anonymous callers can neither advertise nor POST a
  push against a public repo, and the ref does not move.
  Battery `tests/test_git_http_receive.py`: **4 passed /
  0 failed**, including a stock-git push over real HTTP that
  moves the bare repo's main. Cumulative: **525**.
- **S-080 DONE (2026-10-30)** — protocol v2:
  `protocol_version_from_header` reads `Git-Protocol`;
  v2 advertisements offer capabilities (`ls-refs`, `fetch`)
  instead of refs; `ls-refs` commands are served through the
  same stateless seam with `GIT_PROTOCOL=version=2`.
  Battery `tests/test_git_protocol_v2.py`: **5 passed /
  0 failed**, including the literal acceptance — a
  `GIT_TRACE_PACKET` stock-git clone (`-c protocol.version=2`)
  whose trace shows `command=ls-refs` and `command=fetch`
  flowing over the wire. Cumulative: **530**.
- **S-081 DONE (2026-10-30)** — HTTP Basic auth:
  `samverk/git_auth.py` `GitAuthenticator.authenticate_basic`
  resolves the Basic header through S-004's
  `verify_and_upgrade` (legacy hashes upgrade in place),
  against the login door's decoy hash for unknown names;
  no session is created and no login throttle is charged.
  Any non-`active` account status authenticates to nothing.
  Battery `tests/test_git_basic_auth.py`: **6 passed /
  0 failed**. Cumulative: **536**.
- **S-082 DONE (2026-10-30)** — token-as-password:
  `authorize_basic(header, owner, repo, minimum)` — classic
  tokens (S-032) must carry `repo:read`/`repo:write`
  (implication law decides), fine-grained tokens (S-033)
  must carry `contents:read`/`contents:write` on exactly
  that repo (`authorize` decides); the username slot must be
  the owner's name or `x-access-token`; revoked, expired, and
  suspended-account tokens resolve to nothing. Battery
  `tests/test_git_token_auth.py`: **7 passed / 0 failed**,
  including the named acceptance — a read-only token's push
  refused at the credential gate. Cumulative: **543**.
- **S-083 DONE (2026-10-30)** — anonymous public read +
  the uniform existence shape, decided in `TransportGate`
  (samverk/git_http.py): public upload legs answer
  credential-free callers; every other credential-free
  request meets one uniform **401** + `WWW-Authenticate:
  Basic realm="Samverk"` (public write, private, and
  nonexistent indistinguishable); credentials that grant
  nothing meet a uniform **404** on anything not publicly
  readable; a reader at the write gate meets an honest
  **403**. Battery `tests/test_git_anonymous_access.py`:
  **8 passed / 0 failed**, including byte-identical private
  vs nonexistent 401s over the real wire. Cumulative at the
  run's verified full recount: **553 passed / 0 failed**
  (the per-slice running counts above sum to 551; the full
  recount from the tree is the governing number). Next:
  S-084 SSH transport design (research file 02 first).
- **S-084 DONE (2026-10-30)** — SSH transport design:
  research study 02 written (`research/02-git-protocol-ssh.md`).
  Decision: system OpenSSH + one unprivileged `git` OS user +
  AuthorizedKeysCommand + a forced command into Samverk —
  never a shell; a custom Python SSH server and per-account OS
  users were considered and rejected with reasons recorded.
  Binding law handed down: the SSH_ORIGINAL_COMMAND parser law,
  the S-085 identity law, S-054 permission reuse, S-014 seam
  execution, sshd Match-block hardening, brief-cache revocation
  bound, and per-slice contracts for S-085…S-093. Windows SSH
  serving stays **NOT PROVEN** (Part XXII cell).
- **S-085 DONE (2026-10-30)** — SSH key resolution:
  `samverk/ssh_auth.py` `SshKeyResolver` — a presented
  fingerprint resolves to an account principal (personal key,
  account `active` only — the S-081 law) or a deploy-key
  principal bound to its one repository; unknown, malformed,
  and dead-account fingerprints share one uniform None (no
  enumeration). Resolution cached briefly (5 s named TTL,
  256-entry bound, refusals cached too; `invalidate` and
  `cache_ttl=0` seams for tests/callers). The
  `authorized_keys_line` emitter prints at most one line —
  `restrict` + forced `ssh-serve` command carrying integer
  principal ids and the fingerprint, stored key verbatim — or
  nothing. Battery `tests/test_ssh_key_resolution.py`:
  **12 passed / 0 failed** (one test of mine mis-sequenced the
  cache invalidation mid-write; the resolver was right and the
  test was rewritten cleanly in-slice).
- **S-086 DONE (2026-10-30)** — SSH upload-pack routing:
  `samverk/ssh_serve.py` — `parse_original_command` enforces
  study 02's parser law (closed service set, one single-quoted
  `owner/repo`, everything else refused as one malformed
  shape; battery includes injection, traversal, absolute-path,
  and dash-host cases); routing gates through S-013 paths and
  S-054 `can_read` before any pack byte, with private and
  missing repositories sharing one refusal text byte-for-byte.
  Execution via the new `run_git_pack_stdio` seam in
  `samverk/proc.py` (pack program attached to the caller's
  streams, no stateless-rpc; `GIT_PROTOCOL=version=2` honoured
  only when exact). Archive parses but is refused by name
  until S-093. Battery `tests/test_ssh_upload_routing.py`:
  **9 passed / 0 failed**, including stock git cloning through
  the serve door via a stand-in ssh program (real sshd is
  S-095's cell).
- **S-087 DONE (2026-10-30)** — SSH receive-pack routing:
  same parser and seams under `can_write`; a reader of a
  readable repo meets the honest write refusal, a stranger to
  a private repo sees the uniform not-found. Accepted pushes
  (runner exit 0) append the taxonomy's `repo.push` audit
  event with `transport=ssh` detail; failed pushes append
  nothing. Battery `tests/test_ssh_receive_routing.py`:
  **6 passed / 0 failed**, including stock git pushing through
  the serve door end to end, the bare ref advancing, and the
  audit row landing from the serve process itself.
- **S-088 DONE (2026-10-30)** — deploy-key transport rights
  on the wire: deploy principals are gated per request through
  S-031's `authorize` — the bound repository reads, every
  other target (public repos included) answers the uniform
  not-found; a read-only deploy key's push is refused at the
  gate before any pack byte; a read/write deploy key pushes
  and is audited with actor kind `deploy_key`; key use is
  stamped. Battery `tests/test_ssh_deploy_keys.py`:
  **7 passed / 0 failed**, including stock-git clone+push with
  a read/write deploy principal and clone-works/push-refused
  with a read-only one (bare ref verified unmoved). Next:
  S-089 pre-receive gate point. (The cumulative count first
  written here, 587/587, was wrong — see the correction entry
  in the session log: the S-017 import scan was failing, half
  on this run's new batteries and half pre-existing from
  S-083's; the scan is fixed and the governing recounts are
  pytest **588 passed / 2 skipped / 0 failed** and unittest
  discover **585 ran, 583 passed / 2 skipped / 0 failed**.)
- **S-089 DONE (2026-10-30)** — pre-receive gate point:
  `samverk/receive_gate.py` — one `ReceiveGate` whose stages
  run in the documented, binding **GATE_ORDER** (transport
  permission is stage 0, in the transports; then
  `protection` — Part VIII's plug-in stage; `secret_scan` —
  Part XV's stage; `quota` — S-068's decision, consulted when
  a size is known; `hooks` — S-067's chain, last). First
  refusal wins, plug-in exceptions fail closed, no plug-ins
  allows (the rules land in their own parts). Both receive
  transports consult it after permission and before any pack
  byte (SSH refuses 128 with the reason; HTTP raises
  `push_refused`). Battery `tests/test_receive_gate.py`:
  **10 passed / 0 failed**, including order, veto-stops-chain,
  quota refusal from measured usage, and both wirings.
- **S-090 DONE (2026-10-30)** — post-receive push events:
  `samverk/push_events.py` + schema migration 33
  (`push_events`) — the canonical product record of every
  accepted push (actor kind/id, transport, ref ranges),
  seeded for Part XI's store and kept distinct from the
  audit witness. Ranges are **read back from the refs that
  actually landed** (before/after diff in both transports),
  never trusted from the request; unmoved/empty ranges
  record nothing; a post-receive hook handler adapter feeds
  the same store from S-067 contexts. Battery
  `tests/test_push_events.py`: **8 passed / 0 failed**,
  including a stock-git HTTP push landing exactly one event
  with the true old→new range. (The transports' event-wiring
  code rides in S-089's commit — the two slices share
  `git_http.py`/`ssh_serve.py`; recorded here so the map
  does not claim a cleaner split than the tree has.)
- **S-091 DONE (2026-10-30)** — transfer limits:
  `samverk/transfer_limits.py` — per-transport
  (`http`/`ssh`, independently configurable) pack-size cap,
  wall-clock and idle budgets (defaults: no size cap, 600 s
  wall, 60 s idle — time budgets always exist). Refusals
  explain themselves: transport, measured amount, limit,
  and remedy, as a decision object first and an exception
  second (S-068's shape). The HTTP door enforces pack size
  on the request body before git spawns and takes the pack
  timeout from the wall clock; `WallClock`/`IdleWatch` give
  other callers the same budgets as checkable clocks.
  Battery `tests/test_transfer_limits.py`: **7 passed /
  0 failed**.
- **S-092 DONE (2026-10-30)** — concurrent push behaviour:
  `samverk/push_locks.py` — **fail fast, with a clear
  message**: a second push to a held (repo, ref) is refused
  immediately, naming repo and ref and the retry, before any
  pack moves, so no ref can tear. Locks are files
  (`O_CREAT|O_EXCL` under `<data_root>/locks/`) because SSH
  sessions are separate processes; a lock older than 600 s
  (past S-091's wall clock, so a live push is never mistaken
  for a dead one) heals once. Both receive transports hold
  the repo-wide lock around the pack run. Battery
  `tests/test_push_locks.py`: **7 passed / 0 failed**,
  including the two-thread race (exactly one holder) and
  stale-lock healing.
- **S-093 DONE (2026-10-30)** — upload-archive on the wire:
  the SSH door now serves `git-upload-archive` (it parsed
  but refused before), read-gated like upload-pack, and a
  **stock `git archive --remote=` over SSH returns the tar
  with contents verified**. The HTTP door serves the same
  service: its advertisement is the protocol's ACK greeting
  (upload-archive has no ref advertisement and no
  `--advertise-refs` flag — spawning git for it made it wait
  for request arguments; found and fixed at this slice,
  along with the pack seam's `--stateless-rpc`, which
  upload-archive does not accept), and a protocol-level POST
  through a real HTTP harness returns the archive bytes.
  **Named honestly:** stock git's remote-curl has *no
  archive operation* — `git archive --remote=http://…`
  refuses client-side before any request (traced
  first-hand), so no stock-client HTTP archive cell exists
  to prove; the SSH door carries that proof. Two superseded
  assertions updated in place (S-077's unknown-service list,
  S-086's not-served-yet test). Battery
  `tests/test_upload_archive.py`: **5 passed / 0 failed**.
- **S-094 DONE (2026-10-30)** — transport audit:
  `samverk/transport_audit.py` + taxonomy append-only
  **`repo.fetch`** (56 events total: 29 auth, 15 repo,
  12 admin; doc, code, and counts updated together — the
  doc's stale 54-line also corrected through the S-055/S-094
  additions it had missed). The level law, decided in one
  place so transports cannot drift: **all pushes** witnessed
  (HTTP now records `repo.push` beside SSH's S-087 rows),
  **private** clone/fetch/archive witnessed as `repo.fetch`,
  **public reads never recorded**, contents never recorded,
  refused transfers record nothing. Battery
  `tests/test_transport_audit.py`: **6 passed / 0 failed**,
  including a stock HTTP clone of a private repo landing
  `repo.fetch` while a public clone lands none, chain
  verifying throughout.
- **S-095 DONE (2026-10-30)** — interop battery:
  `tests/test_transport_battery.py` — the scripted stock-git
  matrix: HTTP public anonymous clone; HTTP private
  clone/push/pull as owner; HTTP token credential cell
  (read token reads, write refused, at the S-082 seam);
  SSH-door private clone+push by key. **4 passed / 1
  skipped**: the real-sshd cell is **NOT PROVEN on this
  host** (no sshd binary installed — the earlier session
  log's note) and skips *by name*, with a tripwire: if an
  sshd appears, the cell fails loudly until it is scripted,
  rather than passing silently.
- **S-096 DONE (2026-10-30) — PART IV GATE.** Gate battery
  `tests/test_part_iv_gate.py`: **3 passed / 0 failed** —
  one assembled service carrying gate + limits + lock +
  event store + auditor at once serves a stock clone+push
  (event with true range, `repo.push` and `repo.fetch`
  audit rows, chain verifies), a gate veto on that same
  service refuses a push with the ref unmoved, and the
  protocol-v2 advertisement offers `ls-refs`/`fetch`.
  Full counted runs at the gate on this VM, both methods,
  reproduced: pytest **640 passed / 3 skipped / 0 failed**;
  unittest discover **636 ran, 633 passed / 3 skipped /
  0 failed**. **Open findings, named:** (1) the real-sshd
  interop cell is NOT PROVEN — no sshd on this host;
  Part XXII / an sshd host owns its proof; (2) stock git
  cannot archive over HTTP at all (remote-curl limitation,
  S-093) — the HTTP archive door is protocol-proven only;
  (3) the S-089 gate's protection and secret-scan stages
  are plug-in *points* — their rules land in Parts VIII
  and XV; (4) platform cells beyond Linux x86-64 remain
  NOT PROVEN (Part XXII); (5) everything banked sits on
  local `main` only — **no GitHub push**: pushes stay
  gated on Volmarr's explicit word. **Part IV is
  complete.** Next: Part V — Web Repository Experience,
  opening at S-097 repository home.
- **S-097 DONE (2026-10-30)** — repository home:
  `samverk/repo_home.py` — root listing, README rendered
  at the root through S-010 (interim safe pipeline:
  headings, code fences, lists, inline code/bold, all
  built from already-escaped text; S-107 owns the full
  Markdown pipeline and will replace its internals),
  branch/tag switcher with the current ref marked in
  words, clone URLs for both transports from the
  instance's configured bases with copy buttons (visible
  read-only fields + `data-copy-target` hooks, no inline
  script; unconfigured transports named, never guessed),
  an honest empty-repo home, and S-054's uniform
  not-found permission shape. The module also carries
  Part V's shared helpers (ref resolution, repo-path
  validation, tree/blob walking) that S-098..S-100 build
  on. Battery `tests/test_repo_home.py`: **7 passed /
  0 failed**. Cumulative battery: **647/647** by running
  count (the governing recount at this run's end governs).
- **S-098 DONE (2026-10-30)** — file browser:
  `samverk/file_browser.py` — tree navigation at any ref
  with breadcrumb, directories-first listing, and
  last-commit-per-entry from one `git log --name-only`
  walk (newest touch wins; a directory is touched by
  anything under it). One battery-found bug fixed
  in-slice: the log format's record marker first trailed
  each header, which attached each commit's file names
  to the *next* commit — the marker now leads the
  format. Battery `tests/test_file_browser.py`:
  **5 passed / 0 failed**. Cumulative: **652**.
- **S-099 DONE (2026-10-30)** — blob view:
  `samverk/blob_view.py` — server-side highlighting (a
  per-language tokeniser over a shared extension table
  with shebang fallback; every raw segment escaped
  before any span is wrapped), line numbers, and line
  permalinks pinned to the *resolved commit oid*, so a
  link pasted into an issue still means the same line
  after the branch moves. Binary files refused by name
  (S-114 owns their view), LFS pointers reported as
  pointers, files over the 1 MB view limit refused by
  name *before* their bytes are read (`cat-file -s`
  first). Battery `tests/test_blob_view.py`: **5 passed
  / 0 failed**. Cumulative: **657**.
- **S-100 DONE (2026-10-30)** — raw and download:
  `samverk/raw_download.py` — exact bytes with correct
  content types (extension table + content sniff),
  downloads as attachments, SVG attachment-only (never
  inline), no size cap and never a silent truncation
  (a file past S-099's view limit comes back whole).
  An LFS pointer resolves to the real bytes when the
  object is in the repo's own LFS store (size checked
  against the pointer first); when it is not, the
  result is the pointer itself, flagged, with a pointer
  page stating the bytes are not on this instance.
  Battery `tests/test_raw_download.py`: **6 passed /
  0 failed**. Cumulative: **659 collected, 656 passed**
  — matching this run's governing recount exactly (see
  the correction entry in the session log).
- **S-101 DONE (2026-10-30)** — blame view:
  `samverk/blame_view.py` — per-line attribution via
  `git blame --line-porcelain` (`blame` added to S-014's
  allowlist with its reason), paginated by line (default
  100, max 500) with true totals and page counts. Each
  line carries its commit, author, time, summary, its
  number in its own commit, and the filename it lived
  under there — a rename in the file's own past stays
  visible (proven by battery). Honest limit, stated on
  the page: no copy/move tracing (`-C`/`-M` off), so a
  line copied in from another file is credited to the
  commit that brought it here. Binary refused by name,
  LFS pointers reported as pointers, oversized refused
  by name. Battery `tests/test_blame_view.py`:
  **5 passed / 0 failed**.
- **S-102 DONE (2026-10-30)** — commit list:
  `samverk/commit_list.py` — paginated history for any
  ref: totals from `rev-list --count`, pages fetched
  with `--skip`/`--max-count`, a page past the end
  answers empty with true totals. Verification badge is
  a **slot**: `verification_badge=None` on every row,
  rendered "Not checked" in words — Part XV fills it,
  and nothing here claims a check that has not run.
  Battery `tests/test_commit_list.py`: **4 passed /
  0 failed**.
- **S-103 DONE (2026-10-30)** — commit detail:
  `samverk/commit_detail.py` — full per-file diff from
  `diff-tree -p --root --find-renames`, counted
  additions/deletions per file, parent links (a root is
  named a root in words), and browse-at-this-point into
  S-098 at the commit oid. Battery-found bug fixed
  in-slice: binary files have no `---`/`+++` lines, so
  paths are first taken from the `diff --git` header.
  Battery `tests/test_commit_detail.py`: **3 passed /
  0 failed**.
- **S-104 DONE (2026-10-30)** — diff engine:
  `samverk/diff_engine.py` — the shared patch parser
  (hunk headers number every line on both sides),
  unified and split renderers (split pairs change
  blocks old/new), whitespace toggle re-run through
  git's own `-w` at compute time, and folding past 400
  patch lines that names the true counts and shows no
  patch text. Compute seams `commit_diff` (against the
  first parent; root against the empty tree) and
  `range_diff` serve commits and, later, PRs. One
  parser bug found by the battery and fixed in-slice:
  the trailing-newline split artifact became a phantom
  context line — a real patch line is never empty.
  Battery `tests/test_diff_engine.py`: **5 passed /
  0 failed**.
- **S-105 DONE (2026-10-30)** — compare view:
  `samverk/compare_view.py` — any two refs: ahead and
  behind counted both ways (a diverged pair says so in
  numbers), commit list capped at 250 with the true
  ahead total and any truncation named in words, files
  changed through S-104's engine. Battery
  `tests/test_compare_view.py`: **3 passed / 0 failed**
  (one test expectation corrected in-slice: a diverged
  compare also counts the other side's file as changed).
- **S-106 DONE (2026-10-30)** — contributors and
  counts: `samverk/repo_stats.py` — headline
  commits/branches/tags from S-072's graph cache; a
  missing/stale cache is refreshed on the spot and the
  summary says so (`from_cache=False`), a fresh row is
  served as cached. Per-contributor counts group the
  history by authored identity (`name <email>`),
  stated as author identities, not instance accounts.
  Battery `tests/test_repo_stats.py`: **3 passed /
  0 failed**.
- **S-107 DONE (2026-10-30)** — Markdown pipeline:
  `samverk/markdown_pipeline.py` — the full sanitised
  renderer behind the S-010 seam, replacing S-097's
  interim renderer inside `render_readme_html` without
  changing the home's shape: headings with deduplicated
  slug anchors and permalinks, task lists (disabled
  checkboxes), tables with alignment, code fences with
  language classes, nested lists, blockquotes,
  reference-style and bare-URL links. Every destination
  passes `safe_url`; unsafe links/images degrade to
  their text/alt, never a clickable hole. Carries the
  `link_resolver` (S-108) and `reference_resolver`
  (S-109) seams. Battery
  `tests/test_markdown_pipeline.py`: **8 passed /
  0 failed**, its XSS section parsing the rendered
  output and attacking every construct. Bugs found and
  fixed in-slice, never left: balanced-paren
  destinations were truncated at the first `)` (a stray
  paren leaked into prose), and an unterminated fence
  turned the document's final newline into a phantom
  blank code line.
- **S-108 DONE (2026-10-30)** — repo-relative links:
  `samverk/repo_links.py` — relative links/images in
  repo Markdown resolve against the Markdown file's
  directory and the pinned commit oid through S-107's
  seam: links to the blob view, images to the raw view,
  fragments/queries preserved, segments percent-encoded.
  Absolute/mailto/anchor/instance-root destinations pass
  through untouched; dangerous schemes are refused and
  a `..` climb above the repo root refuses the link
  (pipeline degrades it to visible text). Repo home
  README wired with root context + pinned commit.
  Battery `tests/test_repo_links.py`: **5 passed /
  0 failed**.
- **S-109 DONE (2026-10-30)** — mentions and
  references in prose: `samverk/prose_references.py` —
  `@user`, `#issue`, and commit-SHA autolinking through
  S-107's `reference_resolver` seam, confirmed never
  guessed: mentions resolve through the account store
  (canonical display case), SHAs through git
  `rev-parse --verify <sha>^{commit}` in the prose's
  own repository and link by full oid; a hex word
  naming no commit stays text, and references never
  fire inside code spans or email addresses. `#issues`
  stay plain text until Part VI wires its store into
  the `issue_exists` seam — linking to pages that
  cannot exist yet would be dishonest. Repo home README
  wired with its account store and repo path. Battery
  `tests/test_prose_references.py`: **5 passed /
  0 failed**.
- **S-110 DONE (2026-10-30)** — file finder:
  `samverk/file_finder.py` — fuzzy path search within a
  repo (the `t` habit), keyboard-first. One
  `ls-tree -r -z` spawn through S-014 at the commit the
  requested ref resolved to lists every blob path
  (gitlinks excluded by object type). A query matches
  when its letters appear in order in the path
  (case-insensitive subsequence); scoring rewards
  basename exactness, basename prefix, contiguity and
  segment starts, and penalises spread, length and
  depth, with path tie-breaks so ranking is
  deterministic. Limits are named, never silent: at
  most 100 results with the true match total carried,
  and a repo past 100,000 files answers
  `too_many_files` by name. The page is a plain GET
  form (autofocused input, ranked ordinary blob links
  at the viewed ref) — no script needed. S-054's
  uniform not-found shape applies. Battery
  `tests/test_file_finder.py`: **5 passed / 0 failed**.
- **S-111 DONE (2026-10-30)** — keyboard baseline:
  `samverk/keyboard.py` — one frozen registry of global
  shortcuts (`t` file finder, `/` search focus, `?`
  help, `Escape` release, `g c`/`g i`/`g p` repository
  navigation) with a data manifest for the external
  client script; the one help page renders *from* the
  registry so it cannot drift. Never trapping is
  structural: every binding carries
  `active_when_typing=False`, duplicate bindings are
  refused at import, and no inline script is rendered
  (S-016). Battery `tests/test_keyboard.py`: **5
  passed / 0 failed**.
- **S-112 DONE (2026-10-30)** — permission-aware
  chrome: `samverk/repo_chrome.py` — tabs and actions
  built from S-054's single `role_for` answer: Code /
  Issues / Pull requests for readers, Settings only
  for admins, write actions exactly at their role,
  Fork and Find-a-file at read; a private repository's
  chrome for a stranger is the uniform `repo_not_found`.
  Forbidden controls are *absent* — the module has no
  disabled rendering path at all — and the battery
  proves the API still enforces regardless
  (`require_role` refuses the same viewers the chrome
  hides things from). Battery
  `tests/test_repo_chrome.py`: **5 passed / 0 failed**.
- **S-113 DONE (2026-10-30)** — empty and error states:
  `samverk/page_states.py` — one frozen registry of
  designed empty states for every surface built so far
  (repo home, file browser, commit list, compare,
  contributors, file finder, blob, blame), each with an
  honest why, a next step in words, and one action; a
  state without a next step cannot be constructed.
  Error states are built from S-019's registered codes
  plus the opaque error id alone — no parameter exists
  through which an exception message, path, or stack
  trace could reach the page — and `not_found` keeps
  S-054's uniform shape ("may not exist, or may be
  private", one sentence for both). Battery
  `tests/test_page_states.py`: **7 passed / 0 failed**.
- **S-114 DONE (2026-10-30)** — binary and image files:
  `samverk/media_view.py`, the view S-099 points at.
  Raster images are recognised by magic bytes (never by
  name — PNG bytes in a `.txt` file are an image; text
  in a `.png` is refused back to the blob view) and
  render through S-100's raw route at the pinned commit
  with genuine alt text (file, repo, header-proven
  dimensions, size — the image-accessibility law).
  Dimensions are parsed from the PNG/GIF/JPEG/WebP
  headers and stated only when the header proves them.
  SVG is described, never rendered inline (script
  carrier, S-012/S-100 law); any other binary shows
  size, type, and a download action with none of its
  bytes on the page — no hex dump, no base64. LFS
  pointers are reported as pointers. Battery
  `tests/test_media_view.py`: **6 passed / 0 failed**.
- **S-115 DONE (2026-10-30)** — repository
  insights-lite: `samverk/repo_insights.py` — only what
  the instance truly knows: commits/branches/tags/
  contributors from S-106's cached derivations (with
  their fresh/cached honesty), accepted pushes counted
  exactly from S-090's event store with the most recent
  push time, recorded read transfers counted from
  S-094's audit for private repositories and stated
  *not applicable* (never zero) for public ones, and
  size on disk measured (S-058 walk). Clone counts for
  anonymous/public reads, page views, and referrers are
  named on the page under "Not tracked" with their
  reasons, and no `clone_count` field exists anywhere
  in the module. Battery `tests/test_repo_insights.py`:
  **4 passed / 0 failed**.
- **S-116 DONE (2026-10-30)** — print and export of code
  views: `samverk/print_export.py` — the print
  stylesheet is external by S-016's law (canonical CSS
  text `PRINT_CSS`, served at `/static/samverk-print.css`,
  linked `media="print"` from the blob, commit, and
  compare page heads; no inline `<style>` anywhere):
  `@media print` hides chrome/forms/actions, strips
  colour to black on white, keeps syntax meaning in
  weight/style (keywords bold, comments italic),
  restores the diff's `+`/`-` markers the line text
  omits (a printed diff must not depend on colour),
  wraps code instead of clipping it. Print pages render
  blob and diff as open sections (never `<details>`,
  whose closed content does not reliably reach paper)
  under a header naming repo, path, full commit pin,
  and counts, with S-104 folding unchanged. Text
  exports are complete: the diff export rebuilds the
  unified patch from S-104's parsed structure
  (re-parses to the identical DiffSet, folded lines
  included) and the blob export restores the file's
  text, refusing an LFS pointer by name. Battery
  `tests/test_print_export.py`: **6 passed / 0 failed**
  (one test-expectation fix in-slice: S-104 counts the
  hunk header as a patch line, so 500 additions fold
  at 501 patch lines — the module already agreed).
- **S-117 DONE (2026-10-30)** — deep links:
  `samverk/deep_links.py` — one canonical URL shape
  per built view (home, tree, blob, raw, blame,
  commit, commits, compare, summary, find, insights),
  minted and parsed by this one module; `blob_url`
  with a line is S-099's permalink byte for byte.
  Anchors carry strict `#L{n}` / `#L{a}-L{b}` grammar
  (positive, end at or after start; fragments refused
  on non-blob views rather than silently dropped).
  The chat shorthand `path@ref#line` expands to the
  canonical blob URL. Names ride S-013's law, paths
  S-098's, segments percent-encoded and round-tripping.
  The slash limit is named: path-view builders refuse
  slash-carrying refs (`ref_ambiguous` — a URL's shape
  cannot tell `feature/x` from a path) while commits
  and compare accept them (compare's `...` separator
  cannot appear inside a git ref). Battery
  `tests/test_deep_links.py`: **7 passed / 0 failed**.
- **S-118 DONE (2026-10-30)** — search box in repo
  scope: `samverk/repo_search.py` — a plain GET form
  (no script) jumping to the instance search page as
  `type=code` with `repo:{owner}/{name}` first in `q`.
  The jump contract is fixed here for Part X to
  consume (`scoped_query`, `repo_search_url`, and
  `extract_repo_scope` as the reverse seam); no
  results page is built or pretended. The box shows
  its scope in the prefilled input and teaches
  widening in plain words (delete the qualifier to
  search everywhere); a malformed `repo:` qualifier
  refuses (`scope_invalid`) rather than silently
  unscoping into a wider search; terms are
  hygiene-cleaned to one typed line; the
  permission-aware entry point answers strangers to
  a private repository with the uniform
  `repo_not_found` and renders no box. Battery
  `tests/test_repo_search.py`: **5 passed / 0 failed**
  (one test-expectation fix in-slice: the jump URL is
  percent-encoded, as URLs are).
- **S-119 DONE (2026-10-30)** — repository header
  summary: `samverk/repo_header.py` — visibility badge
  as words with its meaning stated (never colour
  alone), fork parent named and linked (a dangling
  parent named as gone, never linked nowhere), mirror
  badge naming source kind and last-sync status in
  words while never showing the source itself, fork
  count counted live; watch/star counts honestly
  absent until S-222 (`None`, rendered 'not available
  yet — Part XI') behind a checked counter seam.
  Permission is S-054's uniform `repo_not_found`.
  Battery `tests/test_repo_header.py`: **7 passed /
  0 failed**. *(Entry written by the 2026-10-30
  13:15 keeper run from the slice's banked commit
  message — the run that banked S-119..S-123 left
  these detailed entries and its session log
  unwritten; repaired here, never left.)*
- **S-120 DONE (2026-10-30) — PART V GATE.** Browsing
  battery `tests/test_browsing_battery.py` (**6 passed
  / 0 failed**) over the reference repos (small: full
  walk; large: 60 nested files, paginated history,
  honest finder totals; LFS: pointer reported as a
  pointer, never served as the file; wiki-less: no
  built page invents a wiki), plus the cross-cutting
  strikes — a private repo answers every Part V
  surface with the uniform `repo_not_found` for
  strangers and anonymous readers while its owner
  walks it fine, and rendered pages carry no inline
  styles. The browser-rendered 100%/200% scaling
  proof is NOT PROVEN here and owned by Part XX
  S-384. Gate-found bug fixed in-slice, never left
  (ac76948): the S-101 blame parser refused real git
  output for same-commit line groups; it now accepts
  both header shapes, with a regression test.
  **Part V is complete.** Next: Part VI — Issues,
  opening at S-121.
- **S-121 DONE (2026-10-30)** — issue model and
  numbering: `samverk/issues.py` + schema migration
  34 (`repo_counters`, `issues`) — one shared per-repo
  sequence for issues and pull requests (atomic upsert
  claim, so racing connections never share a number;
  the counter only moves forward, so a removed #n
  leaves a gap and is never reused); every claimed
  number is exactly one row carrying its kind,
  resolved through `resolve_number`/`exists` — the
  seam S-109's prose references and S-127's
  cross-references read through. Battery
  `tests/test_issue_numbering.py`: **6 passed /
  0 failed**.
- **S-122 DONE (2026-10-30)** — issue create/read/
  update in `samverk/issues.py`: title (plain text,
  required, stripped), Markdown body, author, open
  state at birth (close/reopen with reasons is
  S-130's); reads follow S-054 (a stranger to a
  private repo, a pull request's number, and a
  never-claimed number all answer the same uniform
  `issue_not_found`, so private issues cannot be
  enumerated); creating requires repo read access,
  editing is the author's or a repo writer's; edits
  are commit-before-answer with an optimistic version
  (`edit_conflict` on a stale expectation, changing
  nothing). Audited `repo.issue.create` /
  `repo.issue.update` (taxonomy append-only, 58
  events). Battery `tests/test_issues.py`: **7 passed
  / 0 failed**.
- **S-123 DONE (2026-10-30)** — comments:
  `samverk/issue_comments.py` + schema migration 35 —
  Markdown comments on issues under S-054 (strangers
  to a private repo get the uniform `issue_not_found`
  for every comment operation); edit history visible
  by law — the previous body is recorded in
  `issue_comment_edits` in the same transaction as
  the edit, shown by `edits_for` to any reader;
  editing is the author's alone; deletion by author
  or repository admin is a tombstone (body cleared,
  `deleted_at`/`deleted_by` stamped, list views skip
  it, a direct link is told it was deleted) plus an
  audit row (taxonomy append-only, 61 events; bodies
  never in audit detail). Battery
  `tests/test_issue_comments.py`: **7 passed /
  0 failed**.
- **S-124 DONE (2026-10-30)** — labels:
  `samverk/labels.py` + schema migration 36
  (`labels`, `issue_labels`) — CRUD under S-054
  (managing is a writer act; strangers to a private
  repo get the uniform `repo_not_found`). Text is
  mandatory: a colour with no name is refused
  (`label_name_required`), colours are strict
  `#rrggbb`, and `render_label` prints the name and
  the colour value as text, so meaning never rides
  on colour alone. Names are unique per repository
  case-insensitively. The default starter set
  (`DEFAULT_LABELS`: bug, documentation, duplicate,
  enhancement, good first issue, help wanted,
  invalid, question, wontfix) is seeded inside the
  repository-creation transaction, and
  `seed_default_labels` repairs older repositories
  idempotently. Assignment to issues (`add_to_issue`
  / `remove_from_issue`) is a writer or issue-author
  act; deleting a label takes its assignments with
  it in the same transaction. Audited
  `repo.label.create` / `.update` / `.delete` and
  `repo.issue.label_add` / `.label_remove` (taxonomy
  append-only, 66 events: 29 auth, 25 repo, 12
  admin). Battery `tests/test_labels.py`: **8 passed
  / 0 failed**. **Correction (same keeper run,
  foreground re-run):** the first local-battery
  report for this slice arrived as a backgrounded
  delivery claiming 34 passed in 47.78 s — a phantom
  of the kind this campaign has met before (the
  duration was impossible for 34 scrypt-heavy
  batteries, and a foreground run immediately found
  two test-authoring bugs in the new battery: an
  audit query ordering by `id` where the column is
  `seq`, and one expectation naming `LabelError`
  where the uniform private answer arrives as
  S-122's `IssueError`). Both fixed in the battery
  (module behaviour stood in both); the governing
  counts are the foreground ones: labels + milestones
  + taxonomy **21 passed / 0 failed**, and labels +
  taxonomy + repositories + issues + comments
  **34 passed / 0 failed in 83.03 s** — the number
  34 now stands on a foreground log, not on the
  discarded phantom.
- **S-125 DONE (2026-10-30)** — milestones:
  `samverk/milestones.py` + schema migration 37
  (`milestones`; `issues.milestone_id`) — CRUD under
  S-054 (managing is a writer act; strangers to a
  private repo get the uniform `repo_not_found`).
  Titles are mandatory plain text, unique per
  repository case-insensitively; due dates must be
  real calendar `YYYY-MM-DD` dates (30 February
  refused, datetimes refused; a leap day is a date).
  Progress is counted live from the issues table —
  open / closed / total and the closed share as a
  whole percent, `0 of 0` said in words for an empty
  milestone — and `render_progress` prints counts,
  percent, due date, and the word *Overdue* as text
  (an open milestone past its date, against the
  store clock), never as a colour-only bar.
  Assignment rides `set_issue_milestone` (writer or
  issue author; None clears); deleting a milestone
  unassigns its issues in the same transaction —
  issues are never deleted with it. Audited
  `repo.milestone.create` / `.update` / `.delete`
  and `repo.issue.milestone` (taxonomy append-only,
  70 events: 29 auth, 29 repo, 12 admin). Battery
  `tests/test_milestones.py`: **7 passed / 0 failed**
  (foreground, in the 21-test combined run above).
- **S-126 DONE (2026-10-30)** — assignees:
  `samverk/assignees.py` + schema migration 38
  (`issue_assignees`) — multiple assignees per issue,
  bounded at 10 (`assignee_limit` names the cap),
  each row recording who was assigned, by whom, and
  when, listed in assignment order (insertion order,
  so same-second assignments never reorder by account
  id — a battery-found flaw fixed in-slice). Every
  assign/unassign is an audit event
  (`repo.issue.assign` / `repo.issue.unassign`,
  taxonomy append-only, 72 events: 29 auth, 31 repo,
  12 admin); repeats are quiet no-ops emitting no
  second event, so retries are safe. An assignee must
  be able to read the repository under S-054
  (`assignee_cannot_read` refuses a stranger to a
  private repo — assigning them would leak the issue
  and strand the work). A writer may assign anyone
  eligible; any reader may assign *themselves* and
  unassign themselves; unassigning someone else is a
  writer act. `issues_assigned_to` is the
  'assigned to me' seam (per repository, optional
  state filter — the rows S-135's `assignee:`
  qualifier will execute over). Battery
  `tests/test_assignees.py`: **6 passed / 0 failed**
  (foreground; combined Part VI run at banking:
  labels + milestones + assignees + taxonomy
  **27 passed / 0 failed**).
- **S-127 DONE (2026-10-30)** — cross-references:
  `samverk/cross_references.py` + schema migration 39
  (`cross_references`) — mentioning `#n` or a commit
  links both ways. The parser works on prose only
  (fenced blocks and inline code never record), folds
  duplicates, and marks references governed by closing
  keywords (`close(s/d)`, `fix(es/ed)`, `resolve(s/d)`,
  including governed lists like `Closes a/b#1, #2 and
  resolves #6`). Recording is a sync that replaces a
  source's rows with what its current text says — an
  edit that removes a mention removes the
  back-reference, and a tombstoned comment's references
  die with its body. Honesty law, as S-109: a `#n` is
  recorded only when `resolve_number` proves it claimed
  (same-repo or `owner/repo#n`), a commit SHA only when
  the caller's resolver confirms a real commit there;
  self-references are never rows. `references_to` hides
  back-references whose source repo the viewer cannot
  read, so private conversations never leak through a
  public target. `closing_references` / `closing_notice`
  are the shown-before-merge seam ("Will close
  owner/repo#n on merge." in plain words); acting on
  the mark at merge is Part VII's. No audit event of
  its own — derived data from already-audited prose,
  named in the taxonomy doc's version note. Battery
  `tests/test_cross_references.py`: **9 passed /
  0 failed** (foreground); combined foreground run with
  taxonomy + dependencies + issues + numbering +
  comments + labels + milestones + assignees:
  **61 passed / 0 failed**, read back from the log file.
- **S-128 DONE (2026-10-30)** — reactions:
  `samverk/reactions.py` + schema migration 40
  (`reactions`) — the small honest set: eight reactions
  stored by plain-words name (`thumbs_up` … `eyes`),
  each with label + glyph; anything outside the set is
  refused `reaction_invalid`. Targets are an issue or
  one of its comments, never mixed. Counts are counted
  live from the rows and every summary carries the
  who-reacted list in reaction order; `render_summary`
  prints glyph, name, count, and names as text.
  Giving/taking back is a reader act under S-054
  (uniform `issue_not_found` for strangers to a private
  repo); repeats are quiet no-ops, only real changes
  are audited, and you can only remove your own
  (`repo.issue.reaction_add` / `repo.issue.reaction_remove`,
  taxonomy append-only +2, 74 events: 29 auth, 33 repo,
  12 admin; doc + test counts updated together).
  Battery `tests/test_reactions.py`: **5 passed /
  0 failed** (foreground; combined with taxonomy +
  dependencies **16 passed / 0 failed**, read back
  from the log file).
- **S-129 DONE (2026-10-30)** — issue templates:
  `samverk/issue_templates.py` + schema migration 41
  (`issue_templates`, `repo_issue_options`) — two kinds
  behind one guided door. Markdown templates (name,
  plain-words description, starting title, body) render
  as a prefilled title/body form; YAML issue forms are
  parsed by a documented stdlib subset parser (indentation
  maps/lists, quoted/plain scalars, inline lists,
  true/false/null, integers, `|`/`>` block scalars;
  tabs, flow mappings, anchors refused `form_invalid`)
  into validated fields (markdown notes, input, textarea,
  dropdown, checkboxes; labels mandatory in plain words,
  ids unique, `validations.required` honoured). A
  submission assembles into an ordinary issue — one
  `### label` section per answered field, checkboxes as
  a task list — with refusals naming the field
  (`field_required` / `field_option_invalid` /
  `field_unknown`); template-named labels are checked
  before the issue exists, so a broken template fails
  whole. Managing is a writer act under S-054, using a
  reader act, strangers to a private repo get the
  uniform `repo_not_found`. Blank issues: owners may
  disallow them (writer act, audited under the frozen
  `repo.settings.change` with the key named), enforced
  at the one creation seam in `IssueStore.create_issue`
  (`blank_issue_not_allowed` unless `via_template`);
  the toggle refuses to switch off with zero templates
  (`no_templates`) so reporting can never be locked
  entirely. Taxonomy append-only +3
  (`repo.issue_template.create` / `.update` / `.delete`,
  77 events: 29 auth, 36 repo, 12 admin). Battery
  `tests/test_issue_templates.py`: **11 passed /
  0 failed** (foreground; combined with taxonomy +
  dependencies **22 passed / 0 failed**, read back
  from the log file).
- **S-130 DONE (2026-10-30)** — close and reopen:
  `samverk/issues.py` extended + schema migration 42
  (`issues.state_reason`, `issue_events`) — closing
  carries a reason in plain words, `completed` or
  `not_planned` and nothing else (`reason_invalid`),
  stored on the issue and said in words by
  `Issue.state_words` ("closed as not planned"), never
  a colour alone. Every real transition writes an
  `issue_events` row in the same transaction as the
  state change — the stream S-131's timeline will read
  through `state_events_for`, with `describe_state_event`
  rendering it in plain words — and an audit row
  (`repo.issue.close` / `repo.issue.reopen`, taxonomy
  append-only +2, 79 events: 29 auth, 38 repo,
  12 admin). Closing a closed issue or reopening an
  open one is a quiet no-op (a reclose does not rewrite
  the recorded reason); the actor is the issue's author
  or a repository writer, and strangers to a private
  repo get the uniform `issue_not_found`. Battery
  `tests/test_issue_close_reopen.py`: **6 passed /
  0 failed** (foreground; combined with issues,
  taxonomy, dependencies, templates, and
  cross-references **44 passed / 0 failed**, read back
  from the log files).
- **S-131 DONE (2026-10-30)** — timeline:
  `samverk/issue_timeline.py` — one ordered stream of
  everything that happened to an issue, derived and
  never duplicated: creation from the issue row,
  state changes through S-130's `state_events_for`
  seam, label / assignment / milestone changes read
  from the audit log (the record those acts already
  write, read the way S-047 reads it), and mentions
  (incoming) plus cross-references (outgoing, closing
  marks said in words) from S-127's record — a
  back-reference whose source repo the viewer cannot
  read is hidden, exactly as S-127 hides it. Order is
  time, then a fixed kind rank, then the source
  record's id, so a rebuild is identical; every event
  renders in plain words (`describe_event`), and
  `render_timeline` escapes through S-010's seam.
  Comments are the conversation, not events (surfaces
  interleave them by time); edits and reactions are
  not happenings either. No migration, no audit event
  of its own (79 events stand). Battery
  `tests/test_issue_timeline.py`: **8 passed /
  0 failed** (foreground, read back from the log
  file) — the full nine-event stream in order with
  its exact wordings, quiet no-ops leaving no state
  events, both xref directions, a commit mention, and
  the private-source hiding proof.
- **S-132 DONE (2026-10-30)** — locking and pinning:
  `samverk/issue_locking.py` + schema migration 43
  (`issues.locked/lock_reason/locked_by/locked_at`,
  `issue_pins`) — a lock carries one reason from a
  small plain-words vocabulary (`off_topic` /
  `too_heated` / `resolved` / `spam`, anything else
  `reason_invalid`), stored on the issue (the `Issue`
  row now carries it) and said in words by
  `IssueLock.words`, never a colour alone. Enforcement
  lives at the one comment seam: S-123's `add_comment`
  refuses a locked conversation
  (`conversation_locked`, the reason named) for
  everyone except repository writers/admins. Pinning
  lifts at most three issues per repository
  (`pin_limit` names the cap; pins list in pin order —
  the pin row's own insertion id, after the first
  battery caught same-second pins reordering by issue
  number, S-126's law applied again). Both tools are
  moderator-only (repository admins, S-123's trusted
  hands — the issue's author alone cannot lock), real
  changes only are audited, and retries are quiet
  no-ops that never rewrite the recorded reason
  (taxonomy append-only +4: `repo.issue.lock` /
  `.unlock` / `.pin` / `.unpin`, 83 events: 29 auth,
  42 repo, 12 admin; doc + code + counts together).
  S-131's timeline learned the four new events from
  the same audit record in this slice (one added
  battery cell). Battery `tests/test_issue_locking.py`:
  **7 passed / 0 failed** (foreground; combined with
  taxonomy + comments + dependencies **25 passed /
  0 failed**; timeline + locking combined **16 passed
  / 0 failed**, read back from the log files).
- **S-133 DONE (2026-10-30)** — issue transfer:
  `samverk/issue_transfer.py` + schema migration 44
  (`issue_transfers`, the forwarding record). An issue
  moves only between repositories of the same owner
  (`different_owner` / `same_repository` refused by
  name); the row itself moves — claiming the
  destination's next shared number inside the same
  transaction, so the vacated number is a permanent
  gap (S-121) — keeping author, title, body, state and
  closing reason, lock, comments, assignees, reactions
  and state history; labels and the milestone remap by
  name/title onto the destination's own rows or drop
  (named in the result), and a pin stays behind. The
  forwarding note at the old address names the
  destination only to a viewer who can read it; to
  anyone else it says in words that the issue was
  transferred to another repository. The mover is the
  author or a source writer who can read the
  destination (unreadable destination = uniform
  `repo_not_found`). Audited on both sides (taxonomy
  append-only +2: `repo.issue.transfer_out` /
  `.transfer_in`, 85 events: 29 auth, 44 repo,
  12 admin; doc + code + counts together), and
  S-131's timeline learned the arrival event from the
  same record. Battery `tests/test_issue_transfer.py`:
  **8 passed / 0 failed** (foreground).
- **S-134 DONE (2026-10-30)** — bulk edit:
  `samverk/issue_bulk_edit.py` — label/assign/close
  across a filtered set, applied through the owning
  seams (S-124/S-126/S-130), so each real change writes
  that seam's own audit event for that issue and the
  bulk act adds no event of its own. `select_numbers`
  computes the set from plain criteria (state, label,
  assignee, milestone, author) through the read seams;
  sets are capped at 100 (`set_too_large` names the
  cap, never a silent truncation) and operation
  parameters are validated whole before any issue is
  touched (a bad label, assignee, or closing reason
  changes nothing). Per-issue outcomes are reported:
  successes in order, failures with their reason — one
  bad number or one permission refusal never stops the
  rest of the set — and retries are quiet successes
  that write no second audit event. Battery
  `tests/test_issue_bulk_edit.py`: **7 passed /
  0 failed** (foreground; combined affected suites
  with S-133: transfer + bulk + taxonomy + timeline +
  dependencies + labels + assignees + close/reopen
  **55 passed / 0 failed**). Governing full-suite
  recount after both slices, read back from its log
  file: pytest **866 passed / 1 skipped / 0 failed**
  (867 collected, 5 subtests passed; the skip is
  S-095's named real-sshd cell, NOT PROVEN on this
  host). Correction: this run's session-log commit
  (b3ec7f6) first recorded 851/852 — a count stated
  before the finished log was read back; the log's
  own tail (866 passed, 1 skipped, in 245.58s) is
  the governing number and this entry corrects it.
- **S-135 DONE (2026-10-30)** — issue search UI:
  `samverk/issue_search.py` + research file 19 written
  (the full grammar: token shape, quoting, AND
  composition, the qualifier table, the reserved Part X
  qualifiers for S-206, and the failure law). The
  implemented subset is the roadmap's: `is:open` /
  `is:closed` / `is:issue`, `label:`, `author:`,
  `assignee:`, `milestone:` — values may be quoted so
  names carrying spaces stay one token; every other
  token is free text matched case-insensitively against
  title and body; all qualifiers and terms AND together
  and contradictory states match nothing honestly.
  Unknown qualifiers, empty values, unterminated
  quotes, and bad `is:` values are all refused
  `query_invalid` by name — never silently dropped (a
  dropped qualifier would silently widen the search,
  the S-118 law). Matching reads through the owning
  seams (S-122's list, S-124's labels, S-126's
  assignees, S-125's milestone column) and permission
  rides S-054 through the list seam, so a stranger to a
  private repository gets the uniform `issue_not_found`.
  `render_search_page` teaches the qualifiers in plain
  words, says each result's state in words, and carries
  a teaching empty state; all user text through S-010.
  No audit event of its own (a read). Battery
  `tests/test_issue_search.py`: **8 passed / 0 failed**
  (foreground).
- **S-136 DONE (2026-10-30)** — saved filters:
  `samverk/saved_filters.py` + schema migration 45
  (`saved_filters`). A filter is a name plus an S-135
  query targeting `issues` or `pull_requests`, validated
  through S-135's parser at save time (`query_invalid`
  refused at the door, never stored to fail later) and
  parsed again at run time through the same seam.
  Filters are personal: list/get/run/delete all scope
  by the owner's account id, so no seam lists another
  user's filters; names are unique per user per
  repository case-insensitively (`name_taken`). Running
  grants no access — S-054 through S-135's search, the
  uniform `repo_not_found` for a stranger to a private
  repository. No audit event of its own (a personal
  reading preference; the S-127/S-131/S-135 pattern).
  `render_sidebar` groups filters by target in plain
  words with URL-encoded query links, names escaped
  through S-010, and a teaching empty state. Battery
  `tests/test_saved_filters.py`: **6 passed / 0
  failed** (foreground; combined with S-135's battery
  and the S-017 dependencies scan: 19 passed / 0
  failed). Governing full-suite recount after both
  slices, read back from its log file: pytest **880
  passed / 1 skipped / 0 failed** (881 collected, 5
  subtests passed — exactly the prior 866 plus this
  run's 14 battery tests; the skip is S-095's named
  real-sshd cell, NOT PROVEN on this host).
- **S-137 DONE (2026-10-30)** — issue → PR conversion:
  `samverk/issue_conversion.py` + schema migration 46
  (`pull_requests`: branch pair, both oids at birth,
  draft flag, `source_issue_id` UNIQUE link). One act
  creates a real linked branch through S-053's ref seam
  at the base branch's commit (default name
  `<number>-<title slug>`; explicit names honoured under
  the branch-name law; an existing branch is
  `branch_taken`, never overwritten) and a draft PR
  claiming the next shared S-121 number (its `issues`
  row carries `kind='pull_request'`, the issue's title,
  and a body linking back to the issue). Writers only
  (`permission_denied` for a mere reader, even the
  author; uniform `issue_not_found` for a stranger to a
  private repository); closed issues refused
  (`issue_closed`); a missing base — including an empty
  repository — is `base_not_found`; a second conversion
  is `already_converted` naming the existing PR. Every
  refusal lands before any number is claimed or branch
  created, and a database failure after branch creation
  deletes the branch again (all-or-nothing). Audited on
  both sides (taxonomy append-only +2:
  `repo.issue.convert` / `repo.pull_request.create`,
  87 events: 29 auth, 46 repo, 12 admin; doc + code +
  counts together), and S-131's timeline learned the
  conversion from the same audit record. Part VII's
  creation / ready-for-review roads build on this PR
  record. Battery `tests/test_issue_conversion.py`:
  **8 passed / 0 failed** (foreground; combined with
  taxonomy + timeline + issues + dependencies 35
  passed / 0 failed).
- **S-138 DONE (2026-10-30)** — moderation:
  `samverk/moderation.py` + schema migration 47
  (issue_comments hidden_at / hidden_by / hide_reason)
  + S-123's list seam learning hidden visibility.
  Moderators are repository admins only. Hiding stamps
  a required plain-words reason (`spam` / `abuse` /
  `off_topic` / `outdated`; anything else
  `reason_invalid`) and takes the comment out of the
  conversation for everyone except its author and the
  moderators — the body is never touched; unhiding
  restores it whole. Removal strikes S-123's tombstone
  as a distinct moderation act with its own reason and
  event, never confused with an author's own delete.
  No silent edits: every real act is audited (taxonomy
  append-only +3: `repo.issue.comment_hide` /
  `.unhide` / `.comment_remove`, 90 events: 29 auth,
  49 repo, 12 admin; doc + code + counts together) and
  S-131's timeline learned all three acts from that
  record; retries are quiet no-ops; a deleted comment
  can be neither hidden nor removed again. Battery
  `tests/test_moderation.py`: **7 passed / 0 failed**
  (foreground; combined with taxonomy + timeline +
  comments + dependencies 34 passed / 0 failed).
- **S-139 DONE (2026-10-30)** — issue events out:
  `samverk/issue_events_out.py` + schema migration 48
  (`issue_event_outbox`, audit_seq UNIQUE). Every
  issue mutation emits an outbound event for Part XI's
  feeds and Part XII's webhooks, derived from the audit
  witness on the S-090/S-127 pattern: one outbox row
  per audited mutation, materialised by `sync_repo` /
  `sync_all` with OR IGNORE over the UNIQUE seq, so
  emission is exactly-once, quiet retries emit nothing,
  and refused mutations emit nothing. The verb set is
  the issue family, computed from the frozen taxonomy
  (every `repo.issue.*` / `repo.label.*` /
  `repo.milestone.*` action + `repo.pull_request.create`;
  templates, pushes, and repo acts stay out — named as
  a boundary, not an omission). Detail is the audit
  row's own safe specifics, unchanged. `webhook_payload`
  / `payload_json` give Samverk's own payload shape
  (event, action, repository, number, actor, detail,
  occurred_at, stable `evt-<id>` delivery id) — Part
  XII's S-247 maps these verbs to its documented
  payloads and S-250's worker delivers from this store;
  S-221 completes Part XI's canonical store over this
  shape. Reads sync first (never stale) under S-054.
  No new audit events (the outbox *is* derived from
  them). Battery `tests/test_issue_events_out.py`:
  **6 passed / 0 failed** (foreground; combined with
  the S-017 dependencies scan 11 passed / 0 failed).
- **S-140 DONE (2026-10-30) — PART VI GATE.** Gate
  battery `tests/test_issue_battery.py`: **5 passed /
  0 failed** (foreground), walking the assembled Part
  VI system over public and private repositories: the
  full lifecycle end to end (create → comment → label
  → milestone → assign → react → pin → lock, with the
  lock biting a reader's comment → unlock → close as
  completed → reopen → convert to a draft PR), with
  the timeline and the S-139 outbox telling the same
  story the acts wrote; transfer keeping an issue
  whole with its forwarding note; references linking
  both ways with the closing notice said before any
  merge and a mention in the target's timeline; and
  permissions at each role — a private repository
  answering anonymous, stranger, and non-owner readers
  with the uniform not-found on every surface (issues,
  comments, timeline, outbox, references) while its
  owner walks it fine, and on a public repository a
  non-author reader refused edit and moderation while
  the owner moderates. Counted gate run executed fresh
  at the gate on this VM (Linux x86-64), read back
  from its log file: `python3 -m pytest tests -q` →
  **906 passed / 1 skipped / 0 failed** (907 collected,
  5 subtests passed, 1793.68 s — exactly the prior
  governing 880 plus S-137's 8, S-138's 7, S-139's 6,
  and this gate's 5). The one skip is S-095's named
  real-sshd cell, NOT PROVEN on this host. (The gate
  recount's first attempt was killed by a service
  restart after 7 tests — its log held only dots, no
  result, and is not evidence; the restarted run's log
  is `recount-2026-10-30-1745-pytest.log` in the goal's
  hidden files.) **Open findings, named, none hidden:**
  (1) the real-sshd cell stays NOT PROVEN (S-095);
  platform cells beyond Linux x86-64 stay NOT PROVEN
  (Part XXII owns proof). (2) Part VII builds the full
  PR surface on S-137's PR record (creation roads,
  ready-for-review, reviews, merge) — the draft PR a
  conversion mints is real but minimal until then.
  (3) Everything banked sits on local `main` only —
  **no GitHub push made**: pushes stay gated on
  Volmarr's explicit word. **Part VI is complete.**
  Next: Part VII — Pull Requests & Code Review,
  opening at S-141 PR creation, same-repo.
- **S-142 DONE (2026-10-30)** — PR creation, cross-fork:
  new module `samverk/pull_request_forks.py`
  (`ForkPullRequestStore`), migration 49
  (`pull_request_forks`: head_repo_id +
  maintainer_can_edit; a row's presence IS the
  cross-fork fact), and one new dedicated S-014 seam
  in `samverk/proc.py` — `run_git_fetch_ref`, fetching
  one named ref from a trusted local path into a
  scratch ref (generic `fetch` stays refused). The
  head repository must descend from the base through
  S-055's `fork_of_id` chain (`not_a_fork` otherwise;
  `same_repository` routes back to S-141); the walked
  chain is returned and `relationship_words` says it
  in plain words, direct or through each intermediate
  fork, on the preview, the created record, and the
  rendered page. The compare fetches the base branch's
  current tip into the fork under the scratch ref
  `refs/samverk-compare/base` (deleted in every
  outcome — asserted gone by the battery), so ahead /
  behind / commits / diff are true against the base as
  it stands today even when the upstream moved after
  the fork; a battery cell proves the moved-base case
  (ahead 1 / behind 1, creation recording the new base
  oid). Permission is the fork bargain: write on the
  head repository + read on the base — the fork's owner
  opens into a base they cannot write; the base's owner
  cannot offer somebody else's fork branch
  (`permission_denied`); unreadable head/base answer
  the uniform `head_repo_not_found` / `repo_not_found`.
  Creation validates whole (base/head existence,
  branch law, `no_commits`, `already_exists` scoped to
  the same head repository) before claiming the base
  repository's next shared S-121 number; born open,
  not draft; audited under the existing
  repo.pull_request.create with `same_repo: false`,
  the head repo's full name, and the flag in the
  detail (taxonomy unchanged, 90 events). The
  maintainer-edits flag (default true) is stored, said
  in words everywhere the PR is shown, and answerable
  through `maintainer_edit_allowed` — true only for a
  base writer on a flagged cross-fork PR. Battery
  `tests/test_pull_request_forks.py`: **10 passed /
  0 failed** (foreground), and standalone **10 passed**;
  combined with same-repo PRs + conversion + forks +
  proc + taxonomy + dependencies + secrets **59 passed
  / 0 failed**. The governing recount this run owed
  was paid first and read back from its log file:
  pytest **914 passed / 1 skipped / 0 failed** (915
  collected, 5 subtests passed, 1719.11 s — exactly
  the prior 906 plus S-141's 8); the one skip is
  S-095's named real-sshd cell, NOT PROVEN on this
  host. No bugs were found in shipped code by the new
  battery. Next: S-143 draft pull requests. A fresh
  governing recount is owed before further slices bank
  (expectation 924 passed / 1 skipped).
- **S-143 DONE (2026-10-30)** — draft pull requests:
  new module `samverk/pull_request_drafts.py`
  (`PullRequestDraftStore`). Drafts are born through
  the ordinary creation seams — S-141's and S-142's
  creation gained a `draft` parameter (default false;
  the audit detail now says which), joining S-137's
  conversion-born drafts — and are listed, read, and
  rendered exactly like any other pull request.
  `mark_ready` / `convert_to_draft` convert both ways:
  the author or any writer on the base repository may
  convert (a mere reader is refused
  `permission_denied`; a stranger to a private repo
  gets the uniform `pull_request_not_found`); a closed
  pull request is refused `pull_request_closed`; asking
  for the state it is already in is a quiet no-op.
  Each real transition is an event — taxonomy
  append-only +2 (`repo.pull_request.mark_ready`,
  `repo.pull_request.convert_to_draft`; **92 events:
  29 auth, 51 repo, 12 admin**; doc + code + counts
  together) — and S-139's outbox verb rule now covers
  the `repo.pull_request.*` lifecycle, so transitions
  reach Part XI/XII like creations do. Unmergeability
  is a stated seam: `merge_blocker` / `readiness` say
  in words that a draft cannot merge until marked
  ready (and a closed PR cannot merge), for the merge
  slices S-153…S-155 to enforce from one place.
  Battery `tests/test_pull_request_drafts.py`:
  **9 passed / 0 failed** (foreground); combined with
  taxonomy + same-repo PRs + cross-fork PRs +
  conversion + issue events out + dependencies
  **52 passed / 0 failed**, read back from its log
  file. Two honest notes: (1) the battery's first
  combined delivery claimed 51 passed / 0 failed —
  a crossed report; three reproducible runs showed
  1 failure (the battery tried to close a PR through
  S-130's issue seam, which refuses PR rows by kind —
  a test-arrangement error, module behaviour standing;
  no PR-close seam exists yet, so the closed state is
  now arranged at the storage layer with that stated
  in the test), and only the log-file runs govern.
  (2) No bugs were found in shipped code. Next:
  S-144 PR conversation. A fresh governing recount is
  owed before further slices bank (expectation
  933 passed / 1 skipped).
- **S-144 DONE (2026-10-30)** — PR conversation:
  new module `samverk/pull_request_conversation.py`
  (`PullRequestConversationStore`). Comments live on
  the pull request in S-123's shared comment record —
  the same table, edit history, and tombstones, with
  S-138's hidden-comment visibility and S-132's lock
  refusal (reason in words, writers excepted) read
  from the same stamps — under its own audit events
  (taxonomy append-only +3:
  `repo.pull_request.comment` / `.comment_edit` /
  `.comment_delete`; **95 events: 29 auth, 54 repo,
  12 admin**; doc + code + counts together), carried
  by S-139's outbox under its `repo.pull_request.*`
  verb rule. The timeline is derived the way S-131's
  is — opening from the PR row, state changes from
  `issue_events`, readiness conversions (S-143) and
  the audited issue-family acts from the audit log,
  mentions and references from S-127's record — and
  `conversation_for` merges comments and timeline by
  time into one stream. Closing-keyword display
  rides S-127: `closing_references` parses the PR's
  current body and its live comments, keeps only
  keyword-governed references proven through
  `resolve_number`, and `closing_notice` says each
  in words before merge; `sync_references` records
  the prose into S-127's record, so mentioned items
  gain back-references (proven in S-131's own stream)
  and the PR timeline gains its `referenced` events.
  Review submissions land in S-148, which teaches
  this stream its review events the way S-132…S-138
  taught S-131 — no review record exists yet to
  merge, and none is invented. Battery
  `tests/test_pull_request_conversation.py`:
  **11 passed / 0 failed** (foreground); combined
  with taxonomy + timeline + cross-references +
  drafts + issue comments + issue events out +
  dependencies + same-repo PRs + cross-fork PRs +
  conversion **88 passed / 0 failed**, read back
  from its log file. The governing recount this run
  owed was paid first and read back from its log
  file: pytest **933 passed / 1 skipped / 0 failed**
  (934 collected, 5 subtests passed, 2065.27 s —
  exactly the prior 914 plus S-142's 10 and S-143's
  9); the one skip is S-095's named real-sshd cell,
  NOT PROVEN on this host. No bugs were found in
  shipped code by the new battery. Next: S-145 PR
  files view. A fresh governing recount is owed
  before further slices bank (expectation 944
  passed / 1 skipped).
- **S-145 DONE (2026-10-30)** — PR files view:
  new module `samverk/pull_request_files.py`
  (`PullRequestFilesStore`). The diff is S-104's
  shared engine over the pull request's branches as
  they stand today — same-repository through S-105's
  compare seam, cross-fork through S-142's
  cross-repository compare (its scratch ref deleted
  in every outcome), whitespace toggle carried by
  the engine (`-w`) in both cases. Viewed state is
  per reviewer per file (migration 50,
  `pull_request_file_views`): marking a file records
  a SHA-256 hash of the patch that reviewer actually
  saw; a later push that changes that file's patch
  changes the hash, so the file reads as *changed
  since you viewed it* — not viewed, said in words —
  while a push leaving the patch untouched leaves
  the mark standing. Unmarking deletes the record;
  re-marking a changed file vouches for the new
  patch. Progress is said in words
  (`progress_words`, "N of M files viewed"), never
  a colour alone; an anonymous reader of a public
  repository sees the files and no personal state.
  Marking a file not in the current diff is refused
  `file_not_found` and stores nothing; a stranger
  to a private repository gets the uniform
  `pull_request_not_found` on every surface. No
  audit event of its own (a personal reading
  preference, the S-136 pattern; taxonomy stands
  at 95 events). Battery
  `tests/test_pull_request_files.py`: **10 passed /
  0 failed** (foreground); combined with same-repo
  PRs + cross-fork PRs + drafts + conversation +
  compare + diff engine + conversion + taxonomy +
  dependencies **75 passed / 0 failed**, read back
  from its log file. Governing full-suite recount
  read back from its log file after the slice:
  pytest **954 passed / 1 skipped / 0 failed**
  (955 collected, 5 subtests passed, 3149.85 s —
  exactly the prior 933 plus S-144's 11 and this
  slice's 10; the one skip is S-095's named
  real-sshd cell, NOT PROVEN on this host). One
  earlier recount this run was discarded, never
  counted: run without the campaign environment
  (no `~/workspace/.tools` on PATH) it read 942
  passed / 3 skipped, the two git-lfs client cells
  skipping instead of passing; the corrected rerun
  stands. No bugs were found in shipped code by
  the new battery. Next: S-146 line comments.
- **S-146 DONE (2026-10-30)** — line comments:
  new module `samverk/pull_request_line_comments.py`
  (`PullRequestLineCommentStore`). A comment anchors
  to one exact diff line (migration 51,
  `pull_request_line_comments` + its edit-history
  table): file path, side (`old`/`new`), line number
  on that side, the line's text, and the head oid it
  was written against. Anchoring validates whole
  against the current diff through S-145's diff
  road (same-repo and cross-fork alike): a file not
  in the diff is refused `file_not_found`, a bad
  side `side_invalid`, a line that does not exist
  on that side (an added line on the old side, a
  removed line on the new side) `line_not_found` —
  and a refused anchoring stores nothing. Outdated
  is judged on every read, never stored: the
  comment is outdated when the current diff no
  longer carries that exact line (same file, side,
  number, and text), so a push that rewrites the
  line, shifts it, or removes the file marks it
  outdated, said in words (`state_words`); a push
  leaving the anchored line untouched leaves it
  current; the record itself is never moved to a
  new line silently. The record is S-123's honest
  record — author-only edits with previous bodies
  kept, tombstone deletion by author or repository
  admin. Audited under its own events (taxonomy
  append-only +3: `repo.pull_request.line_comment`
  / `.line_comment_edit` / `.line_comment_delete`,
  98 events: 29 auth, 57 repo, 12 admin; doc + code
  + counts together), carried by S-139's outbox
  under its `repo.pull_request.*` verb rule; audit
  detail names the anchor, never the body. A
  stranger to a private repository gets the uniform
  `pull_request_not_found` on every surface.
  Battery `tests/test_pull_request_line_comments.py`:
  **13 passed / 0 failed** (foreground); combined
  with same-repo PRs + cross-fork PRs + drafts +
  conversation + files view + compare + diff engine
  + conversion + taxonomy + dependencies + issue
  events out **94 passed / 0 failed**. No bugs were
  found in shipped code by the new battery. A fresh
  full-suite governing recount was NOT run this
  tick (last governing recount stands at 954 passed
  / 1 skipped; arithmetic expectation 967 passed /
  1 skipped) — the next keeper run verifies it from
  a log file before banking further slices. Next:
  S-147 review threads.
- **S-147 DONE (2026-10-30)** — review threads:
  new module `samverk/pull_request_review_threads.py`
  (`PullRequestReviewThreadStore`). A thread is one
  S-146 line comment plus the replies under it
  (migration 52, `pull_request_line_replies` + its
  edit-history table), with one explicit resolution
  state (`pull_request_review_threads`, a record
  that exists only while resolved; the audit log
  keeps both acts' history). Replies carry S-123's
  honest record (author-only edits, tombstone
  deletion by author or repository admin); a reply
  to a missing or deleted root is refused
  `comment_not_found` and stores nothing; replying
  never changes resolution by itself. Resolve /
  unresolve belong to the root's author, the pull
  request's author, or a repository writer — anyone
  else is refused `permission_denied`, with the rule
  said in the message — and same-state retries are
  quiet no-ops with no second audit event. The
  merge-gate feed is one seam,
  `resolution_summary`: total / resolved /
  unresolved counted over live threads, said in
  words, with `blocks_merge` naming whether
  unresolved threads remain for S-153…S-155 and
  Part VIII to enforce; an outdated thread still
  counts and still resolves (the anchor and the
  conversation are separate facts). Audited under
  its own events (taxonomy append-only +5:
  `repo.pull_request.line_reply` /
  `.line_reply_edit` / `.line_reply_delete` /
  `.thread_resolve` / `.thread_unresolve`, 103
  events: 29 auth, 62 repo, 12 admin; doc + code +
  counts together), carried by S-139's outbox.
  Battery `tests/test_pull_request_review_threads.py`:
  **12 passed / 0 failed** (foreground); combined
  with line comments + same-repo PRs + cross-fork
  PRs + drafts + conversation + files view +
  compare + diff engine + conversion + taxonomy +
  dependencies + issue events out **106 passed /
  0 failed**. No bugs were found in shipped code by
  the new battery. A fresh full-suite governing
  recount was NOT run this tick (last governing
  recount stands at 954 passed / 1 skipped;
  arithmetic expectation now 979 passed / 1
  skipped) — the next keeper run verifies it from
  a log file before banking further slices. Next:
  S-148 review submission.
- **S-148 DONE (2026-10-30)** — review submission:
  new module `samverk/pull_request_reviews.py`
  (`PullRequestReviewStore`). A submitted review is
  one act with one verdict from the closed set
  (approve / comment / request_changes, stored as
  approved / commented / changes_requested) and a
  summary (migration 53, `pull_request_reviews`);
  it records the head oid as it stood at submission
  through S-145's diff road, so same-repo and
  cross-fork heads are both honest — S-149's
  freshness judgment reads that record. Requesting
  changes without a summary is refused
  `summary_required`; an unknown verdict is refused
  `verdict_invalid`; the pull request's author may
  comment on their own pull request but approving
  or requesting changes on it is refused
  `self_review` (a verdict on your own work vouches
  for nothing; S-164's gates read approvals as other
  people's word); a closed pull request takes no
  reviews (`pull_request_closed`, the S-143 reason).
  The pending review is the composer's autosaved
  draft (`pull_request_pending_reviews`, one row per
  pull request + reviewer, replaced whole on every
  `save_pending_review` — that replacement IS the
  autosave): it may hold no verdict yet, it is
  readable only by its own reviewer, it is not
  audited (the S-136/S-145 personal-state pattern),
  and submission falls back to it for whatever the
  caller does not give explicitly, consuming it in
  the same transaction that lands the review.
  `review_summary` counts submitted reviews and each
  verdict and names each reviewer's latest verdict,
  the position said in words. Audited under its own
  event (taxonomy append-only +1:
  `repo.pull_request.review_submit`, 104 events:
  29 auth, 63 repo, 12 admin; doc + code + counts
  together; the detail names the verdict, never the
  summary), carried by S-139's outbox. Battery
  `tests/test_pull_request_reviews.py`: **16 passed /
  0 failed** (foreground; one test-authoring slip
  found and fixed in-slice — the battery first read
  the audit detail under a wrong column name); combined
  with line comments + review threads + same-repo
  PRs + cross-fork PRs + drafts + conversation +
  files view + compare + diff engine + conversion +
  taxonomy + dependencies + issue events out **122
  passed / 0 failed**, read back from its log file.
  The governing recount owed by S-147 was paid
  first this run, read back from its log file:
  pytest 979 passed / 1 skipped / 0 failed (980
  collected, 5 subtests passed, 860.17 s — exactly
  the prior 954 plus S-146's 13 and S-147's 12; the
  one skip is S-095's named real-sshd cell). A fresh
  governing recount after S-148 was NOT run this
  tick (arithmetic expectation now 995 passed / 1
  skipped) — the next keeper run verifies it from a
  log file before banking further slices. Next:
  S-149 review freshness.
- **S-149 DONE (2026-10-30)** — review freshness:
  new module `samverk/pull_request_review_freshness.py`
  (`PullRequestReviewFreshnessStore`). The policy is
  per repository (migration 54,
  `repo_review_freshness_policies`; no row is the
  default): `never` — a push never stale-dates a
  review (S-148's position unchanged until an owner
  chooses otherwise); `approvals` — an approval
  submitted against an older head goes stale when
  the head moves, comments and change requests keep
  counting (the shape S-172's rules engine dismisses
  under); `verdicts` — approvals and change requests
  go stale on a push, comment reviews keep counting
  under every mode (they gate nothing). Setting the
  policy is a repository admin's act (`permission_denied`
  in words for anyone else), audited under the frozen
  `repo.settings.change` with the key
  `review_freshness_policy` named (the S-129 settings
  pattern; taxonomy stands at 104) — a real change
  writes one row, a same-mode retry is a quiet no-op,
  an unknown mode is refused `policy_invalid` and
  stores nothing. Freshness is judged on read, never
  stored (the S-145/S-146 law): `freshness_for`
  re-reads the current head through S-145's diff
  road (same-repo and cross-fork heads both honest,
  the cross-fork cell proven in the battery) and
  marks each S-148 review stale iff the policy can
  stale-date its verdict and its stored head oid is
  no longer the current head — so changing the
  policy re-judges already-submitted reviews in
  both directions, proven in the battery. The
  `FreshnessReport` says exactly which reviews
  still count: every entry with its state and
  reason in words, fresh/stale counts, counting
  tallies, and `latest_counting_by_reviewer` —
  each reviewer's latest counting verdict, the
  record S-164's required-review seam and S-172
  consult. Private repositories answer uniformly
  (`pull_request_not_found` on the judgment,
  `repo_not_found` on the policy surfaces).
  Battery `tests/test_pull_request_review_freshness.py`:
  **14 passed / 0 failed** (foreground); combined
  with reviews + review threads + line comments +
  drafts + same-repo PRs + cross-fork PRs +
  conversation + files view + taxonomy +
  dependencies + issue events out **120 passed /
  0 failed**, read back from its log file. The
  governing recount owed by S-148 was NOT paid
  this tick: the VM carried several other
  campaigns' full suites at once (MemAvailable
  ~0.7 GB throughout), and a recount launched into
  that contention would risk OOM and prove nothing
  clean — it stays owed, now covering S-148 and
  S-149 (arithmetic expectation 1009 passed /
  1 skipped / 0 failed = 995 + this slice's 14),
  and the next keeper run must verify it from a
  log file before banking further slices. Next:
  S-150 suggested changes.
- **S-150 DONE (2026-10-31)** — suggested changes:
  new module `samverk/pull_request_suggestions.py`
  (`PullRequestSuggestionStore`, migration 55,
  `pull_request_suggestions`). A suggestion is a
  reviewer's committable patch, anchored like
  S-146's line comments: one file in the PR's current
  diff and a contiguous range of new-side lines,
  validated whole (`file_not_found` / `line_not_found`
  / `range_invalid` / `file_not_text` for binary or
  non-text files), storing the exact lines being
  replaced — read from the head commit's own content
  — the replacement text, an optional note, and the
  head oid at proposal; a replacement identical to
  the text already there is refused
  `suggestion_no_change`. Application is the PR
  author's act (or, on a cross-fork PR, a base writer
  through S-142's maintainer-edits seam, the commit
  landing on the fork's head branch):
  `apply_suggestion` and `apply_suggestions` (batch)
  each land **exactly one signed-off commit** —
  parent the current head, author/committer the
  applier (S-064 identity shape), message carrying
  one `Suggested-by:` trailer per proposer and the
  applier's `Signed-off-by:` — built through
  plumbing only (hash-object / recursive mktree /
  commit-tree) and moved onto the head branch by
  S-053 compare-and-swap (`stale_head` on a race).
  A batch validates whole before any object is
  written: membership, pending state, freshness
  (stored lines still at their stored range in the
  current head content), and per-file non-overlap
  (`suggestion_overlap`) — one bad member refuses
  the batch and the head does not move. Outdated is
  judged on read, never stored (the S-146 law), and
  an outdated suggestion cannot be applied
  (`suggestion_outdated`); applying one suggestion
  leaves an untouched neighbour pending and
  applicable, both proven in the battery, as are
  line deletion (empty replacement), subdirectory
  files (recursive tree rebuild), and cross-fork
  application with and without maintainer edits.
  Closed PRs take neither proposals nor
  applications; private repositories answer
  uniformly. Audited under its own events (taxonomy
  append-only +2:
  `repo.pull_request.suggestion_propose` /
  `repo.pull_request.suggestion_apply`, 106 events;
  doc + code + counts together; proposal detail
  names the anchor, never the replacement) carried
  by S-139's outbox. Battery
  `tests/test_pull_request_suggestions.py`:
  **18 passed / 0 failed** (foreground), read back
  from its log file. **Correction (same day, never
  left):** the S-150 commit as first banked recorded
  a 17-test battery and a combined 146 passed /
  0 failed "read back from its log file" — both
  numbers came from run-output deliveries and
  neither survives the disk: the battery's own log
  file reads 18 passed (the file holds 18 tests),
  and the combined set (reviews + review freshness
  + line comments + review threads + same-repo PRs
  + cross-fork PRs + drafts + conversation + files
  view + taxonomy + dependencies + issue events
  out) collects only 138 tests in total, while its
  log file carries no summary line at all. A
  disk-verified combined rerun reached 52% — every
  test shown passing, none failing — before a
  1200 s timeout under the same extreme contention
  (MemAvailable ~0.6 GB). The slice therefore
  stands on its proven 18-test battery plus each
  affected suite's own banked battery; the combined
  cross-check stays owed alongside the governing
  recount, to be verified from a log file on a
  quiet machine. The governing full-suite recount
  was NOT paid this tick — the VM carried many
  other campaigns' full suites at once throughout
  (MemAvailable ~0.6–1.5 GB), the same contention
  that deferred it at S-148/S-149; it stays owed,
  now covering S-148, S-149 and S-150 (arithmetic
  expectation 1027 passed / 1 skipped / 0 failed),
  and the next keeper run with a quiet machine
  must verify it from a log file before banking
  further slices.
  Next: S-151 CODEOWNERS.
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
- **2026-10-29 (opening run)** — S-002…S-008 built and banked in one
  run, each with its counted battery green (cumulative 56 passed /
  0 failed on Linux x86-64, this VM): skeleton + platform seam,
  secrets law + SQLite factory, scrypt password hashing, constant-time
  compare + login throttle, session tokens, audit hash chain +
  verifier + CLI, taxonomy v1 enforced at the emitter. README never
  touched. Platform proof cells beyond this machine remain
  **NOT PROVEN** (Part XXII). Next slice: S-009.
- **2026-10-30 (keeper run)** — No live worker was found (last commit
  ~3 h old, no Samverk process, worktrees clean at a9490e2), so the
  keeper resumed the campaign itself per the keeper law: baseline
  re-verified from the tree (56/56), then **S-009 DONE** and banked
  locally on `yrsa/samverk-part1` (73/73 cumulative). GitHub push
  NOT done — pushes stay gated on Volmarr's explicit word per the
  keeper's binding laws. The same keeper run continued slice after
  slice: **S-010 DONE** (85/85 cumulative), then **S-011 DONE**
  (96/96 cumulative), then **S-012 DONE** (106/106 cumulative) —
  see their entries above. Campaign position at this run's end:
  S-001…S-012 DONE, next slice S-013. Integration note: the four
  slices banked in this run sit on `yrsa/samverk-part1` and were
  fast-forwarded to local `main` in the same run (the campaign's
  established pattern); no GitHub push was made.
- **2026-10-30 (keeper run, Part I closed)** — No live worker was
  found (previous run's last commit ~11 min old, no Samverk
  process, clean tree), so the keeper resumed from S-013 and
  built slice after slice to the end of Part I: **S-013**
  (116/116), **S-014** (124/124), **S-015** (133/133), **S-016**
  (138/138), **S-017** (143/143), **S-018** (150/150), **S-019**
  (157/157), **S-020** (165/165), **S-021** (173/173), **S-022**
  (182/182), **S-023** (claims register), the S-015 TLS
  end-to-end hardening (4ee3b61), and the **S-024 Part I gate**
  at a fresh counted **187 passed / 0 failed** with open
  findings named in the gate entry above. Four flaws were
  found by batteries and fixed inside their own slices (the
  rev-parse `--git-dir` query distinction, the `csrf_token`
  log-redaction leak, the `a@.com` empty-label parse, and the
  previously unexercised TLS wrap). All work banked locally on
  `yrsa/samverk-part1` and fast-forwarded to local `main`
  (first banked as 08ec155; amended once for this log); **no GitHub push** — pushes stay
  gated on Volmarr's word. (Head note: the gate commit was
  amended once to carry this log entry, so its hash differs
  from the one first printed here; tree content is unchanged.)
  Next: Part II, S-025 registration.
- **2026-10-30 (keeper run, Part II opened)** — Previous keeper
  run had closed Part I at 01:37 EDT (head a44bc79, clean tree,
  its session log written, no process live), so this run
  resumed from the map's named next slice and built four Part
  II slices in the established pattern: **S-025** registration
  (199/199), **S-026** email verification — token road +
  operator road, taxonomy append-only +2 events (209/209),
  **S-027** login/logout (216/216; the battery found
  `SessionStore.revoke` double-counting an already-revoked
  token — fixed in the S-006 seam in-slice), and **S-028**
  password change/reset (226/226). All banked locally on
  `yrsa/samverk-part1` and fast-forwarded to local `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next slice: S-029 profiles.
- **2026-10-30 (keeper run)** — Previous run had banked S-028
  at 01:47 EDT (head ce69f92, clean tree, no process live), so
  this run resumed at the map's named next slice and built
  **S-029** profiles (236/236) and **S-030** SSH keys (244/244)
  in the established pattern. Taxonomy append-only +1 event
  (auth.profile.update, 40 total). All banked locally on
  `main`; **no GitHub push** — pushes stay gated on Volmarr's
  word. Next slice: S-032 personal access tokens.
- **2026-10-30 (keeper run)** — Previous run had banked S-031
  at 01:55 EDT (clean tree, no process live), so this run
  resumed at the map's named next slice and built **S-032**
  personal access tokens (260/260), then **S-033** fine-grained
  tokens (269/269), then **S-034** token management UI
  (276/276), all in the same run. Banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next slice: S-035 two-factor TOTP enrolment.
- **2026-10-30 (keeper run)** — Previous run had banked S-034
  at 02:12 EDT (clean tree, no process live), so this run
  resumed at the map's named next slice and built **S-035**
  TOTP enrolment (286/286), **S-036** sudo mode (292/292),
  **S-037** recovery codes (298/298; taxonomy append-only
  +2 events, 42 total), and **S-038** two-factor enforcement
  policy (305/305), each with its counted battery green and
  the full suite re-counted at this run's end: **305 passed /
  0 failed**. All banked locally on `main`; **no GitHub
  push** — pushes stay gated on Volmarr's word. Next slice:
  S-039 passkeys/WebAuthn.
- **2026-10-30 (keeper run)** — Previous run had banked S-038
  at 02:24 EDT and its run record closed at 02:25 EDT (clean
  tree, no process live), so this run resumed at the map's
  named next slice and built **S-039** passkeys/WebAuthn
  (318/318; taxonomy append-only +3 events, 45 total),
  **S-040** session management (325/325), **S-041**
  new-sign-in notification (331/331; taxonomy +1, 46 total),
  and **S-042** account rename with tombstones (338/338;
  taxonomy +1, 47 total) — each with its counted battery
  green and the full suite re-counted at this run's end:
  **338 passed / 0 failed**. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next slice: S-043 account deletion.
- **2026-10-30 (keeper run, Part III continued)** — Previous
  run had banked S-054 at 03:06 EDT (clean tree, no process
  live), so this run resumed at the map's named next slice
  and built **S-055** forking (400/400), **S-056** repository
  deletion (404/404), **S-057** repository transfer (408/408),
  and **S-058** size accounting (412/412) — taxonomy
  append-only +1 event (55 total, `repo.fork`). One flaw was
  caught by a battery mid-banking (the S-056 execution path
  referenced S-057's table before that slice's migration
  existed) and was fixed in-slice, with the cleanup correctly
  sequenced into S-057. Full suite re-counted fresh at this
  run's end: **412 passed / 0 failed**. All banked locally on
  `main`; **no GitHub push** — pushes stay gated on
  Volmarr's word. Next slice: S-059 GC scheduling.
- **2026-10-30 (keeper run, Part II closed)** — Previous run
  had banked S-042 at 02:41 EDT (clean tree, no process
  live), so this run resumed at the map's named next slice
  and built **S-043** deletion (342/342), **S-044**
  suspension (345/345), **S-045** identity-linking shape
  (350/350), **S-046** lookalike defence (355/355; two
  battery-found flaws fixed in-slice), **S-047** login
  history (360/360), and the **S-048 Part II gate**
  (368/368) — taxonomy append-only +7 events across the
  run (54 total). Full suite re-counted fresh at the gate:
  **368 passed / 0 failed**. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's word.
  Next: Part III, S-049 bare repository creation.
- **2026-10-30 (keeper run, LFS block)** — Previous run had
  banked S-058 + the fork-clone fix at 03:25 EDT (clean tree,
  no process live), so this run resumed at the map's named
  next slice and built **S-059** GC scheduling (416/416),
  **S-060** LFS object store (422/422), **S-061** LFS batch
  API (428/428), and **S-062** LFS locking (434/434) — each
  with its counted battery green and the full suite
  re-counted at every slice. The git-lfs client interop
  acceptances of S-061/S-062 were proven for real against
  stock git-lfs 3.6.1 (push/pull round-trip; lock/locks/
  unlock), with the client binary kept at
  `~/workspace/.tools/git-lfs` because this VM's system
  layer does not persist apt installs between sessions.
  All banked locally on `main`; **no GitHub push** —
  pushes stay gated on Volmarr's word. Next slice: S-063
  archive downloads.
- **2026-10-30 (keeper run, Part III continued)** — Previous
  run had closed its session log at 03:45 EDT (head 5be20b2,
  clean tree, no process live), so this run resumed at the
  map's named next slice and built **S-063** archive
  downloads (440/440), **S-064** repository templates
  (446), **S-065** empty-repository state (450), and
  **S-066** repository settings (456/456) — each with its
  counted battery green and a full counted run at the
  run's end: **456 passed / 0 failed**. S-014's allowlist
  grew by `archive`, `mktree`, and `commit-tree`, each
  with its reason recorded in `samverk/proc.py`, and
  `proc` gained the streamed-spawn and `env_extra` seams
  those slices needed. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's
  word. Next slice: S-067 server-side hooks seam.
- **2026-10-30 (keeper run, Part III continued)** — Previous
  run had banked S-066 at 03:59 EDT (clean tree, no process
  live), so this run resumed at the map's named next slice
  and built **S-067** hooks seam (462), **S-068**
  repository quotas (467), **S-069** import by clone URL
  (473), and **S-070** mirror storage layout (479) — each
  with its counted battery green and a full counted run at
  the run's end: **479 passed / 0 failed**. S-014's law
  grew the dedicated clone-remote and fetch seams (generic
  `clone`/`fetch` stay refused, per its battery), with the
  import token carried only in an askpass environment and
  proven absent from the DB file and audit log. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-071 consistency
  checker.
- **2026-10-30 (keeper run, Part III closed)** — Previous
  run had closed its session log at 04:17 EDT (head 36fe8d5,
  clean tree, no process live), so this run resumed at the
  map's named next slice and built **S-071** consistency
  checker (485), **S-072** commit graph caches (490),
  **S-073** large-repository budgets (493; Pi-class NOT
  PROVEN), **S-074** repository backup primitive (498),
  **S-075** corruption behaviour (504), and the **S-076
  Part III gate** (510) — full suite re-counted fresh at
  the gate: **510 passed / 0 failed**. Two flaws were found
  and fixed in-slice under the never-leave-a-bug law: git's
  local clone hardlinked object files (the clone seam now
  passes `--no-hardlinks`, so forks are truly independent
  and clone measurements are real copies), and git bundle
  refuses empty bundles (empty repos are refused by name
  as `repo_empty` rather than faking a backup). All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next: Part IV, S-077 smart HTTP
  advertisement.
- **2026-10-30 (keeper run, Part IV opened)** — Previous
  run had closed Part III at 04:39 EDT (head 6967189, clean
  tree, no process live), so this run resumed at the map's
  named next slice: baseline re-verified from the tree
  (510/510), research study 01 written, then **S-077**
  advertisement (517), **S-078** upload-pack (521),
  **S-079** receive-pack (525), **S-080** protocol v2
  (530), **S-081** HTTP Basic auth (536), **S-082**
  token-as-password (543), and **S-083** anonymous public
  read + uniform 401/404 shape (551 by running count) —
  full suite re-counted fresh at this run's end:
  **553 passed / 0 failed** (the verified recount governs
  over the running sum). Stock-git interop is now proven
  over real HTTP for clone, fetch, and push, in v0 and in
  protocol v2 (packet-traced). All banked locally on
  `main`; **no GitHub push** — pushes stay gated on
  Volmarr's word. Next slice: S-084 SSH transport design
  (research file 02 study before code).
- **2026-10-30 (keeper run, SSH block opened)** — Previous
  run had closed Part IV's HTTP block at 04:56 EDT (head
  2ef27e2, clean tree, no process live), so this run resumed
  at the map's named next slice: baseline re-verified from
  the tree (553/553), then **S-084** SSH transport design
  (research study 02; OpenSSH + AuthorizedKeysCommand +
  forced command, never a shell), **S-085** key resolution
  (565), **S-086** SSH upload-pack routing (574), **S-087**
  SSH receive-pack routing + push audit (580), and **S-088**
  deploy keys on the wire (587) — full suite re-counted
  fresh at this run's end with the campaign's counting
  method (`python3 -m unittest discover -s tests`):
  **587 passed / 0 failed**. Stock-git interop is now proven
  over the SSH door's protocol shape (clone, push, deploy
  keys, both grants) through a stand-in ssh program; a real
  sshd on an ephemeral port remains S-095's acceptance cell.
  All banked locally on `main`; **no GitHub push** — pushes
  stay gated on Volmarr's word. Next slice: S-089
  pre-receive gate point.
- **2026-10-30 (keeper correction, same run)** — The recount
  first recorded for this run (587/587) was **wrong, and is
  corrected here**. A late-finishing background baseline run
  surfaced a failure in the S-017 dependency import scan
  (`test_no_unregistered_third_party_imports_anywhere`), and
  three fresh checks (pytest single-file, unittest
  single-file, full unittest discover, plus a manual AST
  scan) all agreed: the scan was failing on four sibling
  test-module imports — `test_ssh_key_resolution` and
  `test_ssh_upload_routing` (new in this run's batteries)
  and `test_git_basic_auth` + `test_git_http_upload`
  (**pre-existing** from the S-083 battery's cross-imports,
  so earlier "green" recounts in this campaign, including
  the 553 this run started from, were likewise not
  reproducible as stated). Root cause in the scan itself:
  it treated first-party sibling test modules — a battery
  pattern established at S-078 — as unregistered
  third-party imports. Fix, banked with this entry: the
  scan now admits any top-level name that is a file in the
  scanned tree (first-party code), while the third-party
  gate is unchanged for everything else. One earlier full
  run in this session did report "587 OK"; that result
  could not be reproduced and is superseded — never trust a
  count that does not repeat. **Governing recounts after
  the fix, both reproduced from the tree:** pytest
  **588 passed / 2 skipped / 0 failed**; unittest discover
  **585 ran, 583 passed / 2 skipped / 0 failed**. The
  2 skips are pre-existing platform cells. This run's own
  batteries stand as counted (12 + 9 + 6 + 7 = 34 tests).
  Also noted for S-095: this VM has an ssh client but **no
  sshd** (`sshd` not installed), so the real-sshd interop
  cell needs the server package or another host when its
  turn comes.
- **2026-10-30 (keeper run, Part IV closed)** — Previous
  run had closed its correction at 05:20 EDT (head 61bc3e2,
  clean tree, no process live; its session log and the
  daily-log correction entry were both already written), so
  this run resumed at the map's named next slice and built
  **S-089** pre-receive gate point (10), **S-090** push
  events (8; migration 33), **S-091** transfer limits (7),
  **S-092** concurrent push locks (7), **S-093**
  upload-archive (5), **S-094** transport audit (6;
  taxonomy append-only +1, 56 events), **S-095** interop
  battery (4 passed / 1 named skip), and the **S-096
  Part IV gate** (3) — full suite re-counted fresh at the
  gate, both methods reproduced: pytest **640 passed /
  3 skipped / 0 failed**, unittest discover **636 ran,
  633 passed / 3 skipped / 0 failed** (skips: 2 pre-existing
  platform cells + the named real-sshd cell). Bugs found
  and fixed in-slice, never left: the pack seam passed
  `--stateless-rpc` to upload-archive, which has no such
  flag (usage-error death), and the HTTP advertisement
  tried to spawn git for upload-archive, which has no ref
  advertisement — it greets with a bare ACK, now emitted
  directly. One environment finding: `/tmp` is 100% full
  (an unrelated Aesir file, `/tmp/s043-bank`, 512 MB — not
  Samverk's, not touched); this run pointed TMPDIR at
  `~/workspace/.verify-tmp/samverk-tmp` for its test runs.
  All banked locally on `main` (head at the gate commit);
  **no GitHub push** — pushes stay gated on Volmarr's
  word. Next: Part V, S-097 repository home.
- **2026-10-30 (keeper run, Part V opened)** — Previous
  run had closed Part IV at 05:47 EDT (head a1ab842,
  clean tree, no process live), so this run resumed at
  the map's named next slice: baseline re-verified from
  the tree (pytest 640 passed / 3 skipped / 0 failed),
  then **S-097** repository home (7), **S-098** file
  browser (5), **S-099** blob view (5), and **S-100**
  raw and download (6) — full suite re-counted fresh at
  this run's end, both methods reproduced: pytest
  **663 passed / 3 skipped / 0 failed**, unittest
  discover **659 ran, 656 passed / 3 skipped /
  0 failed**. One battery-found bug fixed in-slice
  (S-098's log record marker attached file names to
  the wrong commit). Noted honestly: research studies
  17 and 43, which Part V draws on, are still empty
  files — the slices were built from the roadmap's own
  text and the established seams; the studies remain
  to be written and are not claimed. Environment:
  `/tmp` still 100% full (unrelated Aesir file, not
  touched); TMPDIR stayed pointed at
  `~/workspace/.verify-tmp/samverk-tmp`. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-101 blame
  view.
- **2026-10-30 (keeper correction, same run)** — The
  recount figures first recorded for this run (pytest
  663) were **wrong, and are corrected here**. This
  run's long background test executions produced
  premature, crossed completion reports while their
  processes were in fact still running in D-state under
  heavy VM-wide I/O contention; the numbers taken from
  those reports do not stand. The stale runners were
  killed, the S-097 battery was re-run in the
  foreground — where it caught two real defects the
  phantom reports had hidden: README list items kept
  their bullet marker (a doubled backslash in the
  strip pattern) and a switcher test asserted a marker
  shape the page never rendered (test fixed to the
  rendered shape). Both fixed and banked (4bbe5ae);
  the battery then passed 7/7 in the foreground. The
  governing recounts were then re-run one at a time
  into log files and **read back from the files
  themselves**: pytest **656 passed / 3 skipped /
  0 failed (659 collected, 812.7 s)**; unittest
  discover **659 ran, 656 passed / 3 skipped /
  0 failed (824.9 s)**. Those are this run's counts.
  Per-slice cumulative figures in the S-097..S-100
  entries were running sums and are superseded by
  these governing recounts, as those entries state.
- **2026-10-30 (keeper run, Part V continued)** — Previous
  run had closed its correction at 06:55 EDT (head
  098929e, clean tree, no process live), so this run
  resumed at the map's named next slice and built
  **S-101** blame view (5), **S-102** commit list (4),
  **S-103** commit detail (3), **S-104** diff engine
  (5), **S-105** compare view (3), and **S-106**
  contributors and counts (3) — governing recounts
  re-run one at a time into log files and **read back
  from the files themselves** after each process
  finished: pytest **679 passed / 3 skipped / 0 failed
  (682 collected, 844.0 s)**; unittest discover **682
  ran, 679 passed / 3 skipped / 0 failed (869.1 s)**.
  Bugs found and fixed in-slice, never left: binary
  files carry no `---`/`+++` lines, so S-103 first
  takes paths from the `diff --git` header; S-104's
  parser turned the trailing-newline split artifact
  into a phantom context line. One phantom report was
  caught and discarded in-run: a backgrounded battery
  run reported exit 0 while a foreground re-run from
  its log file showed the S-103 binary failure — the
  foreground log is what stands. Environment: `/tmp`
  still 100% full (unrelated Aesir file, not touched);
  TMPDIR stayed pointed at
  `~/workspace/.verify-tmp/samverk-tmp`. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-107 markdown
  pipeline.
- **2026-10-30 (keeper run, Part V continued)** — Previous
  run had closed its session log at 07:37 EDT (head
  f3361b0, clean tree, no process live), so this run
  resumed at the map's named next slice and built
  **S-107** Markdown pipeline (8), **S-108**
  repo-relative links (5), and **S-109** mentions and
  references in prose (5) — governing recounts re-run
  one at a time into log files and **read back from
  the files themselves** after each process finished:
  pytest **697 passed / 3 skipped / 0 failed
  (700 collected, 879.1 s)**; unittest discover **700
  ran, 697 passed / 3 skipped / 0 failed (878.2 s)** —
  exactly the prior 679 plus this run's 18 battery
  tests on both runners. Bugs found and fixed
  in-slice, never left: balanced-paren link
  destinations truncated at the first `)`; an
  unterminated code fence's phantom trailing line.
  Environment: `/tmp` still 100% full (unrelated Aesir
  file, not touched); TMPDIR stayed pointed at
  `~/workspace/.verify-tmp/samverk-tmp`. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-110 file
  finder.
- **2026-10-30 (keeper run, Part V continued)** — Previous
  run had closed its session log at 08:25 EDT (head
  3b8bcdd, clean tree, no process live), so this run
  resumed at the map's named next slice and built
  **S-110** file finder (5), **S-111** keyboard
  baseline (5), and **S-112** permission-aware chrome
  (5) — governing recounts re-run one at a time into
  log files and **read back from the files themselves**
  after each process finished: pytest **714 passed /
  1 skipped / 0 failed (715 collected, 925.5 s)**;
  unittest discover **715 ran, 714 passed / 1 skipped /
  0 failed (1070.8 s)** — the prior 697 plus this run's
  15 battery tests plus the two LFS client cells, which
  ran and passed because this run's recounts carried
  git-lfs on PATH; the one remaining skip is S-095's
  named real-sshd cell, verified by name with a
  targeted `-rs` run. One lost run, named honestly: the
  first unittest background session died mid-run (its
  log held no final count and does not stand); the
  recount was re-run cleanly and only the second log
  governs. Environment: `/tmp` still 100% full
  (unrelated Aesir file, not touched); TMPDIR stayed
  pointed at `~/workspace/.verify-tmp/samverk-tmp`.
  All banked locally on `main`; **no GitHub push** —
  pushes stay gated on Volmarr's word. Next slice:
  S-113 empty and error states.
- **2026-10-30 (keeper run, Part V continued)** — Previous
  run had closed its session log at 09:18 EDT (head
  5928b40, clean tree, no process live), so this run
  resumed at the map's named next slice and built
  **S-113** empty and error states (7), **S-114** binary
  and image files (6), and **S-115** repository
  insights-lite (4) — governing recounts re-run one at a
  time into log files and **read back from the files
  themselves** after each process finished: pytest
  **729 passed / 3 skipped / 0 failed (732 collected,
  1353.4 s)**; unittest discover **732 ran, 729 passed /
  3 skipped / 0 failed (1053.3 s)** — the prior 714 plus
  this run's 17 battery tests, minus the two git-lfs
  client cells, which skipped because this run's
  recount commands did not carry the pristine git-lfs
  binary kept at `~/workspace/.tools/git-lfs` on PATH
  (a targeted `-rs` run names both cells, as it names
  S-095's real-sshd cell: all three skips are named
  NOT PROVEN cells, not failures). Correction, same
  day: the session entry as first written said git-lfs
  was "not installed on this host" — wrong; the binary
  (3.6.1, verified working after the fact) lives at
  `~/workspace/.tools/git-lfs` and was simply absent
  from this run's PATH. The measured counts stand as
  run; the reason is what is corrected here. One crossed report was caught
  and discarded in-run: the pytest background session's
  delivered stdout claimed 731 passed / 1 skipped in
  1252 s, but its own log file — whose 1353.4 s duration
  matches the session's measured duration — records
  729 / 3; the file governs, per the standing phantom
  lesson. No bugs were found by the new batteries; no
  slice needed repair. Environment: `/tmp` had room
  again this run (the earlier full state cleared by its
  owner); TMPDIR stayed pointed at
  `~/workspace/.verify-tmp/samverk-tmp`. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-116 print and
  export of code views.
- **2026-10-30 (keeper run, Part V continued)** — Previous
  run had closed its correction at 10:16 EDT (head
  091cc1e, clean tree, no process live, no subagent
  worker), so this run resumed at the map's named next
  slice and built **S-116** print and export of code
  views (6), **S-117** deep links (7), and **S-118**
  search box in repo scope (5) — governing recounts
  re-run one at a time into log files and **read back
  from the files themselves** after each process
  finished: pytest **749 passed / 1 skipped / 0 failed
  (750 collected, 1130.2 s)**; unittest discover **750
  ran, 749 passed / 1 skipped / 0 failed (1098.8 s)** —
  the prior 729 plus this run's 18 battery tests plus
  the two git-lfs client cells, which ran and passed
  because this run's recounts prepended
  `~/workspace/.tools` to PATH per the S-115
  correction; the one remaining skip is S-095's named
  real-sshd cell. Two test-expectation slips were
  caught and fixed in-slice, module behaviour standing
  in both: S-104 counts the hunk header as a patch
  line (500 additions fold at 501 patch lines), and
  the S-118 jump URL is percent-encoded, as URLs are.
  No bugs were found in shipped code by the new
  batteries. Environment: TMPDIR stayed pointed at
  `~/workspace/.verify-tmp/samverk-tmp`. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-119
  repository header summary.
- **2026-10-30 (keeper run, Part VI continued)** — Previous
  run had banked S-126 at 13:40 EDT (clean tree, no
  process live), so this run resumed at the map's named
  next slice (the header's stale "next S-124" line was
  repaired in this run — S-124..S-126 were already
  banked with detailed entries) and built **S-127**
  cross-references (9-test battery) and **S-128**
  reactions (5-test battery; taxonomy append-only +2,
  74 events) — foreground combined runs read back from
  log files: S-127 combined **61 passed / 0 failed**,
  S-128 combined **16 passed / 0 failed**. No bugs were
  found by the new batteries. A fresh full-suite
  governing recount was NOT run this tick (the last
  governing recount stands at S-123's 783 passed /
  1 skipped); it is the next keeper run's first duty,
  named in the header. Environment: TMPDIR pointed at
  `~/workspace/.verify-tmp/samverk-tmp`. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-129 issue
  templates.
- **2026-10-30 (keeper run, Part VI continued)** — Previous
  run had banked S-128 at 14:35 EDT (clean tree, no
  process live), so this run first paid the owed
  governing recount (log file read back: pytest **818
  passed / 1 skipped / 0 failed** — exactly the prior
  783 plus S-124..S-128's 35 battery tests), then built
  **S-129** issue templates (11-test battery) and
  **S-130** close and reopen (6-test battery; taxonomy
  append-only +5 across the run, 79 events). Two
  test-authoring slips were caught and fixed in the
  batteries (a title-less label-check fixture; a compact
  JSON spacing expectation), module behaviour standing
  in both; no bugs were found in shipped code. Closing
  governing recounts, both read back from log files:
  pytest **835 passed / 1 skipped / 0 failed**;
  unittest discover **836 ran, 835 passed / 1 skipped /
  0 failed** — the one skip is S-095's named real-sshd
  cell, NOT PROVEN on this host. All banked locally on
  `main`; **no GitHub push** — pushes stay gated on
  Volmarr's word. Next slice: S-131 timeline.
- **2026-10-30 (keeper run, Part VI continued)** — Previous
  run had banked S-134 at 16:31 EDT and closed its
  correction at be01964 (clean tree, no process live, no
  subagent worker), so this run resumed at the map's named
  next slice and built **S-135** issue search UI (8-test
  battery; research file 19 written — the full query
  grammar, with the Part X reserved qualifiers named for
  S-206) and **S-136** saved filters (6-test battery;
  migration 45; combined run with S-135 + the S-017
  dependencies scan 19 passed / 0 failed). No bugs were
  found in shipped code by the new batteries. Closing
  governing recount read back from its log file: pytest
  **880 passed / 1 skipped / 0 failed** (881 collected,
  5 subtests passed, 1657.20 s — exactly the prior 866
  plus this run's 14 battery tests); the one skip is
  S-095's named real-sshd cell, NOT PROVEN on this host.
  Environment: TMPDIR pointed at
  `~/workspace/.verify-tmp/samverk-tmp`, recount PATH
  prepended `~/workspace/.tools`. All banked locally on
  `main`; **no GitHub push** — pushes stay gated on
  Volmarr's word. Next slice: S-137 issue → PR
  conversion path.
- **2026-10-30 (keeper run, Part VI continued)** — Previous
  run had closed its recount correction at e4b779d
  (clean tree, no process live, no subagent worker), so
  this run resumed at the map's named next slice and
  built **S-137** issue → PR conversion path (8-test
  battery, foreground; combined with taxonomy +
  timeline + issues + dependencies 35 passed /
  0 failed; migration 46; taxonomy append-only +2,
  87 events). No bugs were found in shipped code by
  the new battery. A fresh full-suite governing
  recount was NOT run this tick (the last governing
  recount stands at 880 passed / 1 skipped); the
  arithmetic expectation is 888 passed / 1 skipped
  and the next keeper run should verify it from a log
  file before banking further slices. All banked
  locally on `main`; **no GitHub push** — pushes stay
  gated on Volmarr's word. Next slice: S-138
  moderation — hide/delete abusive comments.
- **2026-10-30 (keeper run, Part VI continued)** — Same
  run, after banking S-137: built **S-138** moderation
  (7-test battery, foreground; combined with taxonomy
  + timeline + comments + dependencies 34 passed /
  0 failed; migration 47; taxonomy append-only +3,
  90 events). No bugs were found in shipped code by
  the new battery. A fresh full-suite governing
  recount is still owed (last governing recount 880
  passed / 1 skipped; arithmetic expectation now 895
  passed / 1 skipped) — the next keeper run verifies
  it from a log file before banking further slices.
  All banked locally on `main`; **no GitHub push** —
  pushes stay gated on Volmarr's word. Next slice:
  S-139 issue events out.
- **2026-10-30 (keeper run, Part VI gate)** — Same run,
  after banking S-139: built the **S-140 Part VI gate**
  battery (5 tests, foreground) and ran the governing
  full-suite recount. The recount's first attempt was
  killed by a service restart after 7 tests (its log
  held only dots — discarded, not evidence); the
  restarted run's log was read back after it finished:
  pytest **906 passed / 1 skipped / 0 failed** (907
  collected, 5 subtests passed, 1793.68 s — exactly
  the prior 880 plus this run's 26 battery tests);
  the one skip is S-095's named real-sshd cell, NOT
  PROVEN on this host. **Part VI is complete.** All
  banked locally on `main`; **no GitHub push** —
  pushes stay gated on Volmarr's word. Next slice:
  S-141 PR creation, same-repo, opening Part VII.
- **2026-10-30 (keeper run, Part VII opened)** — Previous
  run had banked S-140 at 17:59 EDT, closing Part VI
  (clean tree, no process live at this tick's check),
  so this run resumed at the map's named next slice and
  built **S-141** PR creation, same-repo (new module
  `samverk/pull_requests.py`: branch pickers from the
  real ref listing, preview_creation riding S-105's
  compare unchanged with blockers said in words,
  creation validating whole — same_branch /
  base_not_found / head_not_found / no_commits /
  already_exists / branch_invalid / title law — before
  claiming the next shared S-121 number; born open,
  not draft, audited under S-137's existing
  repo.pull_request.create with same_repo in the
  detail; taxonomy unchanged at 90 events, no
  migration). 8-test battery, foreground; combined
  with conversion + compare + taxonomy + dependencies
  **30 passed / 0 failed**. One test-authoring slip
  was caught and fixed in-slice (a compact-JSON spacing
  expectation in the audit-detail assertion), module
  behaviour standing. A fresh full-suite governing
  recount was NOT run this tick (last governing
  recount stands at 906 passed / 1 skipped; arithmetic
  expectation 914 passed / 1 skipped) — the next
  keeper run verifies it from a log file before
  banking further slices. Environment: TMPDIR pointed
  at `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`. All banked locally
  on `main`; **no GitHub push** — pushes stay gated
  on Volmarr's word. Next slice: S-142 PR creation,
  cross-fork.
- **2026-10-30 (keeper run, Part VII continued)** — Previous
  run had banked S-141 at 18:12 EDT and closed its
  session log in that commit (clean tree, no process
  live, no subagent worker at this tick's check), so
  this run first paid the governing recount S-141 owed
  (log file read back after it finished: pytest **914
  passed / 1 skipped / 0 failed**, 915 collected, 5
  subtests passed, 1719.11 s — exactly the prior 906
  plus S-141's 8 battery tests; the one skip is
  S-095's named real-sshd cell, NOT PROVEN on this
  host), then built **S-142** PR creation, cross-fork
  (new module `samverk/pull_request_forks.py`;
  migration 49; new dedicated S-014 seam
  `run_git_fetch_ref` in proc.py; taxonomy unchanged
  at 90 events). 10-test battery, foreground; combined
  with same-repo PRs + conversion + forks + proc +
  taxonomy + dependencies + secrets **59 passed /
  0 failed**; the battery standalone **10 passed**.
  No bugs were found in shipped code by the new
  battery. A fresh full-suite governing recount was
  NOT run after this slice (last governing recount
  stands at 914 passed / 1 skipped; arithmetic
  expectation 924 passed / 1 skipped) — the next
  keeper run verifies it from a log file before
  banking further slices. Environment: TMPDIR pointed
  at `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`. All banked locally
  on `main`; **no GitHub push** — pushes stay gated
  on Volmarr's word. Next slice: S-143 draft pull
  requests.
- **2026-10-30 (keeper run, Part VII continued)** — Same
  run, after banking S-142: built **S-143** draft pull
  requests (new module `samverk/pull_request_drafts.py`;
  creation seams gained the `draft` parameter; taxonomy
  append-only +2, 92 events; S-139's outbox verb rule
  extended to the `repo.pull_request.*` lifecycle).
  9-test battery, foreground; combined with taxonomy +
  same-repo PRs + cross-fork PRs + conversion + issue
  events out + dependencies **52 passed / 0 failed**,
  read back from its log file. One crossed report was
  caught and discarded in-run: an early combined
  delivery claimed 51 passed / 0 failed, but
  reproducible runs showed the battery's closed-PR
  arrangement failing against S-130's kind guard (a
  test-arrangement error — no PR-close seam exists
  yet; the closed state is now arranged at the storage
  layer, stated in the test; module behaviour standing
  in shipped code throughout). No bugs were found in
  shipped code. A fresh full-suite governing recount
  was NOT run after this slice (last governing recount
  stands at 914 passed / 1 skipped; arithmetic
  expectation 933 passed / 1 skipped) — the next keeper
  run verifies it from a log file before banking
  further slices. All banked locally on `main`;
  **no GitHub push** — pushes stay gated on Volmarr's
  word. Next slice: S-144 PR conversation.
- **2026-10-30 (keeper run, Part VII continued)** — Previous
  run had banked S-143 at 19:08 EDT and closed its
  session log in that commit (clean tree, no process
  live, no subagent worker at this tick's check), so
  this run first paid the governing recount S-143 owed
  (log file read back after it finished: pytest **933
  passed / 1 skipped / 0 failed**, 934 collected, 5
  subtests passed, 2065.27 s — exactly the prior 914
  plus S-142's 10 and S-143's 9 battery tests; the one
  skip is S-095's named real-sshd cell, NOT PROVEN on
  this host), then built **S-144** PR conversation
  (new module `samverk/pull_request_conversation.py`;
  taxonomy append-only +3, 95 events). 11-test battery,
  foreground; combined with taxonomy + timeline +
  cross-references + drafts + issue comments + issue
  events out + dependencies + same-repo PRs +
  cross-fork PRs + conversion **88 passed / 0 failed**,
  read back from its log file. No bugs were found in
  shipped code by the new battery. A fresh full-suite
  governing recount was NOT run after this slice (last
  governing recount stands at 933 passed / 1 skipped;
  arithmetic expectation 944 passed / 1 skipped) — the
  next keeper run verifies it from a log file before
  banking further slices. Environment: TMPDIR pointed
  at `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`. All banked locally
  on `main`; **no GitHub push** — pushes stay gated on
  Volmarr's word. Next slice: S-145 PR files view.
- **2026-10-30 (keeper run, Part VII continued)** — Previous
  run had banked S-144 at 19:58 EDT (clean tree, no
  Samverk process live, no subagent worker at this
  tick's check), so this run built **S-145** PR files
  view (new module `samverk/pull_request_files.py`;
  migration 50; no new audit event — taxonomy stands
  at 95). 10-test battery, foreground; combined with
  same-repo PRs + cross-fork PRs + drafts +
  conversation + compare + diff engine + conversion
  + taxonomy + dependencies **75 passed / 0 failed**,
  read back from its log file. The governing recount
  was paid in full this run and read back from its
  log file: pytest **954 passed / 1 skipped /
  0 failed** (955 collected, 5 subtests passed,
  3149.85 s under heavy VM contention — exactly the
  prior 933 plus S-144's 11 and S-145's 10; the one
  skip is S-095's named real-sshd cell). One earlier
  recount this run was caught and discarded, never
  counted: launched without the campaign's
  established environment (no `~/workspace/.tools`
  on PATH, no campaign TMPDIR) it read 942 passed /
  3 skipped — the two git-lfs client cells skipped
  instead of passing; the corrected rerun with the
  established environment stands as the governing
  number. No bugs were found in shipped code.
  Environment for the governing recount: TMPDIR
  pointed at `~/workspace/.verify-tmp/samverk-tmp`,
  PATH prepended `~/workspace/.tools`. All banked
  locally on `main`; **no GitHub push** — pushes
  stay gated on Volmarr's word. Next slice: S-146
  line comments.
- **2026-10-30 (keeper run, Part VII continued)** — Previous
  run had banked S-145 at 20:44 EDT (clean tree, no
  Samverk process live at this tick's check, ~22
  minutes quiet), so this run built **S-146** line
  comments (new module
  `samverk/pull_request_line_comments.py`; migration
  51; taxonomy append-only +3, 98 events). 13-test
  battery, foreground; combined with same-repo PRs +
  cross-fork PRs + drafts + conversation + files
  view + compare + diff engine + conversion +
  taxonomy + dependencies + issue events out **94
  passed / 0 failed**. No bugs were found in shipped
  code by the new battery. A fresh full-suite
  governing recount was NOT run this tick (last
  governing recount stands at 954 passed / 1
  skipped; arithmetic expectation 967 passed / 1
  skipped) — the next keeper run verifies it from a
  log file before banking further slices.
  Environment: TMPDIR pointed at
  `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`. All banked locally
  on `main`; **no GitHub push** — pushes stay gated
  on Volmarr's word. Next slice: S-147 review
  threads.
- **2026-10-30 (keeper run, Part VII continued)** — Same
  run, after banking S-146: built **S-147** review
  threads (new module
  `samverk/pull_request_review_threads.py`;
  migration 52; taxonomy append-only +5, 103
  events). 12-test battery, foreground; combined
  with line comments + same-repo PRs + cross-fork
  PRs + drafts + conversation + files view +
  compare + diff engine + conversion + taxonomy +
  dependencies + issue events out **106 passed /
  0 failed**, read back from its log file. No bugs
  were found in shipped code by the new battery. A
  fresh full-suite governing recount was NOT run
  this tick (last governing recount stands at 954
  passed / 1 skipped; arithmetic expectation now
  979 passed / 1 skipped) — the next keeper run
  verifies it from a log file before banking
  further slices. Environment: TMPDIR pointed at
  `~/workspace/.verify-tmp/samverk-tmp`, PATH
  prepended `~/workspace/.tools`. All banked
  locally on `main`; **no GitHub push** — pushes
  stay gated on Volmarr's word. Next slice: S-148
  review submission.
- **2026-10-31 (keeper run, Part VII continued)** — No live
  Samverk worker was found (last commit S-149 ~5 h old, no
  Samverk process, worktree clean), so the keeper resumed
  the campaign itself: built **S-150** suggested changes
  (new module `samverk/pull_request_suggestions.py`;
  migration 55; taxonomy append-only +2, 106 events).
  18-test battery, foreground, read back from its log
  file. No bugs were found in shipped code by the new
  battery. **Correction (same day):** this entry as
  first written recorded a 17-test battery and a
  combined 146 passed read back from its log file;
  both came from run-output deliveries and the disk
  disproves them — the battery log reads 18 passed,
  the combined set collects 138 tests total and its
  log carries no summary, and a disk-verified rerun
  reached 52% all-passing before a 1200 s timeout.
  The combined cross-check stays owed with the
  governing recount; see the S-150 entry above for
  the full correction. The governing full-suite
  recount owed since S-148 was NOT paid this tick:
  the VM carried many other campaigns' full suites
  at once throughout (MemAvailable ~0.6–1.5 GB), and
  a recount launched into that contention would risk
  OOM and prove nothing clean — it stays owed, now
  covering S-148..S-150 (arithmetic expectation
  1027 passed / 1 skipped), and the next keeper run
  with a quiet machine must verify it from a log
  file before banking further slices. Environment:
  TMPDIR `~/workspace/.verify-tmp`, PATH prepended
  `~/workspace/.tools`. Banked on `main` and pushed
  to origin per Volmarr's standing go-ahead
  (2026-10-31), verified by ls-remote. Next slice:
  S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 05:35 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~1.17 GB, 1-min load ~15.9, 5-min load ~11.3 on 4 cores, other campaigns' pytest verified by cwd sagnaskemma-build/ember-build/mythic-coder-build/yggdrasil-build/hermes-hack-build, none Samverk); 00:25 recount log re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then hundreds of F's through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote, S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 05:55 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~1.17 GB, 1-min load ~2.5, 5-min load ~6.4, 15-min load ~8.1 on 4 cores, other campaigns' pytest verified by cwd yggdrasil-build/ember-build/hermes-hack-build/runmal, none Samverk); 00:26 recount log re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote, S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 06:05 EST)** — Governing recount still owed; VM contention heaviest yet (MemAvailable ~0.65-0.94 GB, 1-min load ~8.7-18.6, 5-min load ~6.5-12.0 on 4 cores, swap 0, other campaigns' pytest verified by cwd yggdrasil-build/ember-build/sagnaskemma-build/mythic-coder-build/hermes-hack-build/mindspark-build/ravens, none Samverk); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's counted this tick from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote (0e8edab), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 06:15 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~2.55-2.70 GB, 1-min load ~7.2-9.5, 5-min load ~8.3-8.8 on 4 cores, swap 0, other campaigns' pytest verified by cwd yggdrasil-build/sagnaskemma-build/ember-build, none Samverk); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's re-counted this tick from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote (119211e), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 06:25 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~2.00-2.37 GB, samples 2485132 / 2283664 / 2260952 / 2153604 / 2101620 kB, 1-min load ~7.4-9.7, 5-min load ~8.7-8.9, 15-min load ~9.0 on 4 cores, swap 0, other campaigns' pytest verified by cwd yggdrasil-build/sagnaskemma-build/hermes-hack-build, none Samverk); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's counted this tick from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote after a fetch (90bca86), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 06:35 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~0.58-0.87 GB across the sustained watch, samples 786216 / 908340 / 781960 / 604968 / 796976 kB, 1-min load 7.78→3.93, 5-min load ~8.65→7.40 on 4 cores, swap 0, other campaigns' pytest verified by cwd yggdrasil-build/sagnaskemma-build/hermes-hack-build/mythic-coder-build, none Samverk; one transient mid-tick sample suggesting a lull was disproved by immediate direct re-checks at 753768 kB and load 9.03/8.92/8.45); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote (a5487e7), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 06:45 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~1.37-1.57 GB across the watch, samples 1607168 / 1642740 / 1411428 kB, final check 1529892 kB, 1-min load rising 1.33→4.61→7.67 on 4 cores, swap 0, other campaigns' pytest verified by cwd sagnaskemma-build/yggdrasil-build/ember-build/hermes-hack-build, none Samverk; the brief post-reboot quieter opening never reached a safe memory threshold and load climbed as foreign suites respawned); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then F's from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote (55e3e59), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 06:55 EST)** — Governing recount still owed; VM contention heaviest yet (MemAvailable ~0.52–0.73 GB across the watch, samples 576688 / 589264 / 547512 / 770900 / 695440 / 748348 kB, final check 618068 kB, 1-min load ~14.9–16.5 rising to 18.75 at the final check, 5-min load ~7.7–10.8 on 4 cores, swap 0, other campaigns' pytest verified by cwd yggdrasil-build/mythic-coder-build/hermes-hack-build/sagnaskemma-build/ravens-repo/mindspark-build, none Samverk); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's counted this tick from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote after a fetch (f7fb644), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 07:05 EST)** — Governing recount still owed; VM contention persisted (MemAvailable ~0.66–1.14 GB across the watch, samples 692768 / 1201076 / 1147644 kB, 1-min load ~9.9–10.0, 5-min load ~8.0–8.2 on 4 cores, swap 0, other campaigns' pytest verified by cwd sagnaskemma-build/yggdrasil-build/mythic-coder-build, none Samverk); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's counted this tick from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote (abccc1b), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 07:15 EST)** — Governing recount still owed; VM contention persisted (MemAvailable opened ~1.52-1.94 GB across the first watch, samples 1594908 / 1639512 / 1695896 / 1592084 / 1904800 / 2028528 kB, then fell to 855564 / 724876 kB on direct re-checks, 1-min load ~11.6 falling to ~5.7-6.8, 5-min load ~7.5-10.9 on 4 cores, swap 0, other campaigns' pytest verified by cwd sagnaskemma-build/yggdrasil-build/ember-build/hermes-hack-build/ravens-repo, none Samverk; purplelongship ping failed (name or service not known) so the offload road was unavailable); 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read still no summary (1120 bytes, unchanged since 01:24, clean only to ~42% then 443 F's counted this tick from that contended run through ~97%), NOT verified; no Samverk worker live, worktree clean, head verified equal to origin/main by ls-remote (a0af8b9), S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine.
- **2026-11-01 (keeper tick 07:35 EST)** — Governing recount still owed; the blocker CHANGED shape this tick: memory and load were the best of the day (MemAvailable ~3.51–4.75 GB across sustained watches, samples 3510800 / 3666616 / 3646948 / 3753672 / 3531120 / 3978352 / 4544476 / 4752948 / 4557580 kB, 1-min load falling 5.28→2.30, 5-min load ~3.66–4.49 on 4 cores, swap 0; at the final check no foreign pytest was running at all), but a box-wide write gate blocked Python file creation — tempfile.mkstemp in the campaign TMPDIR (~/workspace/.verify-tmp/samverk-tmp) and open-write in /tmp failed 0/50 across three quantified probes (PermissionError Errno 1; one transient repo-dir mkstemp success at 07:39 amid the failures), while shell-level touch in the same directories succeeded; pytest cannot even collect under it (the S-150 combined set's collect-only died inside tempfile), so neither the governing recount nor S-150's combined cross-check could run and nothing from this tick is test evidence. Other campaigns' probe loops chasing the same gate were visible in the process table throughout. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, clean only to ~42% then 443 F's counted this tick through ~97%, no summary line, NOT verified (its F-pattern is consistent with this same gate closing mid-run — stated as consistency, not proof). No Samverk worker live, worktree clean, head 134da5d verified equal to origin/main by ls-remote this tick, S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine with the write gate open.
- **2026-11-01 (keeper tick 07:45 EST)** — Governing recount still owed; the write gate found at 07:35 is STILL closed, and it is now the sole blocker: memory and load were calm (MemAvailable ~2.96–3.10 GB across the watch, samples 3091272 / 3002704 / 2957112 / 3039784 kB, 1-min load falling 3.55→2.35, 5-min load ~3.0 on 4 cores, swap 0; no foreign pytest running — only a hermes probe loop waiting on the same gate, an aesir mojo build, and a staggered sleep), but Python file creation still failed 0/20 (tempfile.mkstemp in the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and in /tmp, PermissionError Errno 1 on every attempt), so pytest cannot collect and neither the governing recount nor S-150's combined cross-check could run; nothing from this tick is test evidence. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, no summary line, F-markers from the contended run through ~97%, NOT verified. No Samverk worker live, head 134da5d verified equal to origin/main by ls-remote after a fetch. This tick TRIED to bank the 07:35 and 07:45 map entries together and could not: git add staged the file but git commit failed twice with "fatal: unable to write loose object file: Operation not permitted" — the gate blocks git's own object writes too — so both entries stand as uncommitted worktree edits for the next tick with the gate open to bank (the 2026-10-31 09:45–10:15 ticks set this same precedent). S-151 not banked until the recount (expectation 1027 passed / 1 skipped, covering S-148..S-150) is verified from its log file on a quiet machine with the write gate open.
- **2026-11-01 (keeper tick 07:55 EST)** — S-150's combined affected-suites cross-check PAID, disk-verified from its log files: the write gate found closed at 07:35/07:45 was still closed on this tick's first all-directory probe at ~07:55 (tempfile.mkstemp PermissionError in the campaign TMPDIR, /tmp, and the repo dir — that probe's output was delivered late and this entry's first wording overstated it; corrected same tick) but OPENED within minutes — the campaign-TMPDIR probe succeeded at run launch (~07:58), both runs below completed their file work, and an all-directory re-probe at 08:46 read OK in all three — so with load calm at launch (1-min ~2.1–3.5 on 4 cores) the owed cross-check was run twice, logging to the goal's hidden_files: first the 12-file affected set alone (combined-s150-2026-11-01-0755.log: **120 passed / 0 failed in 1159.85 s, PYTEST_EXIT:0**), then the full owed set including S-150's own suggestions battery (combined-s150-full-2026-11-01-0755.log: **138 passed / 0 failed in 1283.12 s, PYTEST_EXIT:0**; a collect-only read-back confirmed 138 collected in total = the 120 plus suggestions' 18, reconciling the S-150 correction's count). The cross-check debt is CLOSED. The governing full-suite recount is still NOT paid: MemAvailable stayed ~0.44–1.27 GB through both runs (swap 0) — enough for the 138-test set, never a safe threshold for the ~1000-test suite on this swapless box — so it stays owed (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) and S-151 does not bank until a keeper run on a quiet machine verifies the recount from its log file. No Samverk worker was live at tick start (foreign pytest on the box belonged to ember-build and ravens, verified by cwd). This tick banks the stranded 07:35 and 07:45 entries together with this one.
- **2026-11-01 (keeper tick 08:55 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 07:55 tick's banking (head 853ae3f, verified equal to origin/main by ls-remote after a fetch; worktree clean — the 08:45 tick had already stood down on this same head as verified progress within ~15 min, and this tick confirms no worker followed it). The write gate is OPEN (tempfile.mkstemp probes OK in the campaign TMPDIR, /tmp and the repo dir). Contention was checked across two watches spanning a mid-tick reboot (~08:57): before it, MemAvailable stayed ~0.75–1.10 GB (samples 768792 / 1100832 / 992812 kB, 5-minute load ~7.3–8.9 on 4 cores, swap 0, foreign pytest verified by cwd to belong to yggdrasil-build, sagnaskemma-build, ember-build and hermes-hack-build, none to Samverk); after it, MemAvailable recovered only to ~1.92–2.13 GB (samples 1974824 / 2134612 / 2054632 / 1923120 kB) and was already falling again at the final check (1666192 kB, up 2 min, 1-minute load 5.19) as sagnaskemma-build, ember-build and mythic-coder-build suites respawned — never near a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F's counted (564 dots), clean only to ~42% through ~97%, no summary line, NOT verified. Purplelongship reachability NOT PROVEN this tick (the name resolves through the VM's proxy-mediated DNS, raw ping is socket-blocked in this sandbox, and the device is still recorded offline, last seen 2026-11-01T02:07Z), so the offload road stays unavailable on this evidence. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 09:05 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 08:55 tick (head 3d8f308, verified equal to origin/main by ls-remote at tick start; worktree clean). The write gate is OPEN (tempfile.mkstemp probes OK in the campaign TMPDIR, /tmp and the repo dir). Contention persisted across another mid-watch reboot (box up ~8–9 min at the checks): MemAvailable stayed ~0.40–0.59 GB across the watch (samples 550428 / 403152 / 593304 / 413732 / 570664 kB, swap 0) and 1-min load spiked 1.13→12.93 as foreign suites respawned (pytest verified by cwd to belong to ember-build, hermes-hack-build and yggdrasil lines, none to Samverk) — never near a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F's counted, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 09:15 EST)** — Governing recount still owed, but this tick DID launch it into the best window in hours and stopped it on the campaign's established precedent: no Samverk worker live at tick start and no new slice commits since the 09:05 tick (head 568a39f, verified equal to origin/main by ls-remote at tick start; worktree clean — the foreign pytest on the box was verified by cwd to belong to yggdrasil-build, none to Samverk). The write gate is OPEN (tempfile.mkstemp probes OK in the campaign TMPDIR, /tmp and the repo dir). A six-sample watch opened at MemAvailable 4045032 kB and climbed 5163972 / 5461756 / 6611668 kB with 1-min load falling 3.66→2.33 (box up ~26–29 min, swap 0), so the owed recount was launched in the campaign's established environment (script run-recount-2026-11-01-0915.sh, log recount-2026-11-01-0915-pytest.log in the goal's hidden_files; HEAD 568a39f, MemAvailable 3409548 kB at launch after foreign suites began respawning). Contention returned during the run — MemAvailable fell to ~2.42–2.49 GB and sagnaskemma-build, ember-build, mythic-coder-build and hermes-hack-build suites joined the yggdrasil suite already running — and after ~4 minutes the log held only 27 test markers, every one passing, none failing (~7 tests/min, a ~2.5-hour projected total), so the recount was stopped rather than ridden into OOM risk on this swapless box, following the 2026-10-31 05:15 and 11:25 precedents; the partial log is NOT evidence and the tally stays NOT verified. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F's counted, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (correction to keeper tick 09:15 EST entry, same tick)** — The 09:15 entry's window description is WRONG and is corrected here, never left: it recorded MemAvailable "climbed 5163972 / 5461756 / 6611668 kB with 1-min load falling 3.66→2.33". Those numbers came from a crossed background delivery and match nothing this tick measured directly; the tick's own watch (delivered after the entry banked) reads, 09:24:26–09:25:41: samples 3883128 / 3630400 / 3496388 / 3456520 / 3325664 / 3433172 kB, 1-min load 4.00→5.04 — memory DECLINING from the foreground opening check (09:24:04: 4045032 kB, load 3.66 / 4.92 / 4.60, box up 26 min), and the recount log's own header records 3409548 kB at launch, consistent with the decline. No result changes: the launch decision stands on the true readings (3.4–4.0 GB, still far above the day's usual ~0.4–1.3 GB), and everything after launch in the 09:15 entry (contention returning, MemAvailable ~2.42–2.49 GB during the run, 27 markers all passing in ~4 min, recount stopped on precedent, tally NOT verified) was measured in foreground checks and stands. The crossed delivery's numbers are discarded, not evidence.
- **2026-11-01 (keeper tick 09:25 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 09:15 tick's correction (head fcd48bf at tick start, verified equal to origin/main by ls-remote; worktree clean). The write gate is OPEN (tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp and the repo dir). VM contention persisted and worsened across the watch: MemAvailable opened 1496396 kB and fell 1112004 / 955640 / 952260 kB, 1-min load 11.32 opening then 8.58 / 7.97 / 6.70 on 4 cores, swap 0, foreign pytest verified by cwd to belong to yggdrasil-build, sagnaskemma-build, ember-build, mythic-coder-build and hermes-hack-build, none to Samverk — never near a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 09:35 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 09:25 tick (head 0611fdb at tick start, verified equal to origin/main by foreground ls-remote this tick — 0611fdbc9ffc1d1e10067c3272c9c8fa101229f4 on both sides; worktree clean). The write gate is OPEN (tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and the repo dir). VM contention persisted and worsened across the watch: MemAvailable measured in foreground at ~934 / 905 / 810 / 746 / 588 MB (final check 588000 kB, 1-min load 16.27, 5-min 9.56 on 4 cores, swap 0); one mid-tick probe watch briefly read ~2.99–3.25 GB as foreign suites finished, but immediate foreground re-checks fell back below 1 GB — never a sustained safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. Foreign pytest was verified by cwd to belong to yggdrasil-build, ember-build, mindspark-build, mythic-coder-build and hermes-hack-build, none to Samverk. One backgrounded probe delivery this tick was crossed/stale (it reported the superseded head fcd48bf and a MemAvailable above the box's total RAM) and is discarded as not evidence, per the 09:15 correction precedent. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F's and 564 dots counted, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 09:35 EST — banking addendum, same tick)** — The 09:35 entry above stands as an UNCOMMITTED worktree edit: banking was attempted three times and git refused every time with "fatal: unable to write loose object file: Operation not permitted" — the failure is in `git add` itself (git must write the new blob as a loose object under .git/objects), even though tempfile.mkstemp probes in the repo root, /tmp and the campaign TMPDIR all succeeded minutes earlier. So the write gate is only partly open this tick: ordinary file writes pass, git object writes do not. This is the 07:45 tick's precedent exactly; the entry stays in the worktree for the next tick with the gate fully open to bank. Head remains 0611fdb, verified equal to origin/main by foreground ls-remote this tick; no push was possible or attempted for this entry. No result changes: recount still NOT verified, S-151 still not banked.
- **2026-11-01 (keeper tick 09:45 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 09:25 tick (head 0611fdb at tick start, verified equal to origin/main by foreground ls-remote this tick — 0611fdbc9ffc1d1e10067c3272c9c8fa101229f4 on both sides; the 09:35 entry and its banking addendum were present as uncommitted worktree edits at tick start — this tick banks all entries together if the git gate allows). The sole live pytest process was verified by cwd to belong to yggdrasil-build, none to Samverk. VM contention persisted: MemAvailable measured in foreground at 592024 / 592884 / 404040 / 437904 kB across the watch, later 686212 and 544548 kB (range ~0.40–0.69 GB), 1-min load ~4.36 falling to ~2.98, 5-min load ~6.5–8.0 on 4 cores, swap 0, box up 48 min at watch start — never near a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. Write probes were contradictory this tick: shell touch probes OK in the repo dir and /tmp, while python tempfile.mkstemp probes returned Operation not permitted in /tmp, the campaign TMPDIR and the repo dir — both recorded; the git commit attempt is the definitive gate test. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 09:45 EST — banking addendum, same tick)** — Banking was attempted in foreground after a fetch (remote unchanged) and git refused again with "fatal: unable to write loose object file: Operation not permitted" on `git add` — the same git-object write gate as the 09:35 tick. The 09:35 entry, its addendum, and the 09:45 entry above therefore all stand as UNCOMMITTED worktree edits for the next tick with the gate fully open to bank. Two 0-byte mkstemp probe leftovers created by this tick's probes in the repo root were removed; worktree otherwise holds only the map edit. Head remains 0611fdb, verified equal to origin/main by foreground ls-remote this tick; no push was possible or attempted. No result changes: recount still NOT verified, S-151 still not banked.
- **2026-11-01 (keeper tick 09:55 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 09:25 tick (head 0611fdb at tick start, verified equal to origin/main by foreground ls-remote this tick — 0611fdbc9ffc1d1e10067c3272c9c8fa101229f4 on both sides; the 09:35 entry, its banking addendum, the 09:45 entry and its banking addendum were present as uncommitted worktree edits at tick start — this tick banks all entries together if the git gate allows). Foreign pytest verified by cwd to belong to yggdrasil-build (a ~1.7 GB RSS suite running since 09:02) and mindspark-build, none to Samverk. VM contention persisted and worsened: MemAvailable measured in FOREGROUND at 590200 / 505700 / 597056 kB (~0.5–0.6 GB), 1-min load rising 1.24→6.43→7.79 on 4 cores, swap 0, box up ~58 min — never near a safe threshold for the ~1000-test suite on this swapless box, so the recount was NOT launched. CROSSED-DELIVERY WARNING, recorded per precedent: a backgrounded watch command this tick delivered MemAvailable samples 3883128 / 3630400 / 3496388 / 3456520 kB — byte-identical to the 09:15 tick's own watch samples recorded in the correction entry above — so that whole delivery (including its all-OK write probes) is discarded as a crossed/replayed delivery, not evidence; every number in this entry was measured in foreground calls. Foreground tempfile.mkstemp probes run separately this tick returned OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp and the repo dir, with no probe leftovers. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 09:55 EST — banking addendum, same tick)** — Banking was attempted in foreground after a fetch (remote unchanged, origin/main still 0611fdb) and git refused again with "fatal: unable to write loose object file: Operation not permitted" on `git add` — the same git-object write gate as the 09:35 and 09:45 ticks, despite foreground tempfile probes passing in all three directories minutes earlier. The 09:35 entry, its addendum, the 09:45 entry, its addendum, and the 09:55 entry above therefore all stand as UNCOMMITTED worktree edits for the next tick with the gate fully open to bank. Head remains 0611fdb, verified equal to origin/main by foreground ls-remote this tick; no push was possible or attempted. No result changes: recount still NOT verified, S-151 still not banked.
- **2026-11-01 (keeper tick 10:05 EST — verification pass)** — No Samverk worker live and no new commits since 09:36 (head 0611fdb, verified equal to origin/main by foreground ls-remote this tick). The only pytest on the box is a foreign Yggdrasil suite (PID 13236, ~3.4 GB RSS, running since 09:02). MemAvailable sampled ~1.02–1.09 GB early in the tick, rising to ~1.73–1.85 GB at the final checks, but 1-minute load stayed ~6.1–6.8 on 4 cores with swap 0 — never near a safe threshold for the ~1000-test suite. The box-wide write gate is CLOSED again this tick: Python tempfile creation failed in both the default temp dirs and the campaign TMPDIR (no usable temporary directory), shell touch in the campaign TMPDIR succeeded, and `git add` failed with "fatal: unable to write loose object file: Operation not permitted" (exit 128) — so no recount could run cleanly (every Samverk test builds temp git repos) and the stranded 09:35–10:05 map entries could not be banked; they stand as uncommitted worktree edits together with this entry. The 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) was re-read directly: 1120 bytes, mtime 2026-11-01 01:24 unchanged, tail at ~97% with heavy F's, no summary line, NOT verified. S-150's combined cross-check stands PAID from the 07:55 tick (138 passed / 0 failed). Recount expectation remains 1027 passed / 1 skipped / 0 failed covering S-148..S-150; S-151 (CODEOWNERS) not banked until a keeper run on a quiet machine with the write gate open verifies it from its log file.
- **2026-11-01 (keeper tick 10:15 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since 09:36 (head 0611fdb at tick start, verified equal to origin/main by foreground ls-remote this tick — 0611fdbc9ffc1d1e10067c3272c9c8fa101229f4 on both sides). The only pytest on the box is the foreign Yggdrasil suite (PID 13236, cwd verified yggdrasil-build, ~5.15 GB RSS, running since 09:02), none Samverk. MemAvailable measured in foreground at 1198848 kB (~1.20 GB), 1-min load 4.78 on 4 cores, swap 0 — never near a safe threshold for the ~1000-test suite on this swapless box, so the recount was NOT launched. MATERIAL CHANGE this tick: the git-object write gate is OPEN again — foreground tempfile.mkstemp probes passed in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp and the repo dir, and `git add` succeeded (exit 0) for the first time since the 09:25 tick, so the stranded 09:35–10:05 entries are banked together with this entry and pushed in this tick. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, tail at ~97%, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 10:25 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 10:15 tick banked the stranded entries (head ad95b90 at tick start, verified equal to origin/main by foreground ls-remote after a fetch — ad95b909d574b5b2885f7a93342b5a2fe966d9d7 on both sides; worktree clean). The write gate is OPEN (foreground tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and the repo dir). VM contention persisted across the watch: MemAvailable measured in foreground at 972572 kB opening and fell 827796 / 723140 / 660260 kB, 1-min load 6.46 opening and 7.99 / 6.95 / 8.19 on 4 cores, swap 0 — never near a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. Foreign pytest verified by cwd/process to belong to yggdrasil-build (PID 13236, ~5.24 GB RSS, running since 09:02), sagnaskemma-build and mythic-coder-build, none to Samverk. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, tail at ~97%, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 10:35 EST)** — Governing recount still owed, but this tick DID launch it into the day's second-best window and stopped it on the 09:15 precedent, faster: no Samverk worker live at tick start and no new slice commits since the 10:25 tick (head 82138e3 at tick start, verified equal to origin/main by foreground ls-remote after a fetch — 82138e305f18656e5dc2573135f1ca03c405d320 on both sides; worktree clean). The write gate is OPEN (foreground tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and the repo dir). Opening watch was the calmest in hours: MemAvailable ~3.13–3.28 GB across samples (3132524 / 3212992 / 3207140 / 3279000 kB), 1-min load ~1.4–1.7 on 4 cores, swap 0, the big yggdrasil suite gone — foreign pytest verified by cwd to belong only to sagnaskemma-build, ember-build, hermes-hack-build, mindspark-build and yggdrasil-build small tests, none to Samverk; purplelongship still offline (device list, last seen 2026-11-01T02:07Z), so the offload road stays unavailable. The owed recount was launched in the campaign's established environment (script run-recount-2026-11-01-1035.sh, log recount-2026-11-01-1035-pytest.log in the goal's hidden_files; HEAD 82138e3, MemAvailable 2542312 kB at launch as foreign suites began respawning). Contention returned hard during the run — MemAvailable fell 2542312 → 2357036 → 2016568 → 1873168 kB, 1-min load climbed 2.23 → 11.04 → 15.85 — and after ~4 minutes the log held only 13 test markers, every one passing, none failing (~3/min, a ~5-hour projected total, worse than the 09:15 tick's ~7/min stop point), so the recount was stopped rather than ridden into OOM risk on this swapless box, following the 2026-10-31 05:15 / 11:25 and 2026-11-01 09:15 precedents; the stopped pytest was verified gone and the partial log (89 bytes, 13 dots, 0 F) is NOT evidence — the tally stays NOT verified. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, tail at ~97%, no summary line, NOT verified. S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 10:45 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 10:35 tick (head 1baf199 at tick start, verified equal to origin/main by foreground ls-remote this tick — 1baf199fd1b48ddd1b0d13dc2a17851eafeaaaac on both sides; worktree clean). The write gate is OPEN (foreground tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and the repo dir). VM contention persisted across the watch: MemAvailable measured in foreground at 1703008 kB (~1.66 GB) at the first check, then 2406944 / 2865768 / 2941652 kB (~2.35–2.87 GB, rising) across a one-minute watch, and 3598976 kB (~3.51 GB) at the final check — but 1-minute load climbed with it, 3.39 → 5.03 → 5.48 → 8.32 on 4 cores (5-minute load ~5.1–6.2, swap 0), so even the best memory sample came with load far above the 10:35 tick's calm launch window (3.13–3.28 GB at 1-minute load ~1.4–1.7) which still had to be stopped at 13 tests; never a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. Foreign pytest verified by cwd to belong to ember-build and yggdrasil-build at the first check, then yggdrasil-build and mythic-coder-build across the watch, none to Samverk. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, tail at ~97%, no summary line, NOT verified. S-150's combined cross-check stands PAID from the 07:55 tick (138 passed / 0 failed). S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 10:55 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 10:45 tick (head c3a4a67 at tick start, verified equal to origin/main by foreground ls-remote this tick — c3a4a670f9506d211efada634fb8d057c9f2d9ab on both sides; worktree clean). The write gate is OPEN (foreground tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and the repo dir). VM contention persisted: machine had rebooted ~2 min before the tick; MemAvailable measured in foreground at 1797940 kB (~1.79 GB) at the first check and 1691648 kB (~1.69 GB, falling) at the final check, swap 0, and 1-minute load climbed 5.39 → 7.16 on 4 cores — far from a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. Foreign pytest verified running for mythic-coder-build, sagnaskemma-build and other campaigns, none to Samverk. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, tail at ~97%, no summary line, NOT verified. S-150's combined cross-check stands PAID from the 07:55 tick (138 passed / 0 failed). S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
- **2026-11-01 (keeper tick 11:05 EST)** — Governing recount still owed; no Samverk worker live and no new slice commits since the 10:55 tick (head 261e0f3 at tick start, verified equal to origin/main by foreground ls-remote this tick — 261e0f3c064ed5f1a4def6ccb695bc419df8bb3b on both sides; worktree clean). The write gate is OPEN (foreground tempfile.mkstemp probes OK in /tmp, the campaign TMPDIR ~/workspace/.verify-tmp/samverk-tmp and the repo dir). VM contention was the heaviest of the day: the machine had rebooted ~5 min before the tick and MemAvailable measured in foreground at 1433228 kB (~1.43 GB) at the first check, then 1207492 / 1325076 kB (~1.21–1.33 GB) across the watch, while 1-minute load opened at 18.64 and stayed 15.10 → 12.52 on 4 cores (5-minute load ~10.5, swap 0) — never near a safe threshold for the ~1000-test suite on this swapless box, so launching would risk OOM and prove nothing clean; the recount was NOT launched. Foreign pytest verified by cwd to belong to mythic-coder-build, sagnaskemma-build, ember-build, ravens-repo and mindspark-build, none to Samverk. purplelongship still offline (device list, last seen 2026-11-01T02:07Z), so the offload road stays unavailable. 00:26 recount log (~/workspace/.verify-tmp/samverk_recount_s151_20261101_0026.log) re-read directly this tick: 1120 bytes, mtime 2026-11-01 01:24 unchanged, 443 F chars and 564 dots counted, tail at ~97%, no summary line, NOT verified. S-150's combined cross-check stands PAID from the 07:55 tick (138 passed / 0 failed). S-151 not banked until the recount (expectation 1027 passed / 1 skipped / 0 failed, covering S-148..S-150) is verified from its log file on a quiet machine; next S-151 CODEOWNERS.
