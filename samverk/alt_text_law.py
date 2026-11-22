"""Alt-text law (S-390).

Roadmap S-390: Alt-text law -- every image in the UI and
docs carries real alt text, including avatars
(user-supplied alt honoured) and diagrams (described,
not "image").

This is Volmarr's standing image-accessibility law
(2026-10-19) stated once, as code, for the whole forge:

- `judge_alt` judges one alt text: missing, generic
  ("image", "picture", "photo", "diagram", "graphic"),
  or a bare filename are all refused; a diagram's alt
  must actually describe it (at least DIAGRAM_MIN_WORDS
  words), never just name the kind.
- `decide_alt` honours the user: a user-supplied alt
  that passes the judge wins over the authored one
  (avatars work this way since profiles' S-185-era
  policy, `validate_avatar_alt`); a user alt that fails
  falls back to the authored alt, and if neither passes
  the image is refused, never shipped alt-less.
- `fallback_alt` is the floor for rendered content
  images (the markdown pipeline's seam): when an author
  wrote no real alt, the rendered alt names the image
  file and its place, after media_view's standing
  pattern -- a floor, never a decoration.
- `audit_rendered` and `audit_docs` sweep the shipped
  surfaces: every <img> in rendered HTML, every image
  in the docs tree, judged by the same law.

Pure code: no store, no audit event, no migration --
schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

import re
from pathlib import Path

GENERIC_ALT = {"image", "picture", "photo", "diagram", "graphic",
               "img", "icon", "logo", "screenshot", "untitled"}
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")
DIAGRAM_MIN_WORDS = 5


def judge_alt(alt, kind="image"):
    """Judge one alt text; [] means it carries real meaning."""
    if alt is None or not str(alt).strip():
        return ["alt_missing"]
    text = str(alt).strip()
    problems = []
    if text.lower() in GENERIC_ALT:
        problems.append("alt_generic")
    if " " not in text and text.lower().endswith(IMAGE_SUFFIXES):
        problems.append("alt_is_filename")
    if kind == "diagram" and len(text.split()) < DIAGRAM_MIN_WORDS:
        problems.append("alt_diagram_too_thin")
    return problems


def decide_alt(authored, user_supplied, kind="image"):
    """The user's real alt wins; a failing user alt falls back."""
    if user_supplied is not None and judge_alt(user_supplied, kind) == []:
        return user_supplied
    if judge_alt(authored, kind) == []:
        return authored
    return None


def fallback_alt(src, label):
    """Authored alt if real, else the floor naming the file."""
    if judge_alt(label) == []:
        return label
    name = str(src).rstrip("/").rsplit("/", 1)[-1] or "unnamed"
    return f"Image file {name}"


def audit_rendered(html, kind="image"):
    """Every <img> in rendered HTML carries judged alt text."""
    problems = []
    for tag in re.findall(r"<img [^>]*>", html):
        match = re.search(r'alt="([^"]*)"', tag)
        alt = match.group(1) if match else None
        for problem in judge_alt(alt, kind):
            problems.append(f"{problem}:{tag[:48]}")
    return problems


def audit_docs(root=None):
    """Every image in the docs tree carries judged alt text."""
    base = (Path(__file__).resolve().parent.parent / "docs"
            if root is None else Path(root))
    problems = []
    for path in sorted(base.rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        for alt in re.findall(r"!\[([^\]]*)\]\([^)]*\)", text):
            for problem in judge_alt(alt):
                problems.append(f"{problem}:{path.name}")
        for tag in re.findall(r"<img [^>]*>", text):
            match = re.search(r'alt="([^"]*)"', tag)
            for problem in judge_alt(match.group(1) if match else None):
                problems.append(f"{problem}:{path.name}")
    return problems


def alt_text_passed():
    return audit_docs() == []
