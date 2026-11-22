# Successor roadmap seed (S-403)

In plain words: the first roadmap (416 slices) is
closing. This seed is its honest remainder -- every
item the campaign deferred, refused, left NOT
PROVEN, left open, or reserved for its founder --
written down with its source, its real status, its
owner, and the condition that reopens it, so the
next roadmap starts from the truth and not from a
blank page. Nothing here upgrades a status: what
was deferred is deferred, what was refused is
refused, what stands NOT PROVEN stands NOT PROVEN.

The law module is `samverk/successor_roadmap_seed.py`;
its battery is `tests/test_successor_roadmap_seed.py`;
the runner is `tools/run_successor_roadmap_seed.py`;
the counted log ships at
`docs/successor-roadmap-seed-s403.md`.

## Census

- Seed items: 24
- Deferred: 6
- Refused: 5
- NOT PROVEN: 5
- Open: 5
- Founder-owned: 1
- Served by an existing road: 2
- Schema 140, taxonomy 142 stand (no migration,
  no new taxonomy event in this slice)

## The seed items

### graphql-layer -- GraphQL API layer

- Status: DEFERRED
- Source: S-253
- Owner: successor roadmap
- Reopens when: A second independent consumer with measured relationship-read pain, or the PR-review benchmark in research 24's shape showing REST materially worse; S-255 abuse defences extended to query cost
- Note: Verdict DEFER in docs/GRAPHQL_VERDICT.md; revisited here as S-403 requires. No endpoint, schema or resolver exists; requests are refused graphql_deferred. The eight must-not-break invariants in the verdict carry into any future build.

### package-python -- Package registry: Python packages

- Status: DEFERRED
- Source: S-264
- Owner: successor roadmap
- Reopens when: A village project names a concrete private-package need release assets cannot serve, with its workload as evidence; trust machinery (signing verifier, S-268 storage accounting, quarantine design) standing
- Note: First candidate in research 26's ranking; measured village need today is zero (Samverk is stdlib-first). Answered registry_deferred.

### package-javascript -- Package registry: JavaScript packages

- Status: DEFERRED
- Source: S-264
- Owner: successor roadmap
- Reopens when: A village project becomes a JavaScript package with a private-distribution need release assets cannot serve
- Note: No village JavaScript package exists; the web surface is server-rendered. Answered registry_deferred.

### package-oci -- Package registry: OCI container images

- Status: REFUSED
- Source: S-264
- Owner: Volmarr (standing No Docker law)
- Reopens when: Only Volmarr's word overriding the No Docker law
- Note: Refused outright at S-264: the village runs no Docker, ever; native installs only. Answered registry_refused. S-265 documented the seam instead of a registry core.

### package-generic-archives -- Package registry: generic archives

- Status: SERVED
- Source: S-264
- Owner: S-257/S-259/S-260 (banked)
- Reopens when: Nothing to reopen: served today; a successor item arises only if a need appears that releases cannot meet
- Note: Versioned archives are what releases and assets already host, repo-linked with checksums and the signing seam. Answered registry_served_by_releases. Recorded so the seed accounts for every ecosystem S-264 judged.

### package-go-modules -- Package registry: Go modules

- Status: SERVED
- Source: S-264
- Owner: git tags on readable repositories (banked)
- Reopens when: Nothing to reopen: served today by design of the Go module protocol
- Note: Go modules are fetched from version-control tags; a tag on a readable Samverk repository already is a module version. Answered registry_served_by_git.

### discussion-polls -- Discussion polls

- Status: DEFERRED
- Source: S-282 / S-286
- Owner: successor roadmap
- Reopens when: Measured village need plus a fraud-honest design that does not pretend to establish voter identity beyond account scope
- Note: Deferred at S-282; S-286 published the refusal on that verdict (judged through S-283's doors and S-190 first, then refused; no poll table exists).

### discussion-badges -- Discussion rich badges

- Status: DEFERRED
- Source: S-282
- Owner: successor roadmap
- Reopens when: Measured village need for a signal beyond the accepted-answer mark
- Note: Deferred at S-282 in the same sentence as polls; unbuilt and, unlike polls, never refused by any slice. A village trusts an answer because its author is known.

### signing-verifier -- Signing seam verifier and registry trust machinery

- Status: DEFERRED
- Source: S-263 / S-305 / S-264
- Owner: successor roadmap
- Reopens when: Named as a precondition of any reopened package verdict (S-264 reopen conditions)
- Note: S-263's signing seam has no verifier yet and a digest is not an author identity; S-264 names the verifier as trust machinery that must stand before any registry reopens.

### study-24-graphql -- Open study: research/24-graphql-api-shape.md

- Status: OPEN
- Source: S-398 (study from research 24)
- Owner: successor roadmap
- Reopens when: The revisited GraphQL verdict is recorded in the study file itself, closing the S-398 marking
- Note: S-398: the file poses the defer-or-adopt question but records no verdict; the DEFER verdict stands in docs/GRAPHQL_VERDICT.md (S-253). This seed carries the item; it does not edit the study file's verdict into existence.

### study-26-packages -- Open study: research/26-packages-and-registry.md

- Status: OPEN
- Source: S-398 (study from research 26)
- Owner: successor roadmap
- Reopens when: The package verdicts are recorded in the study file itself, closing the S-398 marking
- Note: S-398: the file poses the registry verdict question but records no verdict; DEFER all / REFUSE OCI stands in docs/PACKAGE_VERDICT.md (S-264).

### study-30-discussions -- Open study: research/30-discussions.md

- Status: OPEN
- Source: S-398 (study from research 30)
- Owner: successor roadmap
- Reopens when: The discussions verdict is recorded in the study file itself, closing the S-398 marking
- Note: S-398: the file poses the verdict question but records no verdict; BUILD (core) stands in docs/DISCUSSIONS_VERDICT.md (S-282), with polls and badges deferred -- the remainder this seed carries above.

### claims-f02-platform-matrix -- Claims F-02: Windows, macOS and ARM platform matrix

- Status: NOT PROVEN
- Source: S-399 (claim C-10)
- Owner: Part XXII (S-405..S-416), then successor roadmap for any cell still unproven
- Reopens when: Each matrix cell flips only when its battery has run green in that cell (Part XXII's own law)
- Note: Linux x86-64 proven; Pi-class budgets measured at S-395; Windows, macOS and the full matrix NOT PROVEN. Part XXII stands after S-403 in this roadmap; the seed inherits whatever it leaves unproven.

### claims-f10-live-composition -- Claims F-10: feature services composed into one running forge

- Status: NOT PROVEN
- Source: S-399
- Owner: S-402 and the successor roadmap
- Reopens when: samverk/server.py routes the composed forge end to end and the proof is counted
- Note: Only /, /healthz and /admin/status are routed today; the many banked feature services are not composed into one served forge. NOT PROVEN at S-399 and still NOT PROVEN here.

### claims-f11-full-suite-green -- Claims F-11: the full suite is green

- Status: NOT PROVEN
- Source: S-399 (counted run S-393)
- Owner: Part XXI pin-refresh work and the final census (S-404)
- Reopens when: A finished counted run over the final tree reads zero failures
- Note: The S-393 counted master run stands 6129 ran / 15 named stale-pin failures / 4 named skips. Later counted runs judge their own trees; no run yet entitles the words 'full suite green'.

### claims-f01-real-sshd-cell -- Claims F-01 remainder: the real-sshd transport cell

- Status: NOT PROVEN
- Source: S-399 (claim C-09)
- Owner: Part XXII (S-405..S-416)
- Reopens when: The transport battery runs against a real sshd in a proven cell, counted green
- Note: C-09 is PROVEN scoped: stock-git smart-HTTP and SSH forced-command harnesses are green; the real-sshd cell is still skipped on the proving host and remains NOT PROVEN. The scoped remainder, named so it is never read as whole.

### claims-f17-readme-wordings -- Claims F-17: two README wordings only Volmarr can settle

- Status: OPEN
- Source: S-399
- Owner: Volmarr
- Reopens when: Volmarr's own word on the founding Status bullet and the 'Samtel' wording
- Note: The founding Status bullet ('46 study areas, each an empty file') is false today -- S-398 counted all 46 populated -- and the first paragraph reads 'Samtel' for Samtal. Recorded, never edited: README.md is never touched by this campaign.

### release-signing -- S-400 release package signing

- Status: OPEN
- Source: S-400
- Owner: Volmarr
- Reopens when: The maintainer signs the package checksums with the key held outside this tree
- Note: The S-400 package ships unsigned by design of the slice: signing is a named remainder owned by Volmarr, not a defect and not done.

### v1-tag-placement -- S-401 v1.0 tag placement

- Status: NOT PROVEN
- Source: S-401
- Owner: keeper, on the wave400 counted verdict
- Reopens when: A finished counted run over the counted tree (banked main at 400/416) reads zero failures; only then is the tag placed
- Note: The tag law landed at S-401; the tag itself is NOT placed -- the wave400 counted verdict was unfinished when S-401 banked. If the verdict is not green: fix forward, fresh counted run, then the tag.

### founder-usability-walk -- S-402 Volmarr's usability walk

- Status: FOUNDER
- Source: S-402
- Owner: Volmarr
- Reopens when: Volmarr walks a fresh instance unaided: account, token, repo, push, mirror; every stumble is a defect fixed or commissioned on the spot
- Note: Founder-dependent by the roadmap's own text. No worker builds it, no battery substitutes for it, and this seed claims nothing about its outcome. It also owns part of the F-10 proof.

### standing-no-federation -- Standing exclusion: no federation between instances

- Status: REFUSED
- Source: roadmap standing exclusions (founding)
- Owner: Volmarr (revisited only by his word)
- Reopens when: Only Volmarr's word revisiting the founding exclusion
- Note: Decided at founding: no federation between Samverk instances or Samtal villages. Carried so the successor roadmap inherits the refusal, not a blank.

### standing-no-hosted-service -- Standing exclusion: no hosted-service ambitions

- Status: REFUSED
- Source: roadmap standing exclusions (founding)
- Owner: Volmarr (revisited only by his word)
- Reopens when: Only Volmarr's word revisiting the founding exclusion
- Note: Samverk is software its owner runs, not a platform operated for strangers.

### standing-no-invented-facts -- Standing exclusion: no AI features that invent facts

- Status: REFUSED
- Source: roadmap standing exclusions (founding)
- Owner: Volmarr (revisited only by his word)
- Reopens when: Only Volmarr's word revisiting the founding exclusion
- Note: No generated summaries presented as truth; anything automated is labelled and checkable -- 'The machine drafts. The human decides.'

### standing-no-docker -- Standing exclusion: no Docker

- Status: REFUSED
- Source: roadmap standing exclusions (founding) / S-264
- Owner: Volmarr (standing law)
- Reopens when: Only Volmarr's word overriding the law for a specific case
- Note: Not for Samverk, not for its runner, not for its docs' examples. Native installs only. The same law grounds the OCI refusal above; recorded once here as the standing law itself.

## How the successor roadmap grows from this seed

- Each item becomes a successor slice only when
  its reopen condition is met or its owner calls
  it forward; the seed itself builds none of them.
- Refused items stay refused until Volmarr's word
  revisits them; the seed records the refusal, it
  does not soften it.
- NOT PROVEN items flip only on counted proof in
  the cell they name, never on wording.
- The final census (S-404) closes the first
  roadmap against this seed: proven, NOT PROVEN,
  refused -- counted, plain, and complete.
