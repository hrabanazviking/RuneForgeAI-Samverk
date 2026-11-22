# Final census to Volmarr (S-404)

In plain words: this is the counted close of
the first roadmap's census point. Of 416 slices,
401 stand banked. One slice is Volmarr's alone
to walk (S-402) and stands NOT DONE. One stands
built but unbanked behind it (S-403). This census
is S-404. Twelve slices (S-405..S-416, Part XXII)
stand not yet done, and every cell they promise
stands NOT PROVEN until its battery runs there.
The v1.0 tag is NOT PLACED: the wave400 counted
run reads Ran 6190 with 12 failures, all in the
known stale-pin class, and a run with failures
is not green however familiar its class. The
S-400 package stands unsigned -- NOT PROVEN as
signed. What was refused stays refused, what was
deferred stays deferred. The roadmap closes;
the together-work continues.

The law module is `samverk/final_census.py`;
its battery is `tests/test_final_census.py`;
the runner is `tools/run_final_census.py`;
the counted log ships at
`docs/final-census-s404.md`.

## Roadmap accounting (416 slices, counted whole)

- Banked: 401
- Founder pending (S-402): 1
- Built, not banked (S-403): 1
- This slice (S-404): 1
- Not yet done (S-405..S-416): 12
- Total: 416 of 416

## Census rows

- Census rows: 43
- NOT PROVEN rows: 6
- Refused rows: 5
- Deferred rows: 6
- Not-green counted runs: 3
- Schema 140, taxonomy 142 stand (no migration,
  no new taxonomy event in this slice)

## The census

### slices-banked-401 -- Slices S-001..S-401 banked

- Status: BANKED
- Source: WAVE_PLAN.md / git ls-remote (origin/main 080cf8e)
- Note: Banked strictly in roadmap order, one slice per commit, ls-remote verified. Last banked: S-401 at 2026-11-22 18:15 EST.

### s402-founder-walk -- S-402 Volmarr's usability walk

- Status: FOUNDER PENDING -- NOT DONE
- Source: S-402
- Note: NOT DONE. Founder-only by the roadmap's own text: Volmarr, unaided, on a fresh instance -- account, token, repo, push, mirror. No worker can build it and this census claims nothing about its outcome. Banking head: S-403 banks only after this slice.

### s403-successor-seed -- S-403 Successor roadmap seed

- Status: BUILT, NOT BANKED
- Source: S-403 (team-02 ad97af2 on base 080cf8e)
- Note: BUILT + COMMITTED, NOT banked: commit ad97af2, own battery 13 OK, neighbours 102 OK. Held unmerged in roadmap order; it banks only after S-402 lands.

### s404-final-census -- S-404 Final census to Volmarr

- Status: THIS SLICE
- Source: S-404 (this slice, team-03)
- Note: This census itself: built on banked base 080cf8e, banks only after S-402 and S-403 in roadmap order. Its own battery and neighbours are counted in its counted log; it claims no banking.

### s405-support-matrix -- S-405 Support matrix ratified

- Status: NOT YET DONE
- Source: S-405 (Part XXII)
- Note: NOT YET DONE. The support promise (Linux, Windows, macOS; x86-64 and ARM64, Pi 5 floor) is not yet written down as the ratified matrix; every cell stands NOT PROVEN until its battery runs in that cell.

### s406-platform-seam -- S-406 Platform seam audit

- Status: NOT YET DONE
- Source: S-406 (Part XXII)
- Note: NOT YET DONE. No seam audit has run; stray platform calls outside one platform module are uncounted.

### s407-dependency-register -- S-407 Dependency replaceability register

- Status: NOT YET DONE
- Source: S-407 (Part XXII)
- Note: NOT YET DONE. No replaceability register exists yet for the git binaries, SQLite, or the admitted cryptography dependency.

### s408-filesystem-law -- S-408 Filesystem law

- Status: NOT YET DONE
- Source: S-408 (Part XXII)
- Note: NOT YET DONE. Case-sensitive vs case-insensitive storage correctness, including the two-names-differing-only-by-case collision, is untested as this slice's battery.

### s409-path-encoding -- S-409 Path and encoding discipline

- Status: NOT YET DONE
- Source: S-409 (Part XXII)
- Note: NOT YET DONE. One canonical stored form for refs, paths and config is not yet proven as this slice's battery.

### s410-windows-service -- S-410 Windows service

- Status: NOT YET DONE
- Source: S-410 (Part XXII)
- Note: NOT YET DONE. Samverk as a native Windows service (no Docker, no WSL requirement) is NOT PROVEN.

### s411-macos-service -- S-411 macOS service

- Status: NOT YET DONE
- Source: S-411 (Part XXII)
- Note: NOT YET DONE. Samverk under launchd is NOT PROVEN.

### s412-linux-parity -- S-412 Linux services parity

- Status: NOT YET DONE
- Source: S-412 (Part XXII)
- Note: NOT YET DONE. The systemd units are not yet re-verified as one of three equal service citizens in this part.

### s413-cpu-honesty -- S-413 CPU honesty

- Status: NOT YET DONE
- Source: S-413 (Part XXII)
- Note: NOT YET DONE. Performance budgets are not yet restated per hardware class; a budget proven on one class claims nothing about another.

### s414-browser-reach -- S-414 Browser and device reach

- Status: NOT YET DONE
- Source: S-414 (Part XXII)
- Note: NOT YET DONE. The web UI is not yet verified across Chrome, Firefox, Safari, Edge and phone/tablet browsers as this slice's matrix.

### s415-battery-arm -- S-415 Battery port: Linux on ARM

- Status: NOT YET DONE
- Source: S-415 (Part XXII)
- Note: NOT YET DONE. The full battery has not run green on the Raspberry Pi 5 as this slice's counted run; the Linux x ARM64 cell stands NOT PROVEN.

### s416-battery-ports-gate -- S-416 Battery ports: Windows and macOS + the portability gate

- Status: NOT YET DONE
- Source: S-416 (Part XXII)
- Note: NOT YET DONE. No Windows or macOS battery run exists; the portability gate has not been judged. The founding law is declared kept only for proven cells, and no Part XXII cell is proven yet.

### wave380-counted-run -- Wave 371-380 counted run

- Status: NOT GREEN
- Source: WAVE_PLAN.md (sharded runner, shards-wave380)
- Note: Ran 6029, skipped 4, fails 15. Every failure is the known stale schema/taxonomy-pin class (families actual {auth:34, repo:92, admin:16} vs pinned {auth:33, repo:92, admin:13}; verbs 142 vs 138). No failure outside that class; the run is NOT GREEN.

### s393-counted-master-run -- S-393 counted master run (wave 381-390 counted run)

- Status: NOT GREEN
- Source: S-393 / docs/COUNTED_MASTER_RUN.md
- Note: Ran 6129, Passed 6110, Failed 15, Skipped 4 (all named). Same stale-pin class as wave380. A counted run with 15 failures is NOT GREEN, however familiar the class.

### wave400-counted-run -- Wave 391-400 counted run (wave400)

- Status: NOT GREEN
- Source: WAVE_PLAN.md keeper note 2026-11-22 18:32 EST / hidden_files/shards-wave400-launch.log
- Note: FINISHED: Ran 6190, skipped 4, fails 12, wall 2511.9s, FAILED. All 12 failures classified from the shard logs: every one is the known stale schema/taxonomy-pin class; NO failure outside that class, so no fix-forward work arises. The run is NOT GREEN.

### v1-tag-placement -- S-401 v1.0 tag placement

- Status: NOT PROVEN
- Source: S-401 / samverk/v1_tag.py
- Note: Tag NOT PLACED and NOT PROVEN as placed. S-401's law tags only a counted-GREEN tree; the wave400 counted run over the counted tree 6ede324e is not green (12 stale-pin fails), so the tag stays honestly pending. The road is fix forward, a fresh counted run over the fixed tree, then the tag -- a changed tree is not the counted tree. Never claim green.

### claims-proven -- Claims register: proven claims

- Status: PROVEN
- Source: S-399 / docs/claims-register-final-s399.md
- Note: 8 of 17 final claims stand PROVEN: F-05 native CI, F-06 fresh install, F-07 upgrade drill, F-08 Samtal seam, F-09 v1.0 acceptance battery, F-12 guides walked live, F-13 research corpus, F-15 AGPL-3.0.

### claims-proven-scoped -- Claims register: proven-scoped claims

- Status: PROVEN
- Source: S-399 / docs/claims-register-final-s399.md
- Note: 4 of 17 final claims stand PROVEN within their stated scope only: F-01 git client interop, F-03 design lawbook gate, F-04 mirroring of Volmarr's originals, F-14 native systemd running with no Docker. The scope is part of the claim; nothing wider is proven.

### claims-f02-platform-matrix -- Claim F-02: server on Windows, macOS, ARM to Pi

- Status: NOT PROVEN
- Source: S-399 (claim F-02)
- Note: NOT PROVEN. Owned by Part XXII (S-405..S-416), all not yet done; no matrix cell has a counted battery run.

### claims-f10-live-composition -- Claim F-10: feature services composed into one running forge

- Status: NOT PROVEN
- Source: S-399 (claim F-10)
- Note: NOT PROVEN. The founder walk (S-402) owns part of this proof and is NOT DONE; the composition claim flips only on that live proof.

### claims-f11-full-suite-green -- Claim F-11: the full suite is green

- Status: NOT PROVEN
- Source: S-399 (claim F-11) / counted runs
- Note: NOT PROVEN. The latest counted run (wave400) reads Ran 6190, fails 12 -- not green. No counted run at the close of this census reads zero failures.

### claims-f01-real-sshd-cell -- Claim F-01 scoped remainder: real-sshd cell

- Status: NOT PROVEN
- Source: S-399 (claim F-01)
- Note: NOT PROVEN as a scoped remainder: F-01 stands proven scoped, but its real-sshd cell remains a named NOT PROVEN remainder owned by Part XXII.

### claims-f17-readme-wordings -- Claim F-17: two README wordings

- Status: OPEN
- Source: S-399 (claim F-17)
- Note: OPEN, owned by Volmarr alone: two README wordings only he can settle. This census does not touch any README.md.

### claims-historical -- Claims register: historical rows

- Status: HISTORICAL
- Source: S-399 / docs/claims-register-final-s399.md
- Note: 1 of 17 final rows is historical (F-16): dated position statements, true of their dates, claiming nothing about the present tree.

### release-signing-s400 -- S-400 release package signing

- Status: NOT PROVEN
- Source: S-400 / WAVE_PLAN.md coordinator note 2026-11-22 17:45 EST
- Note: NOT PROVEN. The S-400 package ships unsigned (tarball SHA-256 d49482e6c3c8b4c4dda9e2a13f93078f2bedf780173d23a702e03497eb015693 re-verified at banking): there is no maintainer key on this box and none was fabricated. The S-403 seed carries the signing remainder as open, owned by Volmarr; as a proof that the package is signed, it stands NOT PROVEN.

### refused-oci -- Refused: OCI container packages

- Status: REFUSED
- Source: S-264 / S-403 seed
- Note: REFUSED at the S-264 package verdict and carried refused in the S-403 seed. Revisited only by Volmarr's word.

### refused-docker -- Refused: Docker

- Status: REFUSED
- Source: roadmap standing exclusions (founding) / S-264
- Note: REFUSED as standing law: not for Samverk, not for its runner, not for its docs' examples. Native installs only.

### refused-federation -- Refused: federation between instances

- Status: REFUSED
- Source: roadmap standing exclusions (founding)
- Note: REFUSED at founding: no federation between Samverk instances or Samtal villages.

### refused-hosted-service -- Refused: hosted-service ambitions

- Status: REFUSED
- Source: roadmap standing exclusions (founding)
- Note: REFUSED at founding: Samverk is software its owner runs, not a platform operated for strangers.

### refused-invented-facts -- Refused: AI features that invent facts

- Status: REFUSED
- Source: roadmap standing exclusions (founding)
- Note: REFUSED at founding: no generated summaries presented as truth; anything automated is labelled and checkable.

### deferred-graphql -- Deferred: GraphQL API layer

- Status: DEFERRED
- Source: S-253 / S-403 seed
- Note: DEFERRED at the S-253 verdict, revisited and kept deferred by S-403. No endpoint, schema or resolver exists.

### deferred-package-python -- Deferred: Python package registry

- Status: DEFERRED
- Source: S-264 / S-403 seed
- Note: DEFERRED at the S-264 package verdict; no Python registry is built or claimed.

### deferred-package-javascript -- Deferred: JavaScript package registry

- Status: DEFERRED
- Source: S-264 / S-403 seed
- Note: DEFERRED at the S-264 package verdict; no JavaScript registry is built or claimed.

### deferred-discussion-polls -- Deferred: discussion polls

- Status: DEFERRED
- Source: S-282 / S-286 / S-403 seed
- Note: DEFERRED: discussions core landed (S-283..S-285); polls were deferred and S-286 published the polls position. Not built.

### deferred-discussion-badges -- Deferred: rich discussion badges

- Status: DEFERRED
- Source: S-282 / S-403 seed
- Note: DEFERRED at the S-282 discussions verdict. Not built.

### deferred-signing-verifier -- Deferred: signing verifier

- Status: DEFERRED
- Source: S-263 / S-305 / S-403 seed
- Note: DEFERRED in the S-403 seed (signing seam S-263, verifier road S-305). No verifier is claimed as built.

### open-study-24 -- Open study 24 (GraphQL)

- Status: OPEN
- Source: S-398 (research corpus audit)
- Note: OPEN: study 24 of the 46-file research corpus stands honestly open, owned forward by the successor roadmap (S-403 seed).

### open-study-26 -- Open study 26 (packages)

- Status: OPEN
- Source: S-398 (research corpus audit)
- Note: OPEN: study 26 stands honestly open, owned forward by the successor roadmap (S-403 seed).

### open-study-30 -- Open study 30 (discussions)

- Status: OPEN
- Source: S-398 (research corpus audit)
- Note: OPEN: study 30 stands honestly open, owned forward by the successor roadmap (S-403 seed). The other 43 study files hold completed studies (S-398).

## What this census does not claim

- It does not claim S-402: the founder walk is
  Volmarr's alone and stands NOT DONE.
- It does not claim the v1.0 tag: NOT PLACED,
  because no counted run over the counted tree
  reads green at this census.
- It does not claim a signed release: the S-400
  package is unsigned and signing stands
  NOT PROVEN.
- It does not close Part XXII: S-405..S-416
  stand not yet done and their cells NOT PROVEN.
- The successor roadmap seed (S-403) carries
  the deferred, refused and open remainder
  forward; this census is its counted witness.
