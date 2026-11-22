#!/usr/bin/env python3
"""S-400 -- Release packaging runner.

Packs the tracked source of this tree into the
deterministic release tarball, generates SHA256SUMS.txt
with S-260's format, probes the operator keyring for a
maintainer secret key (ids only -- key material is
never read or printed), writes the plain-words-first
release notes, and verifies the package round-trip with
S-260's verifier.

Usage: python3 tools/run_release_packaging.py --out-dir DIR
    [--log-md PATH] [--notes-md PATH]
Artifacts land in --out-dir; the counted log and the
notes are written where the caller names them.
Exit code 0 only when the round-trip verifies.
"""
import argparse, json, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from samverk.release_packaging import (
    CHECKSUMS_NAME, NOTES_NAME, TARBALL_NAME, package_files,
    render_packaging_log, render_release_notes, verify_package)

def _tracked_files() -> dict:
    out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
        capture_output=True, check=True).stdout
    files = {}
    for raw in out.decode("utf-8").split("\0"):
        if raw:
            files[raw] = (ROOT / raw).read_bytes()
    return files

def _secret_key_ids() -> list:
    try:
        out = subprocess.run(["gpg", "--list-secret-keys",
            "--with-colons"], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return []
    ids = []
    for line in out.stdout.decode("utf-8", "replace").splitlines():
        parts = line.split(":")
        if parts[0] == "sec" and len(parts) > 4 and parts[4]:
            ids.append(parts[4])
    return ids

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--log-md")
    ap.add_argument("--notes-md")
    args = ap.parse_args()
    files = _tracked_files()
    audit = package_files(files, _secret_key_ids())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Rebuild the exact tarball bytes for the artifact dir.
    from samverk.release_packaging import build_tarball_bytes
    tarball_bytes = build_tarball_bytes(files)
    (out_dir / TARBALL_NAME).write_bytes(tarball_bytes)
    (out_dir / CHECKSUMS_NAME).write_text(
        audit["checksums"], encoding="utf-8")
    notes = render_release_notes(audit)
    (out_dir / NOTES_NAME).write_text(notes, encoding="utf-8")
    verification = verify_package(audit["checksums"],
        {TARBALL_NAME: tarball_bytes})
    if args.log_md:
        Path(args.log_md).write_text(
            render_packaging_log(audit, verification),
            encoding="utf-8")
    if args.notes_md:
        Path(args.notes_md).write_text(notes, encoding="utf-8")
    print(json.dumps({**audit, "checksums": audit["checksums"],
        "verification": verification}, indent=2, sort_keys=True))
    print("VERDICT", "PASSED" if verification["ok"] else "FAILED")
    return 0 if verification["ok"] else 1

if __name__ == "__main__":
    raise SystemExit(main())
