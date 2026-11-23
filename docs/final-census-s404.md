# Final census -- S-404

The final census to Volmarr, judged at 401/416
against the tree as it stands (S-402, the founder
walk, still open in roadmap order; S-403 built but
unbanked behind it; this slice banks after both).
The full census ships at `docs/FINAL_CENSUS.md`;
this is its counted log.

Census rows judged: 43

Slice accounting: banked 401 + founder 1 + built 1 + this slice 1 + not yet done 12 = 416 of 416

- banked: 1
- founder_pending: 1
- built_unbanked: 1
- this_slice: 1
- not_yet_done: 12
- not_green: 3
- proven: 2
- not_proven: 6
- open: 4
- historical: 1
- refused: 5
- deferred: 6

| ID | Status | Source |
|---|---|---|
| slices-banked-401 | banked | WAVE_PLAN.md / git ls-remote (origin/main 080cf8e) |
| s402-founder-walk | founder_pending | S-402 |
| s403-successor-seed | built_unbanked | S-403 (team-02 ad97af2 on base 080cf8e) |
| s404-final-census | this_slice | S-404 (this slice, team-03) |
| s405-support-matrix | not_yet_done | S-405 (Part XXII) |
| s406-platform-seam | not_yet_done | S-406 (Part XXII) |
| s407-dependency-register | not_yet_done | S-407 (Part XXII) |
| s408-filesystem-law | not_yet_done | S-408 (Part XXII) |
| s409-path-encoding | not_yet_done | S-409 (Part XXII) |
| s410-windows-service | not_yet_done | S-410 (Part XXII) |
| s411-macos-service | not_yet_done | S-411 (Part XXII) |
| s412-linux-parity | not_yet_done | S-412 (Part XXII) |
| s413-cpu-honesty | not_yet_done | S-413 (Part XXII) |
| s414-browser-reach | not_yet_done | S-414 (Part XXII) |
| s415-battery-arm | not_yet_done | S-415 (Part XXII) |
| s416-battery-ports-gate | not_yet_done | S-416 (Part XXII) |
| wave380-counted-run | not_green | WAVE_PLAN.md (sharded runner, shards-wave380) |
| s393-counted-master-run | not_green | S-393 / docs/COUNTED_MASTER_RUN.md |
| wave400-counted-run | not_green | WAVE_PLAN.md keeper note 2026-11-22 18:32 EST / hidden_files/shards-wave400-launch.log |
| v1-tag-placement | not_proven | S-401 / samverk/v1_tag.py |
| claims-proven | proven | S-399 / docs/claims-register-final-s399.md |
| claims-proven-scoped | proven | S-399 / docs/claims-register-final-s399.md |
| claims-f02-platform-matrix | not_proven | S-399 (claim F-02) |
| claims-f10-live-composition | not_proven | S-399 (claim F-10) |
| claims-f11-full-suite-green | not_proven | S-399 (claim F-11) / counted runs |
| claims-f01-real-sshd-cell | not_proven | S-399 (claim F-01) |
| claims-f17-readme-wordings | open | S-399 (claim F-17) |
| claims-historical | historical | S-399 / docs/claims-register-final-s399.md |
| release-signing-s400 | not_proven | S-400 / WAVE_PLAN.md coordinator note 2026-11-22 17:45 EST |
| refused-oci | refused | S-264 / S-403 seed |
| refused-docker | refused | roadmap standing exclusions (founding) / S-264 |
| refused-federation | refused | roadmap standing exclusions (founding) |
| refused-hosted-service | refused | roadmap standing exclusions (founding) |
| refused-invented-facts | refused | roadmap standing exclusions (founding) |
| deferred-graphql | deferred | S-253 / S-403 seed |
| deferred-package-python | deferred | S-264 / S-403 seed |
| deferred-package-javascript | deferred | S-264 / S-403 seed |
| deferred-discussion-polls | deferred | S-282 / S-286 / S-403 seed |
| deferred-discussion-badges | deferred | S-282 / S-403 seed |
| deferred-signing-verifier | deferred | S-263 / S-305 / S-403 seed |
| open-study-24 | open | S-398 (research corpus audit) |
| open-study-26 | open | S-398 (research corpus audit) |
| open-study-30 | open | S-398 (research corpus audit) |

Counted runs: wave380 Ran 6029 fails 15; S-393 Ran 6129 fails 15; wave400 Ran 6190 fails 12 -- all stale-pin class, none green.
v1.0 tag: NOT PLACED. S-400 signing: NOT PROVEN.

Verdict: **COUNTED**
