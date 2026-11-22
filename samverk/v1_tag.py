"""The v1.0 tag (S-401).

Roadmap S-401: **The v1.0 tag -- tagged on the
counted-green tree only; the tag's release (S-257, on
Samverk itself, dogfooded) carries the census.**

The laws:

- **Counted-green only.** The tag may be placed only
  on a tree whose counted full-suite verdict is green:
  ``failed == 0`` in a completed counted run over that
  exact tree. ``judge_counted_verdict`` is the pure
  judgement and ``may_tag`` is its one-word answer; a
  run that is unfinished, uncounted, or carries any
  failure -- however familiar its class -- is NOT
  green, and no wording in this module ever calls it
  green. The prior counted run (S-393) stood at 15
  failures and would not have carried this tag.
- **The tag names one tree.** ``TAG_NAME`` is ``v1.0``
  and ``COUNTED_TREE`` is the commit the wave-391-400
  counted run (label wave400) executes: the banked
  main at 400/416. A tag placed on any other commit
  is not the v1.0 tag this slice defines, and
  ``judge_tag_placement`` refuses it by name.
- **The release carries the census.** The tag's
  release is S-257's own row, created through
  ``ReleaseStore`` on Samverk itself (dogfooded), and
  its notes are ``render_release_notes``: the census
  first -- slices banked, the counted verdict in
  numbers, the claims register's final count, the
  release package's digest, the schema and taxonomy
  as they stand -- then the honest remainders, in
  words. A census number is never invented here:
  ``build_census`` takes every count from its caller,
  who read it from disk or from the counted run.
- **A non-green verdict is a named remainder, never
  a tag.** ``render_remainder`` names every failure
  the counted run named and states the road: fix
  forward, then a fresh counted run over the fixed
  tree, then the tag. Fixing a failure changes the
  tree, and a changed tree is not the counted tree.

No migration and no new taxonomy event: the schema
stands at 140 and the taxonomy stands at 142. Placing
a git tag and creating an S-257 release row witness
nothing new in the taxonomy's frozen vocabulary.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = [
    "TAG_NAME", "COUNTED_TREE", "CountedVerdict",
    "judge_counted_verdict", "may_tag",
    "aggregate_shard_logs", "build_census",
    "judge_tag_placement", "render_release_notes",
    "render_remainder",
]

TAG_NAME = "v1.0"

# The banked main at 400/416 (S-400 banking commit);
# the tree the wave400 counted run executes.
COUNTED_TREE = "6ede324e2e09cabb087fb8d2992430fe5557a0cb"


@dataclass(frozen=True)
class CountedVerdict:
    ran: int
    passed: int
    failed: int
    skipped: int
    failures: tuple = ()
    finished: bool = True

    def arithmetic_holds(self) -> bool:
        return self.passed + self.failed + self.skipped == self.ran


def judge_counted_verdict(verdict: CountedVerdict) -> str:
    """``green`` only for a finished, arithmetically
    sound counted run with zero failures."""
    if not verdict.finished:
        return "unfinished"
    if not verdict.arithmetic_holds():
        return "uncounted"
    if verdict.failed != 0:
        return "not_green"
    return "green"


def may_tag(verdict: CountedVerdict) -> bool:
    return judge_counted_verdict(verdict) == "green"


_RAN_RE = re.compile(r"Ran (\d+) tests")
_SKIP_RE = re.compile(r"skipped=(\d+)")
_FAIL_RE = re.compile(r"^(?:FAIL|ERROR): (\S+)", re.M)


def aggregate_shard_logs(log_texts) -> CountedVerdict:
    """Aggregate per-shard unittest logs the standing
    way (the S-393 counting): a shard's fail count is
    its FAIL/ERROR lines; a shard with no ``Ran`` line
    means the run has not finished that shard, so the
    verdict is unfinished."""
    ran = skipped = failed = 0
    failures = []
    finished = True
    for text in log_texts:
        m = _RAN_RE.search(text)
        if m is None:
            finished = False
            continue
        ran += int(m.group(1))
        s = _SKIP_RE.search(text)
        if s:
            skipped += int(s.group(1))
        names = _FAIL_RE.findall(text)
        failed += len(names)
        failures.extend(names)
    return CountedVerdict(
        ran=ran, passed=ran - failed - skipped,
        failed=failed, skipped=skipped,
        failures=tuple(failures), finished=finished)


def build_census(*, slices_banked: int, roadmap_slices: int,
                 verdict: CountedVerdict, claims_final_count: int,
                 package_sha256: str, schema: int,
                 taxonomy: int) -> dict:
    return {
        "tag": TAG_NAME,
        "counted_tree": COUNTED_TREE,
        "slices_banked": slices_banked,
        "roadmap_slices": roadmap_slices,
        "counted_ran": verdict.ran,
        "counted_passed": verdict.passed,
        "counted_failed": verdict.failed,
        "counted_skipped": verdict.skipped,
        "counted_verdict": judge_counted_verdict(verdict),
        "claims_final_count": claims_final_count,
        "package_sha256": package_sha256,
        "schema": schema,
        "taxonomy": taxonomy,
    }


def judge_tag_placement(verdict: CountedVerdict,
                        target: str) -> tuple:
    """Reasons the tag may not be placed; empty = lawful."""
    reasons = []
    state = judge_counted_verdict(verdict)
    if state != "green":
        reasons.append("counted verdict is %s, not green" % state)
    if target != COUNTED_TREE:
        reasons.append(
            "tag target %s is not the counted tree %s"
            % (target, COUNTED_TREE))
    return tuple(reasons)


def render_release_notes(census: dict) -> str:
    """The S-257 release notes carrying the census.
    Lawful only when the census verdict is green; the
    caller checks ``may_tag`` first."""
    lines = [
        "# Samverk v1.0",
        "",
        "In plain words: this is Samverk's first versioned",
        "release, tagged on the counted-green tree only.",
        "",
        "## Census",
        "",
        "- Tag: %s on %s" % (census["tag"], census["counted_tree"]),
        "- Roadmap slices banked: %d of %d"
        % (census["slices_banked"], census["roadmap_slices"]),
        "- Counted run: %d ran / %d passed / %d failed / %d skipped"
        % (census["counted_ran"], census["counted_passed"],
           census["counted_failed"], census["counted_skipped"]),
        "- Claims register: %d final rows (S-399)"
        % census["claims_final_count"],
        "- Release package (S-400): SHA-256 %s"
        % census["package_sha256"],
        "- Schema %d, taxonomy %d stand"
        % (census["schema"], census["taxonomy"]),
        "",
        "## Honest remainders",
        "",
        "- The S-400 package ships unsigned: the maintainer",
        "  signs its checksums with the key held outside",
        "  this tree (named remainder, owned by Volmarr).",
        "- Slices S-402..S-416 stand open in roadmap order;",
        "  the claims register's NOT PROVEN rows (F-02,",
        "  F-10, F-11) keep their named owners.",
        "",
    ]
    return "\n".join(lines)


def render_remainder(verdict: CountedVerdict) -> str:
    """The honest record when the tag may NOT be placed:
    every failure named, the road stated, no tag."""
    lines = [
        "The v1.0 tag was NOT placed: the counted verdict",
        "is %s (%d ran / %d passed / %d failed / %d skipped)."
        % (judge_counted_verdict(verdict), verdict.ran,
           verdict.passed, verdict.failed, verdict.skipped),
        "",
        "Failures named by the counted run:",
    ]
    if verdict.failures:
        lines += ["- %s" % name for name in verdict.failures]
    else:
        lines.append("- (none named; the run is unfinished or uncounted)")
    lines += [
        "",
        "Road: fix forward under the Never-Leave-A-Bug law,",
        "then a fresh counted run over the fixed tree; the",
        "tag is placed only on a counted-green verdict.",
        "",
    ]
    return "\n".join(lines)
