"""S-406 — Platform seam audit.

Scans every ``samverk/*.py`` module's *code* (comments and string
literals stripped via tokenize, so doc mentions never count) for OS
touchpoints outside the platform seam (``samverk/platform_seam.py``)
and the named process home (``samverk/proc.py``, S-014).

A touchpoint outside the seam is either routed through the seam or
carried on the explicit INVENTORY below with its reason — an
uninventoried stray fails the audit. The full inventory is published
in docs/PLATFORM_SEAM.md.
"""
from __future__ import annotations

import io
import re
import tokenize
from pathlib import Path

PATTERNS = {
    "process": re.compile(r"subprocess\.|os\.system\b|os\.popen\b|os\.exec|os\.spawn"),
    "signals": re.compile(r"\bsignal\.|os\.kill\b|os\.killpg\b"),
    "locking": re.compile(r"\bfcntl\b|\bmsvcrt\b|\.flock\b"),
    "permissions": re.compile(r"os\.chmod\b|\.chmod\(|os\.chown\b|os\.umask\b|stat\.S_"),
    "platform_id": re.compile(r"sys\.platform|os\.name\b|platform\.(machine|platform|system|uname)"),
}

SEAM_MODULES = {"platform_seam.py", "platform_seam_audit.py"}

# Named remainders: file -> {category: reason}. Anything found that
# is not listed here is an uninventoried stray and fails the audit.
INVENTORY = {
    "proc.py": {"process": "S-014 process policy home; the seam docstring names it as the LANDED home for process creation (allowlists live there)."},
    "reference_runner.py": {"process": "Runs the external reference implementation under the S-014 subprocess law for parity checks; not forge-core process creation."},
    "seam_battery.py": {"process": "Battery harness: shells to git to build seam fixtures; test tooling, not shipped runtime."},
    "upgrade_drill.py": {"process": "Upgrade drill tooling: shells to git against drill repos; operator tooling, not shipped runtime."},
}


def code_lines(path: Path):
    """Yield (lineno, code-text) with comments/strings blanked."""
    src = path.read_bytes()
    lines = src.decode("utf-8", "replace").splitlines()
    code = [list(l) for l in lines]
    try:
        toks = tokenize.tokenize(io.BytesIO(src).readline)
        for tok in toks:
            if tok.type in (tokenize.STRING, tokenize.COMMENT):
                (sl, sc), (el, ec) = tok.start, tok.end
                for ln in range(sl, el + 1):
                    row = code[ln - 1]
                    a = sc if ln == sl else 0
                    b = ec if ln == el else len(row)
                    for i in range(a, min(b, len(row))):
                        row[i] = " "
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return [(i + 1, "".join(r)) for i, r in enumerate(code)]


def audit_tree(root: Path) -> dict:
    """Audit *root*/samverk. Returns counts + stray/inventoried lists."""
    pkg = Path(root) / "samverk"
    inventoried, strays = [], []
    per_category = {c: 0 for c in PATTERNS}
    files_scanned = 0
    for path in sorted(pkg.glob("*.py")):
        if path.name in SEAM_MODULES:
            continue
        files_scanned += 1
        for lineno, text in code_lines(path):
            for cat, pat in PATTERNS.items():
                if pat.search(text):
                    per_category[cat] += 1
                    entry = {"file": f"samverk/{path.name}", "line": lineno,
                             "category": cat, "text": text.strip()[:110]}
                    if cat in INVENTORY.get(path.name, {}):
                        inventoried.append(entry)
                    else:
                        strays.append(entry)
    return {"files_scanned": files_scanned, "per_category": per_category,
            "inventoried": inventoried, "strays": strays,
            "clean": not strays}
