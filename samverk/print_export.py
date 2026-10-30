"""Print and export of code views (S-116).

Code gets read on paper and in saved files, not only on
screen: a readable print stylesheet for blob and diff
pages, print-ready renderings of both, and plain-text
exports that carry the whole content.

- **The stylesheet is external, like everything else.**
  S-016's CSP admits styles only from the instance
  itself (`style-src 'self'`, no inline styles anywhere),
  so this module owns the canonical print CSS text
  (`PRINT_CSS`, served at `PRINT_STYLESHEET_PATH`) and
  the one `<link media="print">` tag blob and diff pages
  carry in their heads. No page emits a `<style>` block.
- **Readable means grayscale-honest.** The print rules
  strip colour to black on white and keep every meaning
  colour carried on screen in a second channel (the
  design lawbook's rule: colour is never the only
  signal): keywords print bold, comments italic, and
  diff additions/deletions print with their `+` / `-`
  markers restored by the stylesheet — the unified
  renderer's line text omits the marker, so without
  this a printed diff would be unreadable once the
  colour is gone. Navigation, forms, and actions do not
  print at all; code wraps instead of being clipped at
  the paper's edge; line numbers stay.
- **Print renderings never fold silently and never use
  `<details>`.** A closed `<details>` element's content
  does not reliably reach paper, so the print pages
  render every file as an open section. Folding still
  applies exactly as on screen (S-104's limit, with its
  true counts named) — print is not a way to smuggle
  past the fold, and the folded notice prints.
- **Exports are complete and plain.** `export_diff_text`
  rebuilds the unified patch from S-104's parsed
  structure — every line, folded or not — and
  `export_blob_text` returns the file's lines as plain
  text. An LFS pointer exports nothing and says why:
  exporting the pointer as if it were the file would
  be a lie in text form (S-100's download serves the
  real bytes).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from .diff_engine import FOLD_LIMIT, DiffSet
from .escaping import escape_html_text

if TYPE_CHECKING:  # annotation only — blob_view imports this
    # module's link tag, so the runtime import would cycle
    from .blob_view import BlobView

PRINT_STYLESHEET_PATH = "/static/samverk-print.css"

PRINT_CSS = """\
/* Samverk print stylesheet (S-116) — blob and diff pages.
   Colour is stripped to black on white; meaning that colour
   carried on screen is kept in weight, style, and markers. */
@page { margin: 18mm 15mm; }
@media print {
  nav, form, .repo-chrome, .repo-tabs, .repo-actions,
  .actions, .switcher, .breadcrumb, .no-print {
    display: none !important;
  }
  body { color: #000; background: #fff; font-size: 11pt;
         line-height: 1.45; }
  a { color: #000; text-decoration: none; }
  code, pre { font-family: ui-monospace, SFMono-Regular, Menlo,
              Consolas, monospace; font-size: 9.5pt;
              white-space: pre-wrap; overflow-wrap: anywhere; }
  .print-header { border-bottom: 1.5pt solid #000;
                  padding-bottom: 6pt; margin-bottom: 10pt; }
  .print-header h1 { font-size: 14pt; margin: 0 0 4pt; }
  .print-header .meta, .print-footer { font-size: 9pt; }
  .print-footer { border-top: 0.5pt solid #000; margin-top: 12pt;
                  padding-top: 6pt; }
  /* Syntax tokens: no colour survives, so weight and style
     carry the distinctions (grayscale coherence). */
  .tok-k { font-weight: bold; }
  .tok-c { font-style: italic; }
  .tok-s { font-style: normal; }
  .tok-n { font-weight: bold; }
  .blob .line { break-inside: avoid; }
  .blob .line-no { color: #000; text-decoration: none; }
  /* Diff markers: the line text omits + and -, so the
     stylesheet restores them — a printed diff must not
     depend on colour to say what changed. */
  .diff tr.dl-add td:last-child code::before { content: "+ "; }
  .diff tr.dl-del td:last-child code::before { content: "- "; }
  .diff td.dl-add code::before { content: "+ "; }
  .diff td.dl-del code::before { content: "- "; }
  .diff td { border: none; padding: 0 4pt; }
  .diff td.no { text-align: right; }
  .diff tr { break-inside: avoid; }
  .file-diff { margin-bottom: 12pt; }
  .file-diff > summary, .file-diff > h2 {
    font-size: 11pt; break-after: avoid; }
  .diff-folded, .binary { border: 1pt solid #000; padding: 6pt; }
}
"""


class PrintError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def print_stylesheet() -> str:
    """The canonical print CSS text, served externally at
    PRINT_STYLESHEET_PATH under S-016's style-src 'self'."""
    return PRINT_CSS


def stylesheet_link_tag() -> str:
    """The one tag a blob/diff page head carries for print.
    media="print" leaves screen rendering untouched."""
    return (f'<link rel="stylesheet" media="print" '
            f'href="{PRINT_STYLESHEET_PATH}">')


def render_blob_print_page(view: BlobView) -> str:
    """A print-ready blob page: a header naming the
    repository, path, full commit, and line count in
    words, then the lines themselves (S-099's escaped,
    highlighted HTML), then a footer repeating the pin —
    a printed page must say what it is a print *of*."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(view.full_name)} — "
        f"{escape_html_text(view.path)} — print — Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        '<header class="print-header">',
        f"<h1>{escape_html_text(view.path)}</h1>",
        f'<p class="meta">{escape_html_text(view.full_name)} · '
        f"commit {escape_html_text(view.commit_oid)} · "
        f"{escape_html_text(view.language)} · "
        f"{len(view.lines)} lines · {view.size} bytes</p>",
        "</header>",
    ]
    if view.is_lfs_pointer:
        parts.append(
            '<p class="lfs">This file is stored with Git LFS. '
            f"Its content is {view.lfs_size} bytes "
            f"(object {escape_html_text(view.lfs_oid or '')}); "
            "the download view serves the real bytes — there "
            "is no code to print here.</p>")
    elif not view.lines:
        parts.append('<p class="empty">This file is empty.</p>')
    else:
        parts.append('<div class="blob">')
        for line in view.lines:
            parts.append(
                f'<div class="line" id="L{line.number}">'
                f'<span class="line-no">{line.number}</span> '
                f"<code>{line.html if line.html else ' '}</code></div>")
        parts.append("</div>")
    parts.append(
        f'<footer class="print-footer">Printed from Samverk — '
        f"{escape_html_text(view.full_name)} · "
        f"{escape_html_text(view.path)} at commit "
        f"{escape_html_text(view.commit_oid)}</footer>")
    parts.append("</body></html>")
    return "\n".join(parts)


def render_diff_print_page(diffset: DiffSet, *, title: str,
                           subtitle: str = "") -> str:
    """A print-ready diff page in unified form (paper is
    one column, whichever form the screen used), one open
    section per file — never <details>, whose closed
    content does not reliably reach paper. Folding is
    S-104's, unchanged, with its counts named."""
    parts = [
        "<!DOCTYPE html>",
        '<html lang="en"><head><meta charset="utf-8">',
        f"<title>{escape_html_text(title)} — print — Samverk</title>",
        stylesheet_link_tag(),
        "</head>",
        "<body>",
        '<header class="print-header">',
        f"<h1>{escape_html_text(title)}</h1>",
        f'<p class="meta">{len(diffset.files)} files changed · '
        f"+{diffset.additions} −{diffset.deletions}"
        + (f" · {escape_html_text(subtitle)}" if subtitle else "")
        + "</p>",
        "</header>",
    ]
    for file in diffset.files:
        label = escape_html_text(file.path)
        if file.old_path and file.new_path \
                and file.old_path != file.new_path:
            label = (f"{escape_html_text(file.old_path)} → "
                     f"{escape_html_text(file.new_path)}")
        parts.append('<section class="file-diff">')
        parts.append(
            f"<h2>{label} +{file.additions} −{file.deletions}</h2>")
        if file.is_binary:
            parts.append(
                '<p class="binary">Binary file — no patch shown.</p>')
        elif len(file.lines) > FOLD_LIMIT:
            parts.append(
                '<p class="diff-folded">This change is folded: '
                f"{len(file.lines)} patch lines, +{file.additions} "
                f"−{file.deletions}, are not shown. The counts are "
                "the file's true counts. The text export carries "
                "every line.</p>")
        else:
            parts.append('<table class="diff unified">')
            for line in file.lines:
                old = "" if line.old_number is None else str(line.old_number)
                new = "" if line.new_number is None else str(line.new_number)
                parts.append(
                    f'<tr class="dl-{line.kind}"><td class="no">{old}</td>'
                    f'<td class="no">{new}</td>'
                    f"<td><code>{escape_html_text(line.text)}</code>"
                    "</td></tr>")
            parts.append("</table>")
        parts.append("</section>")
    parts.append(
        '<footer class="print-footer">Printed from Samverk — '
        f"{escape_html_text(title)}</footer>")
    parts.append("</body></html>")
    return "\n".join(parts)


def export_blob_text(view: BlobView) -> str:
    """The file as plain text: its lines joined, with the
    one trailing newline S-099's view separates restored.
    (A file whose last line had no newline gains one here;
    the raw/download view is the byte-exact road.) An LFS
    pointer refuses — its bytes are not the file."""
    if view.is_lfs_pointer:
        raise PrintError(
            "lfs_pointer",
            "This file is stored with Git LFS; the text export "
            "would be the pointer, not the file. Use the "
            "download view for the real bytes.")
    if not view.lines:
        return ""
    return "\n".join(line.text for line in view.lines) + "\n"


def export_diff_text(diffset: DiffSet) -> str:
    """The whole diff as a unified patch, rebuilt from
    S-104's parsed structure: every parsed line, including
    any the pages fold. Hunk headers ride as the meta
    lines the parser kept, so the patch re-reads through
    the same parser to the same counts."""
    out: list[str] = []
    for file in diffset.files:
        old = file.old_path if file.old_path is not None else "/dev/null"
        new = file.new_path if file.new_path is not None else "/dev/null"
        old_ref = old if old == "/dev/null" else f"a/{old}"
        new_ref = new if new == "/dev/null" else f"b/{new}"
        out.append(f"diff --git {old_ref} {new_ref}")
        if file.is_binary:
            out.append(f"Binary files {old_ref} and {new_ref} differ")
            continue
        out.append(f"--- {old_ref}")
        out.append(f"+++ {new_ref}")
        for line in file.lines:
            if line.kind == "add":
                out.append("+" + line.text)
            elif line.kind == "del":
                out.append("-" + line.text)
            elif line.kind == "meta":
                out.append(line.text)
            else:
                out.append(" " + line.text)
    return "\n".join(out) + ("\n" if out else "")
