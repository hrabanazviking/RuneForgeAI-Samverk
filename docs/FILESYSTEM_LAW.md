# Filesystem Law (S-408)

Roadmap: *repository storage and metadata correct on case-sensitive
and case-insensitive filesystems; the two-names-differing-only-by-case
collision is handled deterministically and tested on both kinds.*

Module: `samverk/filesystem_law.py` · Battery:
`tests/test_filesystem_law.py` · Runner: `tools/run_filesystem_law.py`

## The law

1. **Case-fold identity.** Two storage names differing only by case
   (Unicode `casefold`) are the same name for storage purposes. On an
   insensitive filesystem they are one file; on a sensitive one they
   are two files that silently merge when the tree is copied or
   checked out onto an insensitive filesystem. The collision is a
   defect on BOTH kinds.
2. **Deterministic refusal — never silent overwrite.** A colliding
   name set is refused as a whole (`FilesystemLawError`, stable
   reason `case_collision`; exact duplicates get `duplicate_name`).
   Colliding names are reported in sorted codepoint order; no name
   wins by arrival or directory order. The outcome is identical on
   every OS and run. This follows the S-013 `repo_paths` convention
   (ValueError subclass with a stable `reason`); `plan_storage()`
   gives a lawful set a plan that materialises identically on
   either filesystem kind.
3. **Probe, don't guess.** Filesystem kind is probed (two files
   differing only by case; count what survives), never inferred
   from the OS — case-sensitive APFS volumes and case-insensitive
   Linux mounts both exist.

## What is proven / NOT PROVEN

- PROVEN on this host (Linux, probed case-SENSITIVE): the probe
  matches a manual two-file probe; on-disk colliding pairs are
  detected by `audit_directory`; probe files are cleaned up.
- PROVEN by construction + battery on both kinds: the name law is
  pure string logic, platform-independent; the same refusal fires
  regardless of filesystem kind.
- SIMULATED, honestly labelled: the insensitive kind is exercised
  through `SimulatedInsensitiveDirectory` (casefold-keyed in-memory
  model showing the merge the law prevents).
- NOT PROVEN: a run on a real case-insensitive filesystem (real
  NTFS / default APFS / exFAT). No such volume was available on
  the build host; none is claimed.
