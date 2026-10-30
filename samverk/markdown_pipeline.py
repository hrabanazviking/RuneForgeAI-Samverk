"""Markdown pipeline (S-107) — the full renderer behind the S-010 seam.

S-097's repository home shipped with an interim safe renderer and
named this slice as its replacement: one sanitised Markdown
pipeline that every prose surface (READMEs now; issues, comments
and pull requests in their own parts) renders through, so
sanitisation is written once and audited once.

- **Escape first, build second.** No stored byte reaches the
  output as markup. Inline code spans and link/image targets are
  lifted out as placeholders *before* the surrounding text is
  escaped through S-010; emphasis and autolinking then run on
  already-escaped text; placeholders are restored last. Raw HTML
  in the source is therefore visible text, never tags — the XSS
  battery in tests/test_markdown_pipeline.py attacks every
  construct this module emits (headings, links, images, tables,
  code fences, quotes, task lists) and none may emit a stored
  tag, event handler, or dangerous URL.
- **URLs are sanitised, never merely escaped.** Link and image
  destinations pass S-010's `safe_url` (or the caller's resolver,
  S-108's seam): a `javascript:`, `data:`, entity-obfuscated or
  protocol-relative destination produces *no link at all* — the
  link text (or an image's alt text) renders as plain text, so
  nothing the author wrote silently vanishes and nothing unsafe
  becomes clickable.
- **The constructs the roadmap names** — headings with anchors
  (slugified from the heading's plain text, deduplicated within
  the document, each heading carrying a permalink), task lists
  (checkboxes rendered disabled: the rendered page is a view,
  not a form), tables (with column alignment), and code fences
  (language named as a class only when it is a plain token) —
  plus the ordinary prose set: paragraphs, ordered/unordered
  and nested lists, blockquotes, horizontal rules, inline code,
  bold/italic/strikethrough, reference-style links, and bare-URL
  autolinks.
- **Seams for the slices that follow.** `link_resolver` is
  S-108's door: a callable `(url, kind) -> str | None` ('link'
  or 'image') that may rewrite a destination (repo-relative
  resolution) or refuse it. `reference_resolver` is S-109's:
  a callable `(kind, value) -> str | None` ('mention', 'issue',
  'commit') asked to confirm and locate prose references before
  they become links, so a hex word is never linked as a commit
  unless the resolver proves the object exists.

The renderer never raises on malformed input: worst case, the
source renders as plain paragraphs. A forge page must not fall
over because a README is odd.
"""

from __future__ import annotations

import re
from typing import Callable

from .escaping import escape_html_attr, escape_html_text, safe_url

LinkResolver = Callable[[str, str], "str | None"]
ReferenceResolver = Callable[[str, str], "str | None"]

_PLACEHOLDER = "\x00%d\x00"
_FENCE_RE = re.compile(r"^\s{0,3}(```+|~~~+)\s*([^\s`~]*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_HR_RE = re.compile(r"^\s{0,3}([-*_])(\s*\1){2,}\s*$")
_LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_REFDEF_RE = re.compile(r"^\s{0,3}\[([^\]]+)\]:\s*(\S+)(?:\s+.*)?$")
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{1,}:?\s*(\|\s*:?-{1,}:?\s*)*\|?\s*$")
_CODE_SPAN_RE = re.compile(r"``(.+?)``|`([^`\n]+)`", re.DOTALL)
_LINK_RE = re.compile(
    r"(!?)\[([^\]]*)\]\(\s*((?:[^()\s]|\([^()\s]*\))+)"
    r"(?:\s+[\"'][^\"']*[\"'])?\s*\)"
    r"|(!?)\[([^\]]+)\]\[([^\]]*)\]"
    r"|(!?)\[([^\]]+)\](?![\[(])")
_BARE_URL_RE = re.compile(r"https?://[^\s<\x00]+")
_REF_TOKEN_RE = re.compile(
    r"(?<![\w.-])@([A-Za-z0-9][A-Za-z0-9-]{0,38})"
    r"|(?<![\w#])#(\d+)"
    r"|\b([0-9a-f]{7,40})\b")
_TRAILING_PUNCT = ".,;:!?)]}'\""


def slugify(plain_text: str, seen: dict[str, int]) -> str:
    """A heading anchor: the heading's plain words, lowered,
    punctuation dropped, spaces hyphenated, deduplicated
    within the document (`intro`, `intro-1`, …)."""
    slug = re.sub(r"[^\w\s-]", "", plain_text.lower())
    slug = re.sub(r"[\s_]+", "-", slug).strip("-")
    slug = re.sub(r"-{2,}", "-", slug) or "heading"
    count = seen.get(slug, 0)
    seen[slug] = count + 1
    return slug if count == 0 else f"{slug}-{count}"


def _plain_text(markdown: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", markdown)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"!?\[([^\]]*)\]\[[^\]]*\]", r"\1", text)
    text = re.sub(r"[*_~]{1,3}([^*_~]+)[*_~]{1,3}", r"\1", text)
    return text.strip()


class _Renderer:
    def __init__(self, link_resolver: LinkResolver | None,
                 reference_resolver: ReferenceResolver | None):
        self._link_resolver = link_resolver
        self._reference_resolver = reference_resolver
        self._refs: dict[str, str] = {}
        self._slugs: dict[str, int] = {}
        self._slots: list[str] = []

    # -- placeholder machinery ------------------------------------
    def _slot(self, html: str) -> str:
        self._slots.append(html)
        return _PLACEHOLDER % (len(self._slots) - 1)

    def _restore(self, text: str) -> str:
        # Slots can nest (a code span inside link text), so
        # restore until no placeholder remains.
        while "\x00" in text:
            restored = re.sub(
                r"\x00(\d+)\x00",
                lambda m: self._slots[int(m.group(1))]
                if int(m.group(1)) < len(self._slots) else "",
                text)
            if restored == text:
                break
            text = restored
        return text

    def _resolve(self, url: str, kind: str) -> str | None:
        if self._link_resolver is not None:
            return self._link_resolver(url, kind)
        return safe_url(url)

    # -- inline -----------------------------------------------------
    def render_inline(self, raw: str) -> str:
        text = raw.replace("\x00", "")
        # 1. Code spans first: their content is literal, and no
        #    later step may format inside them.
        def keep_code(match: re.Match) -> str:
            content = match.group(1) if match.group(1) is not None \
                else match.group(2)
            return self._slot(f"<code>{escape_html_text(content)}</code>")
        text = _CODE_SPAN_RE.sub(keep_code, text)
        # 2. Links and images: destinations sanitised now, while
        #    they are still raw; unsafe ones degrade to text.
        text = _LINK_RE.sub(self._keep_link, text)
        # 3. Escape everything that is left.
        text = escape_html_text(text)
        # 4. Bare URLs autolink on the escaped text (an & in a
        #    query string is &amp; there and belongs in the href
        #    exactly as escaped).
        text = _BARE_URL_RE.sub(self._keep_bare_url, text)
        # 5. Prose references (S-109 seam) and emphasis run on
        #    escaped text outside any tag this module emitted.
        text = self._autolink_references(text)
        text = self._emphasis(text)
        # 6. Restore the protected fragments.
        return self._restore(text)

    def _keep_link(self, match: re.Match) -> str:
        if match.group(1) is not None or match.group(4) is not None:
            bang = match.group(1) if match.group(1) is not None \
                else match.group(4)
            label = match.group(2) if match.group(2) is not None \
                else match.group(5)
            if match.group(3) is not None:
                dest = match.group(3)
            else:
                ref = (match.group(6) or label).strip().lower()
                dest = self._refs.get(ref)
                if dest is None:
                    return match.group(0)
        else:
            bang = match.group(7)
            label = match.group(8)
            dest = self._refs.get(label.strip().lower())
            if dest is None:
                return match.group(0)
        kind = "image" if bang == "!" else "link"
        resolved = self._resolve(dest, kind)
        # Link text gets escaping + emphasis but no nested links;
        # code-span placeholders inside it survive for _restore.
        inner = self._emphasis(escape_html_text(label))
        if resolved is None:
            # No link: the words (or the image's alt text, which
            # accessibility law never lets us drop silently)
            # render as plain text.
            return self._slot(inner)
        href = escape_html_attr(resolved)
        if kind == "image":
            return self._slot(
                f'<img src="{href}" alt="{escape_html_attr(label)}">')
        return self._slot(f'<a href="{href}">{inner}</a>')

    def _keep_bare_url(self, match: re.Match) -> str:
        url = match.group(0)
        trailing = ""
        while url and url[-1] in _TRAILING_PUNCT:
            trailing = url[-1] + trailing
            url = url[:-1]
        if not url:
            return match.group(0)
        return self._slot(f'<a href="{url}">{url}</a>') + trailing

    def _autolink_references(self, escaped: str) -> str:
        if self._reference_resolver is None:
            return escaped
        parts = re.split(r"(<[^>]+>)", escaped)
        for idx, part in enumerate(parts):
            if part.startswith("<"):
                continue
            parts[idx] = _REF_TOKEN_RE.sub(self._keep_reference, part)
        return "".join(parts)

    def _keep_reference(self, match: re.Match) -> str:
        if match.group(1) is not None:
            kind, value, shown = "mention", match.group(1), \
                "@" + match.group(1)
        elif match.group(2) is not None:
            kind, value, shown = "issue", match.group(2), \
                "#" + match.group(2)
        else:
            kind, value, shown = "commit", match.group(3), match.group(3)
        url = self._reference_resolver(kind, value)
        if url is None:
            return match.group(0)
        return self._slot(
            f'<a href="{escape_html_attr(url)}">{escape_html_text(shown)}</a>')

    @staticmethod
    def _emphasis(escaped: str) -> str:
        text = re.sub(r"~~([^~]+)~~", r"<del>\1</del>", escaped)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<![\w])__([^_]+)__(?![\w])",
                      r"<strong>\1</strong>", text)
        text = re.sub(r"\*([^*\n]+)\*", r"<em>\1</em>", text)
        text = re.sub(r"(?<![\w])_([^_\n]+)_(?![\w])", r"<em>\1</em>", text)
        return text

    # -- blocks -----------------------------------------------------
    def render(self, text: str) -> str:
        lines = text.replace("\r\n", "\n").replace("\r", "\n") \
            .replace("\x00", "").split("\n")
        lines = self._collect_refs(lines)
        html, _ = self._render_blocks(lines, 0, len(lines))
        return html

    def _collect_refs(self, lines: list[str]) -> list[str]:
        kept: list[str] = []
        in_fence = False
        for line in lines:
            if _FENCE_RE.match(line):
                in_fence = not in_fence
                kept.append(line)
                continue
            if not in_fence:
                match = _REFDEF_RE.match(line)
                if match:
                    self._refs[match.group(1).strip().lower()] = \
                        match.group(2)
                    continue
            kept.append(line)
        return kept

    def _render_blocks(self, lines: list[str], start: int,
                       end: int) -> tuple[str, int]:
        out: list[str] = []
        i = start
        while i < end:
            line = lines[i]
            stripped = line.strip()
            if not stripped:
                i += 1
                continue
            fence = _FENCE_RE.match(line)
            if fence:
                html, i = self._render_fence(lines, i, end, fence)
                out.append(html)
                continue
            heading = _HEADING_RE.match(line)
            if heading:
                level = len(heading.group(1))
                body = heading.group(2)
                plain = _plain_text(body)
                slug = slugify(plain, self._slugs)
                out.append(
                    f'<h{level} id="{escape_html_attr(slug)}">'
                    f"{self.render_inline(body)}"
                    f'<a class="heading-anchor" href="#{escape_html_attr(slug)}" '
                    f'aria-label="Permalink to {escape_html_attr(plain)}">#</a>'
                    f"</h{level}>")
                i += 1
                continue
            if _HR_RE.match(line):
                out.append("<hr>")
                i += 1
                continue
            if self._is_table_start(lines, i, end):
                html, i = self._render_table(lines, i, end)
                out.append(html)
                continue
            if stripped.startswith(">"):
                html, i = self._render_quote(lines, i, end)
                out.append(html)
                continue
            if _LIST_RE.match(line):
                html, i = self._render_list(lines, i, end)
                out.append(html)
                continue
            # Setext heading: a paragraph line underlined by
            # === (h1) or --- (h2).
            if i + 1 < end and re.match(r"^\s{0,3}(=+|-+)\s*$", lines[i + 1]) \
                    and not _LIST_RE.match(line):
                level = 1 if lines[i + 1].strip().startswith("=") else 2
                plain = _plain_text(stripped)
                slug = slugify(plain, self._slugs)
                out.append(
                    f'<h{level} id="{escape_html_attr(slug)}">'
                    f"{self.render_inline(stripped)}"
                    f'<a class="heading-anchor" href="#{escape_html_attr(slug)}" '
                    f'aria-label="Permalink to {escape_html_attr(plain)}">#</a>'
                    f"</h{level}>")
                i += 2
                continue
            # Paragraph: gather until a blank line or a block
            # construct starts.
            para = [stripped]
            i += 1
            while i < end and lines[i].strip() \
                    and not self._starts_block(lines, i, end):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{self.render_inline(chr(10).join(para))}</p>")
        return "\n".join(out), i

    def _starts_block(self, lines: list[str], i: int, end: int) -> bool:
        line = lines[i]
        if _FENCE_RE.match(line) or _HEADING_RE.match(line) \
                or _HR_RE.match(line) or _LIST_RE.match(line) \
                or line.strip().startswith(">"):
            return True
        if self._is_table_start(lines, i, end):
            return True
        # A setext underline ends the paragraph as a heading.
        return bool(i + 1 < end
                    and re.match(r"^\s{0,3}(=+|-+)\s*$", lines[i + 1]))

    def _render_fence(self, lines: list[str], i: int, end: int,
                      fence: re.Match) -> tuple[str, int]:
        marker = fence.group(1)
        char = marker[0]
        language = fence.group(2)
        code: list[str] = []
        closed = False
        i += 1
        while i < end:
            closing = _FENCE_RE.match(lines[i])
            if closing and closing.group(1)[0] == char \
                    and len(closing.group(1)) >= len(marker):
                i += 1
                closed = True
                break
            code.append(lines[i])
            i += 1
        if not closed and code and code[-1] == "":
            # An unterminated fence runs to EOF; the document's
            # final newline is a terminator, not a blank line.
            code.pop()
        body = escape_html_text("\n".join(code))
        if language and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_+-]*", language):
            return (f'<pre><code class="language-{escape_html_attr(language)}">'
                    f"{body}</code></pre>", i)
        return f"<pre><code>{body}</code></pre>", i

    def _is_table_start(self, lines: list[str], i: int, end: int) -> bool:
        return i + 1 < end and "|" in lines[i] \
            and bool(_TABLE_SEP_RE.match(lines[i + 1])) \
            and "-" in lines[i + 1]

    @staticmethod
    def _split_row(line: str) -> list[str]:
        text = line.strip()
        if text.startswith("|"):
            text = text[1:]
        if text.endswith("|"):
            text = text[:-1]
        return [cell.strip() for cell in text.split("|")]

    def _render_table(self, lines: list[str], i: int,
                      end: int) -> tuple[str, int]:
        headers = self._split_row(lines[i])
        separators = self._split_row(lines[i + 1])
        aligns: list[str] = []
        for cell in separators:
            if cell.startswith(":") and cell.endswith(":"):
                aligns.append("center")
            elif cell.endswith(":"):
                aligns.append("right")
            elif cell.startswith(":"):
                aligns.append("left")
            else:
                aligns.append("")
        i += 2
        rows: list[list[str]] = []
        while i < end and lines[i].strip() and "|" in lines[i]:
            rows.append(self._split_row(lines[i]))
            i += 1

        def cell(tag: str, value: str, idx: int) -> str:
            align = aligns[idx] if idx < len(aligns) else ""
            attr = f' align="{align}"' if align else ""
            return f"<{tag}{attr}>{self.render_inline(value)}</{tag}>"

        out = ["<table>", "<thead><tr>"]
        out.append("".join(cell("th", h, n) for n, h in enumerate(headers)))
        out.append("</tr></thead>")
        if rows:
            out.append("<tbody>")
            for row in rows:
                padded = (row + [""] * len(headers))[:len(headers)]
                out.append("<tr>" + "".join(
                    cell("td", v, n) for n, v in enumerate(padded)) + "</tr>")
            out.append("</tbody>")
        out.append("</table>")
        return "\n".join(out), i

    def _render_quote(self, lines: list[str], i: int,
                      end: int) -> tuple[str, int]:
        inner: list[str] = []
        while i < end and lines[i].strip().startswith(">"):
            text = lines[i].strip()[1:]
            inner.append(text[1:] if text.startswith(" ") else text)
            i += 1
        html, _ = self._render_blocks(inner, 0, len(inner))
        return f"<blockquote>\n{html}\n</blockquote>", i

    def _render_list(self, lines: list[str], i: int,
                     end: int) -> tuple[str, int]:
        first = _LIST_RE.match(lines[i])
        assert first is not None
        base_indent = len(first.group(1))
        ordered = first.group(2)[0].isdigit()
        tag = "ol" if ordered else "ul"
        items: list[str] = []
        while i < end:
            match = _LIST_RE.match(lines[i])
            if match is None or len(match.group(1)) != base_indent \
                    or match.group(2)[0].isdigit() != ordered:
                break
            content = match.group(3)
            i += 1
            # Nested lists and continuation lines belong to
            # this item while they are indented past it.
            nested: list[str] = []
            while i < end and lines[i].strip():
                nxt = _LIST_RE.match(lines[i])
                if nxt is not None and len(nxt.group(1)) > base_indent:
                    html, i = self._render_list(lines, i, end)
                    nested.append(html)
                    continue
                if nxt is not None and len(nxt.group(1)) == base_indent:
                    break
                if len(lines[i]) - len(lines[i].lstrip()) > base_indent:
                    content += " " + lines[i].strip()
                    i += 1
                    continue
                break
            items.append(self._render_item(content, nested))
        return f"<{tag}>\n" + "\n".join(items) + f"\n</{tag}>", i

    def _render_item(self, content: str, nested: list[str]) -> str:
        task = re.match(r"^\[([ xX])\]\s+(.*)$", content)
        if task:
            checked = " checked" if task.group(1).lower() == "x" else ""
            body = self.render_inline(task.group(2))
            html = (f'<li class="task-list-item">'
                    f'<input type="checkbox" disabled{checked}> {body}')
        else:
            html = f"<li>{self.render_inline(content)}"
        if nested:
            html += "\n" + "\n".join(nested)
        return html + "</li>"


def render_markdown(text: object, *,
                    link_resolver: LinkResolver | None = None,
                    reference_resolver: ReferenceResolver | None = None) -> str:
    """Render Markdown *text* to sanitised HTML through the
    S-010 seam. See the module docstring for the laws and the
    S-108/S-109 resolver seams."""
    if text is None:
        return ""
    renderer = _Renderer(link_resolver, reference_resolver)
    return renderer.render(str(text))
