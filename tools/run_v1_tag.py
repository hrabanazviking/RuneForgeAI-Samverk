#!/usr/bin/env python3
"""S-401 runner: aggregate the wave400 counted run from
the seat's shard logs, judge it under the counted-green
law, and (only when green and --place is given) place
the annotated v1.0 tag on the counted tree in this
repository and write the S-257-shaped release notes.

Usage: python3 tools/run_v1_tag.py [--place]
Reads:  ~/samverk-forge/hidden_files/shards-wave400/
Writes: hidden_files/s401-verdict.json (+ notes)
"""
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))

from samverk.v1_tag import (  # noqa: E402
    COUNTED_TREE, TAG_NAME, aggregate_shard_logs, build_census,
    judge_tag_placement, render_release_notes, render_remainder)

SEAT_LOGS = os.path.expanduser(
    "~/samverk-forge/hidden_files/shards-wave400")
OUT = os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), "hidden_files")


def main():
    texts = []
    for i in range(8):
        path = os.path.join(SEAT_LOGS, "shard-%02d.log" % i)
        with open(path, encoding="utf-8", errors="replace") as fh:
            texts.append(fh.read())
    verdict = aggregate_shard_logs(texts)
    census = build_census(
        slices_banked=400, roadmap_slices=416, verdict=verdict,
        claims_final_count=17,
        package_sha256=("d49482e6c3c8b4c4dda9e2a13f93078f2bedf"
                        "780173d23a702e03497eb015693"),
        schema=140, taxonomy=142)
    os.makedirs(OUT, exist_ok=True)
    record = dict(census)
    record["failures"] = list(verdict.failures)
    record["finished"] = verdict.finished
    with open(os.path.join(OUT, "s401-verdict.json"), "w") as fh:
        json.dump(record, fh, indent=2, sort_keys=True)
    print(json.dumps(record, indent=2, sort_keys=True))
    if "--place" not in sys.argv:
        return 0
    reasons = judge_tag_placement(verdict, COUNTED_TREE)
    if reasons:
        print(render_remainder(verdict))
        return 2
    notes = render_release_notes(census)
    notes_path = os.path.join(OUT, "s401-release-notes.md")
    with open(notes_path, "w") as fh:
        fh.write(notes)
    subprocess.run(
        ["git", "tag", "-a", TAG_NAME, "-F", notes_path,
         COUNTED_TREE], check=True)
    print("tagged %s on %s" % (TAG_NAME, COUNTED_TREE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
