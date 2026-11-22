# The v1.0 tag (S-401) -- counted-green tree only

Roadmap S-401: the v1.0 tag is tagged on the counted-green
tree only; the tag's release (S-257, on Samverk itself,
dogfooded) carries the census. The law module is
`samverk/v1_tag.py`; its battery is `tests/test_v1_tag.py`;
the runner is `tools/run_v1_tag.py`.

## Tag state

Tag NOT placed. The wave400 counted run over the counted
tree is still running (started 2026-11-22 17:45 EST,
sharded runner, label wave400, logs in the seat at
~/samverk-forge/hidden_files/shards-wave400/). No shard
has finished, so there is no counted verdict for the
counted tree yet: the verdict is unfinished -- NOT PROVEN
-- and under the counted-green law no tag may be placed.
The keeper places the tag only when a finished counted
run over this exact tree reads zero failures.

Counted tree: 6ede324e2e09cabb087fb8d2992430fe5557a0cb
(banked main at 400/416, S-400 banking commit).

Counted: Ran 0 / Passed 0 / Failed 0 / Skipped 0
(aggregation of the wave400 shard logs as they stand:
no shard carries a Ran line yet, so the run is unfinished
and these zeros mean "not yet counted", never "green".)

## Census

The census the v1.0 release will carry, from disk:

- Tag: v1.0 on 6ede324e2e09cabb087fb8d2992430fe5557a0cb
- Roadmap slices banked: 400 of 416
- Claims register: 17 final rows (S-399)
- Release package (S-400): SHA-256 d49482e6c3c8b4c4dda9e2a13f93078f2bedf780173d23a702e03497eb015693
- Schema 140, taxonomy 142 stand

## Honest remainders

- Tag placement awaits the wave400 counted verdict; if
  that verdict is not green, the road is fix forward,
  then a fresh counted run over the fixed tree, then
  the tag (a changed tree is not the counted tree).
- The S-400 package ships unsigned: the maintainer signs
  its checksums with the key held outside this tree
  (named remainder, owned by Volmarr).
- Slices S-402..S-416 stand open in roadmap order; the
  claims register's NOT PROVEN rows (F-02, F-10, F-11)
  keep their named owners.
