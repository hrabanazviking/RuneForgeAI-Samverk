"""Issue templates (S-129).

Two kinds of template, one guided door into issues:

- **Markdown templates** — a name, a plain-words
  description of when to use it, a starting title, and a
  body the reporter edits. The guided form is the title
  box and the body box, prefilled.
- **YAML issue forms** — a form definition in the public
  issue-form shape (studied from public documentation,
  clean-room): `name`, `description`, `title`, `labels`,
  and a `body` list of fields — `markdown` notes, `input`
  and `textarea` boxes, `dropdown` pickers, `checkboxes`
  lists — each with a label in plain words, an optional
  description and placeholder, and `validations.required`
  where an answer is owed. A submission is assembled into
  an ordinary issue: the template's title (or the one the
  reporter gives), and a Markdown body of one headed
  section per answered field, checkboxes as a task list.

The YAML road is a **documented subset**, parsed here
with no dependency (the register stays empty): indentation
mappings and lists, plain / single- / double-quoted
scalars, inline `[a, b]` lists, `true`/`false`/`null`,
integers, and `|` / `>` block scalars. Tabs, anchors,
flow mappings, and multi-line plain scalars are refused
by name (`form_invalid`) rather than misread. Blank lines
inside the definition are ignored.

Three laws ride on top:

- **Meaning is text.** Every rendered field carries its
  label as words, required fields say "(required)" in
  words, and a template is chosen by name + description —
  never by colour or position alone.
- **Managing templates is a writer act** (S-054);
  reading and using them is a reader act, and a stranger
  to a private repository gets the uniform
  `repo_not_found`. CRUD is audited
  (`repo.issue_template.create` / `.update` / `.delete`).
- **Blank issues can be disallowed by owners.** The
  toggle is a writer act audited under the frozen
  `repo.settings.change` with the key named. While it is
  off, `IssueStore.create_issue` refuses a creation that
  did not come through a template
  (`blank_issue_not_allowed`) — the gate lives at the one
  creation seam, so no surface can walk around it. The
  toggle cannot be switched off while the repository has
  no templates: disallowing blank issues with no guided
  door would lock reporting entirely, so the store
  refuses (`no_templates`) and says why.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass

from .accounts import AccountStore, User
from .audit import AuditLog
from .escaping import escape_html_attr, escape_html_text
from .issues import Issue, IssueError, IssueStore, _validate_body, _validate_title
from .labels import LabelStore
from .markdown_pipeline import render_markdown
from .permissions import can_read, can_write
from .repositories import Repository, RepositoryStore

NAME_MAX = 50
DESCRIPTION_MAX = 200
SOURCE_MAX = 65536
LABELS_MAX = 10
FIELD_TYPES = frozenset(
    {"markdown", "input", "textarea", "dropdown", "checkboxes"})
_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")
_KEY_RE = re.compile(
    r"^([A-Za-z0-9_.\-]+|'[^']*'|\"[^\"]*\"):(?:\s+(.*))?$")


class TemplateError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass(frozen=True)
class FormField:
    id: str                       # '' for markdown notes
    type: str                     # one of FIELD_TYPES
    label: str = ""               # plain words ('' for markdown)
    description: str = ""
    placeholder: str = ""
    value: str = ""               # default, or the note's text
    options: tuple[str, ...] = ()
    option_required: tuple[bool, ...] = ()  # checkboxes, parallel
    required: bool = False


@dataclass(frozen=True)
class IssueTemplate:
    id: int
    repo_id: int
    name: str
    name_lower: str
    kind: str                     # 'markdown' | 'form'
    description: str
    title: str
    body: str                     # markdown kind: the body template
    fields: tuple[FormField, ...] = ()
    labels: tuple[str, ...] = ()
    source: str = ""              # form kind: the YAML as given
    created_at: int = 0
    updated_at: int = 0


# ------------------------------------------------------------------
# The YAML subset parser. Enough of YAML to say an issue
# form honestly, and a refusal for everything outside it.
# ------------------------------------------------------------------

class _Line:
    __slots__ = ("indent", "content", "number")

    def __init__(self, indent: int, content: str, number: int):
        self.indent = indent
        self.content = content
        self.number = number


def _yaml_lines(text: str) -> list[_Line]:
    lines: list[_Line] = []
    for number, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        if raw[:indent].find("\t") >= 0 or raw.lstrip()[:1] == "\t":
            raise TemplateError(
                "form_invalid",
                f"Line {number}: tabs cannot indent a form definition.")
        lines.append(_Line(indent, raw.strip(), number))
    return lines


def _parse_double_quoted(text: str, number: int) -> str:
    out: list[str] = []
    i = 1
    while i < len(text):
        ch = text[i]
        if ch == '"':
            if text[i + 1:].strip():
                raise TemplateError(
                    "form_invalid",
                    f"Line {number}: text after a closing quote.")
            return "".join(out)
        if ch == "\\":
            i += 1
            if i >= len(text):
                break
            esc = text[i]
            out.append({"n": "\n", "t": "\t", "r": "\r",
                        '"': '"', "\\": "\\", "/": "/"}.get(esc, esc))
        else:
            out.append(ch)
        i += 1
    raise TemplateError(
        "form_invalid", f"Line {number}: an unterminated quoted string.")


def _parse_scalar(text: str, number: int):
    text = text.strip()
    if text.startswith('"'):
        return _parse_double_quoted(text, number)
    if text.startswith("'"):
        if len(text) < 2 or not text.endswith("'"):
            raise TemplateError(
                "form_invalid",
                f"Line {number}: an unterminated quoted string.")
        return text[1:-1].replace("''", "'")
    if text.startswith("["):
        if not text.endswith("]"):
            raise TemplateError(
                "form_invalid", f"Line {number}: an unterminated list.")
        inner = text[1:-1].strip()
        if not inner:
            return []
        return [_parse_scalar(part, number)
                for part in _split_inline(inner, number)]
    if text.startswith("{"):
        raise TemplateError(
            "form_invalid",
            f"Line {number}: flow mappings are outside the form subset; "
            "indent the mapping instead.")
    if text.startswith(("&", "*", "!", "|", ">")) and len(text) <= 2:
        raise TemplateError(
            "form_invalid",
            f"Line {number}: anchors and tags are outside the form subset.")
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if lowered in ("null", "~"):
        return None
    if re.fullmatch(r"-?[0-9]+", text):
        return int(text)
    return text


def _split_inline(inner: str, number: int) -> list[str]:
    parts: list[str] = []
    depth = 0
    quote = ""
    start = 0
    i = 0
    while i < len(inner):
        ch = inner[i]
        if quote:
            if ch == quote:
                quote = ""
            elif ch == "\\" and quote == '"':
                i += 1
        elif ch in ("'", '"'):
            quote = ch
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
        elif ch == "," and depth == 0:
            parts.append(inner[start:i])
            start = i + 1
        i += 1
    if quote:
        raise TemplateError(
            "form_invalid", f"Line {number}: an unterminated quoted string.")
    parts.append(inner[start:])
    return parts


def _split_key(content: str, number: int):
    match = _KEY_RE.match(content)
    if match is None:
        return None
    key_text = match.group(1)
    if key_text.startswith(("'", '"')):
        key = _parse_scalar(key_text, number)
    else:
        key = key_text
    return str(key), match.group(2)


class _Parser:
    def __init__(self, lines: list[_Line]):
        self._lines = lines
        self._i = 0

    def parse(self):
        if not self._lines:
            raise TemplateError("form_invalid", "The form definition is empty.")
        value = self._block(self._lines[0].indent)
        if self._i != len(self._lines):
            line = self._lines[self._i]
            raise TemplateError(
                "form_invalid",
                f"Line {line.number}: indentation the parser cannot place.")
        return value

    def _peek(self) -> _Line | None:
        return self._lines[self._i] if self._i < len(self._lines) else None

    def _block(self, indent: int):
        line = self._peek()
        if line is None or line.indent < indent:
            return None
        if line.indent > indent:
            raise TemplateError(
                "form_invalid",
                f"Line {line.number}: unexpected indentation.")
        if line.content == "-" or line.content.startswith("- "):
            return self._list(indent)
        if _split_key(line.content, line.number) is not None:
            return self._map(indent)
        self._i += 1
        return _parse_scalar(line.content, line.number)

    def _map(self, indent: int) -> dict:
        out: dict = {}
        while True:
            line = self._peek()
            if line is None or line.indent != indent:
                break
            split = _split_key(line.content, line.number)
            if split is None:
                break
            key, rest = split
            if key in out:
                raise TemplateError(
                    "form_invalid", f"Line {line.number}: a repeated key {key!r}.")
            self._i += 1
            if rest is not None and rest.strip() in ("|", "|-", ">", ">-"):
                out[key] = self._block_scalar(indent, folded=rest.startswith(">"))
            elif rest is not None and rest.strip() != "":
                out[key] = _parse_scalar(rest, line.number)
            else:
                nxt = self._peek()
                if nxt is not None and nxt.indent > indent:
                    out[key] = self._block(nxt.indent)
                elif nxt is not None and nxt.indent == indent and (
                        nxt.content == "-" or nxt.content.startswith("- ")):
                    out[key] = self._list(indent)
                else:
                    out[key] = None
        return out

    def _block_scalar(self, parent_indent: int, *, folded: bool) -> str:
        parts: list[str] = []
        base: int | None = None
        while True:
            line = self._peek()
            if line is None or line.indent <= parent_indent:
                break
            if base is None:
                base = line.indent
            raw = " " * max(0, line.indent - base) + line.content
            parts.append(raw)
            self._i += 1
        return (" " if folded else "\n").join(parts)

    def _list(self, indent: int) -> list:
        out: list = []
        while True:
            line = self._peek()
            if line is None or line.indent != indent:
                break
            if not (line.content == "-" or line.content.startswith("- ")):
                break
            rest = line.content[1:].strip()
            if not rest:
                self._i += 1
                nxt = self._peek()
                out.append(self._block(nxt.indent)
                           if nxt is not None and nxt.indent > indent else None)
                continue
            if _split_key(rest, line.number) is not None:
                # The item is a mapping whose first key rides on
                # the dash line; re-seat it at its true indent and
                # let the map parser take the whole item.
                line.indent = indent + 2
                line.content = rest
                out.append(self._map(indent + 2))
                continue
            self._i += 1
            out.append(_parse_scalar(rest, line.number))
        return out


def parse_yaml_subset(text: object) -> object:
    """Parse the documented YAML subset (module docstring)."""
    if not isinstance(text, str):
        raise TemplateError("form_invalid", "A form definition is text.")
    if len(text) > SOURCE_MAX:
        raise TemplateError(
            "form_invalid",
            f"A form definition is at most {SOURCE_MAX} characters.")
    return _Parser(_yaml_lines(text)).parse()


# ------------------------------------------------------------------
# Form-definition validation: parsed YAML -> FormFields.
# ------------------------------------------------------------------

def _text(value: object, what: str) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        raise TemplateError("form_invalid", f"{what} must be text.")
    return value


def _field_from(item: object, seen_ids: set) -> FormField:
    if not isinstance(item, dict):
        raise TemplateError(
            "form_invalid", "Every form field is a mapping with a type.")
    ftype = item.get("type")
    if ftype not in FIELD_TYPES:
        raise TemplateError(
            "form_invalid",
            "A form field's type is one of: " + ", ".join(sorted(FIELD_TYPES))
            + ".")
    attrs = item.get("attributes") or {}
    if not isinstance(attrs, dict):
        raise TemplateError("form_invalid", "A field's attributes are a mapping.")
    validations = item.get("validations") or {}
    if not isinstance(validations, dict):
        raise TemplateError("form_invalid", "A field's validations are a mapping.")
    required = validations.get("required", False)
    if not isinstance(required, bool):
        raise TemplateError(
            "form_invalid", "validations.required is true or false.")
    if ftype == "markdown":
        value = _text(attrs.get("value"), "A markdown note's value")
        if not value.strip():
            raise TemplateError(
                "form_invalid", "A markdown field needs its text (attributes.value).")
        return FormField(id="", type="markdown", value=value)
    fid = item.get("id")
    if not isinstance(fid, str) or not _ID_RE.match(fid):
        raise TemplateError(
            "form_invalid",
            "Every field needs an id: a letter, then letters, digits, "
            "'-' or '_'.")
    if fid in seen_ids:
        raise TemplateError("form_invalid", f"A repeated field id {fid!r}.")
    seen_ids.add(fid)
    label = _text(attrs.get("label"), "A field's label").strip()
    if not label:
        raise TemplateError(
            "form_invalid",
            f"Field {fid!r} needs a label in plain words (attributes.label).")
    common = dict(
        id=fid, type=ftype, label=label,
        description=_text(attrs.get("description"), "A description"),
        required=required)
    if ftype in ("input", "textarea"):
        return FormField(
            placeholder=_text(attrs.get("placeholder"), "A placeholder"),
            value=_text(attrs.get("value"), "A default value"), **common)
    if ftype == "dropdown":
        options = attrs.get("options")
        if not isinstance(options, list) or not options:
            raise TemplateError(
                "form_invalid",
                f"Dropdown {fid!r} needs at least one option.")
        texts = tuple(_text(o, "A dropdown option").strip() for o in options)
        if any(not t for t in texts) or len(set(texts)) != len(texts):
            raise TemplateError(
                "form_invalid",
                f"Dropdown {fid!r} options are distinct non-empty texts.")
        return FormField(options=texts, **common)
    # checkboxes
    options = attrs.get("options")
    if not isinstance(options, list) or not options:
        raise TemplateError(
            "form_invalid",
            f"Checkboxes {fid!r} need at least one option.")
    labels: list[str] = []
    flags: list[bool] = []
    for option in options:
        if isinstance(option, str):
            labels.append(option.strip())
            flags.append(False)
        elif isinstance(option, dict):
            labels.append(_text(option.get("label"), "A checkbox label").strip())
            flag = option.get("required", False)
            if not isinstance(flag, bool):
                raise TemplateError(
                    "form_invalid", "A checkbox option's required is true or false.")
            flags.append(flag)
        else:
            raise TemplateError(
                "form_invalid",
                "A checkbox option is a label or a mapping with a label.")
    if any(not t for t in labels) or len(set(labels)) != len(labels):
        raise TemplateError(
            "form_invalid",
            f"Checkboxes {fid!r} options are distinct non-empty labels.")
    return FormField(options=tuple(labels),
                     option_required=tuple(flags), **common)


def _labels_from(value: object) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        raw = [part.strip() for part in value.split(",")]
    elif isinstance(value, list):
        raw = [_text(v, "A label name").strip() for v in value]
    else:
        raise TemplateError("form_invalid", "labels is a list of label names.")
    out = [r for r in raw if r]
    if len(out) > LABELS_MAX:
        raise TemplateError(
            "form_invalid", f"A template names at most {LABELS_MAX} labels.")
    for name in out:
        _validate_template_label(name)
    return tuple(out)


def _validate_template_label(name: str) -> None:
    if len(name) > NAME_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in name):
        raise TemplateError(
            "form_invalid", f"That is not a label name: {name!r}.")


def fields_from_form(parsed: object) -> tuple[str, str, str, tuple[str, ...], tuple[FormField, ...]]:
    """(name, description, title, labels, fields) from a parsed
    form definition, fully validated."""
    if not isinstance(parsed, dict):
        raise TemplateError(
            "form_invalid", "A form definition is a mapping with a name.")
    name = _validate_name(parsed.get("name"))
    description = _validate_description(
        parsed.get("description", parsed.get("about")))
    title_raw = _text(parsed.get("title"), "A form's title")
    try:
        title = _validate_title(title_raw) if title_raw.strip() else ""
    except IssueError:
        raise TemplateError(
            "form_invalid", "A form's title is a valid issue title.") from None
    labels = _labels_from(parsed.get("labels"))
    body = parsed.get("body") or []
    if not isinstance(body, list):
        raise TemplateError("form_invalid", "A form's body is a list of fields.")
    seen: set = set()
    fields = tuple(_field_from(item, seen) for item in body)
    return name, description, title, labels, fields


# ------------------------------------------------------------------
# Validation shared by both kinds.
# ------------------------------------------------------------------

def _validate_name(name: object) -> str:
    if not isinstance(name, str) or not name.strip():
        raise TemplateError(
            "template_name_required",
            "A template needs a name — it is chosen by its name "
            "and description, never by position alone.")
    text = name.strip()
    if len(text) > NAME_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise TemplateError(
            "template_name_invalid",
            f"Template names are at most {NAME_MAX} characters of "
            "plain text.")
    return text


def _validate_description(description: object) -> str:
    if description is None:
        return ""
    if not isinstance(description, str):
        raise TemplateError(
            "description_invalid", "A description must be text.")
    text = description.strip()
    if len(text) > DESCRIPTION_MAX or any(
            ord(c) < 0x20 or ord(c) == 0x7F for c in text):
        raise TemplateError(
            "description_invalid",
            f"Descriptions are at most {DESCRIPTION_MAX} characters "
            "of plain text.")
    return text


def _validate_title_or_empty(title: object) -> str:
    if title is None:
        return ""
    try:
        return _validate_title(title) if str(title).strip() else ""
    except IssueError as exc:
        raise TemplateError(exc.reason, str(exc)) from None


def _validate_labels(labels: object) -> tuple[str, ...]:
    if labels is None:
        return ()
    if isinstance(labels, str):
        return _labels_from(labels)
    if isinstance(labels, (list, tuple)):
        out = tuple(str(v).strip() for v in labels if str(v).strip())
        if len(out) > LABELS_MAX:
            raise TemplateError(
                "labels_invalid", f"A template names at most {LABELS_MAX} labels.")
        for name in out:
            _validate_template_label(name)
        return out
    raise TemplateError("labels_invalid", "Labels are a list of names.")


def _field_to_json(f: FormField) -> dict:
    return {"id": f.id, "type": f.type, "label": f.label,
            "description": f.description, "placeholder": f.placeholder,
            "value": f.value, "options": list(f.options),
            "option_required": list(f.option_required),
            "required": f.required}


def _field_from_json(data: dict) -> FormField:
    return FormField(
        id=data["id"], type=data["type"], label=data.get("label", ""),
        description=data.get("description", ""),
        placeholder=data.get("placeholder", ""),
        value=data.get("value", ""),
        options=tuple(data.get("options", ())),
        option_required=tuple(data.get("option_required", ())),
        required=bool(data.get("required", False)))


def _row_to_template(row: sqlite3.Row) -> IssueTemplate:
    fields = tuple(_field_from_json(d)
                   for d in json.loads(row["fields_json"]))
    return IssueTemplate(
        id=row["id"], repo_id=row["repo_id"], name=row["name"],
        name_lower=row["name_lower"], kind=row["kind"],
        description=row["description"], title=row["title"],
        body=row["body"], fields=fields,
        labels=tuple(json.loads(row["labels_json"])),
        source=row["source"], created_at=row["created_at"],
        updated_at=row["updated_at"])


# ------------------------------------------------------------------
# Assembly: a guided submission becomes an ordinary issue.
# ------------------------------------------------------------------

def assemble_body(template: IssueTemplate, values: object) -> str:
    """The Markdown body a submission produces. Refusals name
    the field by its label, in plain words."""
    if not isinstance(values, dict):
        raise TemplateError(
            "values_invalid", "A submission is a mapping of field answers.")
    if template.kind == "markdown":
        unknown = set(values) - {"body"}
        if unknown:
            raise TemplateError(
                "field_unknown",
                "This template takes only a body; unknown fields: "
                + ", ".join(sorted(str(u) for u in unknown)) + ".")
        body = values.get("body", template.body)
        try:
            return _validate_body(body)
        except IssueError as exc:
            raise TemplateError(exc.reason, str(exc)) from None
    known = {f.id for f in template.fields if f.id}
    unknown = set(values) - known
    if unknown:
        raise TemplateError(
            "field_unknown",
            "Unknown fields: " + ", ".join(sorted(str(u) for u in unknown))
            + ".")
    sections: list[str] = []
    for f in template.fields:
        if f.type == "markdown":
            sections.append(f.value.strip())
            continue
        raw = values.get(f.id)
        if f.type in ("input", "textarea"):
            if raw is None:
                raw = f.value
            if not isinstance(raw, str):
                raise TemplateError(
                    "field_invalid", f"{f.label} must be text.")
            text = raw.strip()
            if f.required and not text:
                raise TemplateError(
                    "field_required", f"{f.label} is required.")
            if text:
                sections.append(f"### {f.label}\n\n{text}")
        elif f.type == "dropdown":
            if raw is None or (isinstance(raw, str) and not raw.strip()):
                if f.required:
                    raise TemplateError(
                        "field_required", f"{f.label} is required.")
                continue
            if not isinstance(raw, str) or raw not in f.options:
                raise TemplateError(
                    "field_option_invalid",
                    f"{f.label} must be one of: " + ", ".join(f.options) + ".")
            sections.append(f"### {f.label}\n\n{raw}")
        elif f.type == "checkboxes":
            checked = _checked_labels(f, raw)
            for label, needed in zip(f.options, f.option_required):
                if needed and label not in checked:
                    raise TemplateError(
                        "field_required",
                        f"{f.label}: '{label}' must be checked.")
            lines = [f"### {f.label}", ""]
            for label in f.options:
                mark = "x" if label in checked else " "
                lines.append(f"- [{mark}] {label}")
            sections.append("\n".join(lines))
    body = "\n\n".join(s for s in sections if s)
    try:
        return _validate_body(body)
    except IssueError as exc:
        raise TemplateError(exc.reason, str(exc)) from None


def _checked_labels(f: FormField, raw: object) -> set:
    if raw is None:
        return set()
    if isinstance(raw, dict):
        checked = {k for k, v in raw.items() if v}
    elif isinstance(raw, (list, tuple, set)):
        checked = set(raw)
    else:
        raise TemplateError(
            "field_invalid", f"{f.label} must be a list of checked options.")
    unknown = checked - set(f.options)
    if unknown:
        raise TemplateError(
            "field_option_invalid",
            f"{f.label} has no option named "
            + ", ".join(sorted(str(u) for u in unknown)) + ".")
    return checked


def compose_issue(template: IssueTemplate, values: object,
                  title: object = None) -> tuple[str, str]:
    """(title, body) for a submission: the reporter's title
    wins; otherwise the template's starting title."""
    if title is None or (isinstance(title, str) and not title.strip()):
        title = template.title
    try:
        title_ok = _validate_title(title)
    except IssueError as exc:
        raise TemplateError(exc.reason, str(exc)) from None
    return title_ok, assemble_body(template, values)


# ------------------------------------------------------------------
# Rendering: the guided forms themselves. No script, no
# inline style; every control labelled in words.
# ------------------------------------------------------------------

def render_choice_list(templates: list[IssueTemplate],
                       *, allow_blank: bool = True) -> str:
    """The chooser: each template by name + description as
    text, and the blank road stated honestly either way."""
    parts = ['<ul class="issue-templates">']
    for t in templates:
        parts.append(
            '<li><a href="?template=' + escape_html_attr(t.name_lower)
            + '">' + escape_html_text(t.name) + "</a> — "
            + escape_html_text(t.description) + "</li>")
    parts.append("</ul>")
    if allow_blank:
        parts.append(
            '<p><a href="?template=blank">Blank issue</a> — start '
            "from an empty title and body.</p>")
    else:
        parts.append(
            "<p>Blank issues are turned off for this repository: "
            "please choose a template above.</p>")
    return "\n".join(parts)


def render_guided_form(template: IssueTemplate, *,
                       action: str = "") -> str:
    """The guided form for one template, as HTML."""
    parts = [
        '<form method="post" action="' + escape_html_attr(action)
        + '" class="issue-template-form">',
        "<h2>" + escape_html_text(template.name) + "</h2>",
    ]
    if template.description:
        parts.append("<p>" + escape_html_text(template.description) + "</p>")
    parts.append(
        '<p><label for="issue-title">Title (required)</label><br>'
        '<input id="issue-title" name="title" type="text" required value="'
        + escape_html_attr(template.title) + '"></p>')
    if template.kind == "markdown":
        parts.append(
            '<p><label for="issue-body">Body</label><br>'
            '<textarea id="issue-body" name="body" rows="12">'
            + escape_html_text(template.body) + "</textarea></p>")
    else:
        for f in template.fields:
            parts.append(_render_field(f))
    parts.append('<p><button type="submit">Submit new issue</button></p>')
    parts.append("</form>")
    return "\n".join(parts)


def _render_field(f: FormField) -> str:
    if f.type == "markdown":
        return ('<div class="form-note">\n' + render_markdown(f.value)
                + "\n</div>")
    fid = escape_html_attr(f.id)
    required_word = " (required)" if f.required else ""
    label = ('<label for="field-' + fid + '">'
             + escape_html_text(f.label) + required_word + "</label>")
    description = ("<p>" + escape_html_text(f.description) + "</p>"
                   if f.description else "")
    required_attr = " required" if f.required else ""
    if f.type == "input":
        control = (
            '<input id="field-' + fid + '" name="' + fid + '" type="text"'
            + required_attr + ' value="' + escape_html_attr(f.value)
            + '" placeholder="' + escape_html_attr(f.placeholder) + '">')
        return "<p>" + label + "<br>" + control + "</p>" + description
    if f.type == "textarea":
        control = (
            '<textarea id="field-' + fid + '" name="' + fid + '" rows="8"'
            + required_attr + ' placeholder="'
            + escape_html_attr(f.placeholder) + '">'
            + escape_html_text(f.value) + "</textarea>")
        return "<p>" + label + "<br>" + control + "</p>" + description
    if f.type == "dropdown":
        options = "".join(
            '<option value="' + escape_html_attr(o) + '">'
            + escape_html_text(o) + "</option>" for o in f.options)
        control = ('<select id="field-' + fid + '" name="' + fid + '"'
                   + required_attr + ">" + options + "</select>")
        return "<p>" + label + "<br>" + control + "</p>" + description
    # checkboxes
    boxes = []
    for option, needed in zip(f.options, f.option_required):
        word = " (required)" if needed else ""
        boxes.append(
            '<label><input type="checkbox" name="' + fid + '" value="'
            + escape_html_attr(option) + '"> '
            + escape_html_text(option) + word + "</label>")
    return ("<fieldset><legend>" + escape_html_text(f.label)
            + "</legend>" + description + "<br>".join(boxes) + "</fieldset>")


# ------------------------------------------------------------------
# The store.
# ------------------------------------------------------------------

class IssueTemplateStore:
    def __init__(
        self,
        conn: sqlite3.Connection,
        repositories: RepositoryStore,
        accounts: AccountStore,
        issues: IssueStore | None = None,
        labels: LabelStore | None = None,
        audit: AuditLog | None = None,
        time_fn: Callable[[], float] = time.time,
    ):
        self._conn = conn
        self._repos = repositories
        self._accounts = accounts
        self._issues = issues
        self._labels = labels
        self._audit = audit
        self._now = time_fn

    # -- guards ------------------------------------------------------
    def _repo_for_read(self, viewer: User | None, owner: object,
                       repo: object) -> Repository:
        current = self._repos.get_repository(owner, repo)
        if current is None or not can_read(viewer, current):
            raise TemplateError("repo_not_found", "No such repository.")
        return current

    def _repo_for_write(self, actor: User, owner: object,
                        repo: object) -> Repository:
        current = self._repo_for_read(actor, owner, repo)
        if not can_write(actor, current):
            raise TemplateError(
                "permission_denied",
                "Only a repository writer can manage issue templates.")
        return current

    # -- CRUD ----------------------------------------------------------
    def create_markdown_template(
            self, actor: User, owner: object, repo: object, name: object,
            *, description: object = "", title: object = "",
            body: object = "", labels: object = None,
            source_ip: str | None = None) -> IssueTemplate:
        current = self._repo_for_write(actor, owner, repo)
        name_ok = _validate_name(name)
        desc = _validate_description(description)
        title_ok = _validate_title_or_empty(title)
        if not isinstance(body, str):
            raise TemplateError("template_body_invalid", "A body must be text.")
        try:
            body_ok = _validate_body(body)
        except IssueError as exc:
            raise TemplateError(exc.reason, str(exc)) from None
        if not body_ok.strip():
            raise TemplateError(
                "template_body_required",
                "A Markdown template needs a body to start from.")
        labels_ok = _validate_labels(labels)
        return self._insert(actor, current, name_ok, "markdown", desc,
                            title_ok, body_ok, (), labels_ok, "", source_ip)

    def create_form_template(
            self, actor: User, owner: object, repo: object,
            source: object, *, source_ip: str | None = None
    ) -> IssueTemplate:
        current = self._repo_for_write(actor, owner, repo)
        if not isinstance(source, str):
            raise TemplateError("form_invalid", "A form definition is text.")
        parsed = parse_yaml_subset(source)
        name, desc, title, labels, fields = fields_from_form(parsed)
        return self._insert(actor, current, name, "form", desc, title,
                            "", fields, labels, source, source_ip)

    def _insert(self, actor: User, current: Repository, name: str,
                kind: str, description: str, title: str, body: str,
                fields: tuple[FormField, ...], labels: tuple[str, ...],
                source: str, source_ip: str | None) -> IssueTemplate:
        now = int(self._now())
        with self._conn:  # commits before the answer
            try:
                cur = self._conn.execute(
                    "INSERT INTO issue_templates (repo_id, name,"
                    " name_lower, kind, description, title, body,"
                    " fields_json, labels_json, source, created_at,"
                    " updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?,"
                    " ?, ?)",
                    (current.id, name, name.lower(), kind, description,
                     title, body,
                     json.dumps([_field_to_json(f) for f in fields]),
                     json.dumps(list(labels)), source, now, now))
            except sqlite3.IntegrityError:
                raise TemplateError(
                    "template_taken",
                    f"A template named {name!r} already exists in "
                    "this repository.") from None
        template = self._by_id(int(cur.lastrowid))
        assert template is not None
        self._emit(actor, "repo.issue_template.create", current,
                   {"template": template.name, "kind": kind}, source_ip)
        return template

    def get_template(self, viewer: User | None, owner: object,
                     repo: object, name: object) -> IssueTemplate:
        current = self._repo_for_read(viewer, owner, repo)
        template = self._by_name(current.id, name)
        if template is None:
            raise TemplateError("template_not_found", "No such template.")
        return template

    def list_templates(self, viewer: User | None, owner: object,
                       repo: object) -> list[IssueTemplate]:
        current = self._repo_for_read(viewer, owner, repo)
        rows = self._conn.execute(
            "SELECT * FROM issue_templates WHERE repo_id = ?"
            " ORDER BY name_lower", (current.id,)).fetchall()
        return [_row_to_template(r) for r in rows]

    def update_template(
            self, actor: User, owner: object, repo: object, name: object,
            *, new_name: object = None, description: object = None,
            title: object = None, body: object = None,
            labels: object = None, source: object = None,
            source_ip: str | None = None) -> IssueTemplate:
        current = self._repo_for_write(actor, owner, repo)
        template = self._by_name(current.id, name)
        if template is None:
            raise TemplateError("template_not_found", "No such template.")
        kind, fields, source_text = template.kind, template.fields, template.source
        body_text = template.body
        name_ok = (template.name if new_name is None
                   else _validate_name(new_name))
        desc = (template.description if description is None
                else _validate_description(description))
        title_ok = (template.title if title is None
                    else _validate_title_or_empty(title))
        labels_ok = (template.labels if labels is None
                     else _validate_labels(labels))
        if source is not None:
            if template.kind != "form":
                raise TemplateError(
                    "form_invalid",
                    "Only a YAML form template can be replaced from "
                    "a form definition.")
            parsed = parse_yaml_subset(source)
            p_name, p_desc, p_title, p_labels, fields = fields_from_form(parsed)
            if new_name is None:
                name_ok = p_name
            if description is None:
                desc = p_desc
            if title is None:
                title_ok = p_title
            if labels is None:
                labels_ok = p_labels
            source_text = str(source)
        if body is not None:
            if template.kind != "markdown":
                raise TemplateError(
                    "template_body_invalid",
                    "A YAML form's body comes from its fields, not a "
                    "body text.")
            try:
                body_text = _validate_body(body)
            except IssueError as exc:
                raise TemplateError(exc.reason, str(exc)) from None
            if not body_text.strip():
                raise TemplateError(
                    "template_body_required",
                    "A Markdown template needs a body to start from.")
        now = int(self._now())
        with self._conn:
            try:
                self._conn.execute(
                    "UPDATE issue_templates SET name = ?, name_lower = ?,"
                    " description = ?, title = ?, body = ?,"
                    " fields_json = ?, labels_json = ?, source = ?,"
                    " updated_at = ? WHERE id = ?",
                    (name_ok, name_ok.lower(), desc, title_ok, body_text,
                     json.dumps([_field_to_json(f) for f in fields]),
                     json.dumps(list(labels_ok)), source_text, now,
                     template.id))
            except sqlite3.IntegrityError:
                raise TemplateError(
                    "template_taken",
                    f"A template named {name_ok!r} already exists in "
                    "this repository.") from None
        updated = self._by_id(template.id)
        assert updated is not None
        self._emit(actor, "repo.issue_template.update", current,
                   {"template": updated.name, "kind": kind}, source_ip)
        return updated

    def delete_template(self, actor: User, owner: object, repo: object,
                        name: object, *, source_ip: str | None = None
                        ) -> IssueTemplate:
        current = self._repo_for_write(actor, owner, repo)
        template = self._by_name(current.id, name)
        if template is None:
            raise TemplateError("template_not_found", "No such template.")
        with self._conn:
            self._conn.execute(
                "DELETE FROM issue_templates WHERE id = ?", (template.id,))
        self._emit(actor, "repo.issue_template.delete", current,
                   {"template": template.name, "kind": template.kind},
                   source_ip)
        return template

    # -- the blank-issue toggle -----------------------------------------
    def allow_blank_issues(self, viewer: User | None, owner: object,
                           repo: object) -> bool:
        current = self._repo_for_read(viewer, owner, repo)
        row = self._conn.execute(
            "SELECT allow_blank_issues FROM repo_issue_options"
            " WHERE repo_id = ?", (current.id,)).fetchone()
        return True if row is None else bool(row["allow_blank_issues"])

    def set_allow_blank_issues(self, actor: User, owner: object,
                               repo: object, allow: object,
                               *, source_ip: str | None = None) -> bool:
        current = self._repo_for_write(actor, owner, repo)
        if not isinstance(allow, bool):
            raise TemplateError(
                "setting_invalid", "allow_blank_issues is true or false.")
        if not allow:
            count = self._conn.execute(
                "SELECT COUNT(*) AS n FROM issue_templates"
                " WHERE repo_id = ?", (current.id,)).fetchone()["n"]
            if not count:
                raise TemplateError(
                    "no_templates",
                    "Add an issue template first: turning blank issues "
                    "off with no template to use would leave no way to "
                    "report an issue at all.")
        before = self.allow_blank_issues(actor, owner, repo)
        with self._conn:
            self._conn.execute(
                "INSERT INTO repo_issue_options (repo_id,"
                " allow_blank_issues) VALUES (?, ?)"
                " ON CONFLICT (repo_id) DO UPDATE"
                " SET allow_blank_issues = excluded.allow_blank_issues",
                (current.id, 1 if allow else 0))
        if self._audit is not None and before != allow:
            self._audit.append(
                actor_kind="user", actor_id=actor.id,
                action="repo.settings.change", target_kind="repo",
                target_id=current.full_name, outcome="success",
                source_ip=source_ip,
                detail={"key": "allow_blank_issues",
                        "from": before, "to": allow})
        return allow

    # -- using a template ---------------------------------------------------
    def create_issue_from_template(
            self, actor: User, owner: object, repo: object,
            template_name: object, values: object,
            title: object = None, *, source_ip: str | None = None
    ) -> Issue:
        if self._issues is None:
            raise TemplateError(
                "issues_unavailable", "No issue store is wired.")
        template = self.get_template(actor, owner, repo, template_name)
        title_ok, body_ok = compose_issue(template, values, title)
        if template.labels and self._labels is not None:
            # Checked before the issue exists, so a template
            # naming a deleted label fails whole, not half-done.
            for label in template.labels:
                self._labels.get_label(actor, owner, repo, label)
        issue = self._issues.create_issue(
            actor, owner, repo, title_ok, body_ok,
            via_template=True, source_ip=source_ip)
        if template.labels and self._labels is not None:
            for label in template.labels:
                self._labels.add_to_issue(
                    actor, owner, repo, issue.number, label,
                    source_ip=source_ip)
        return issue

    # -- internals ------------------------------------------------------------
    def _by_id(self, template_id: int) -> IssueTemplate | None:
        row = self._conn.execute(
            "SELECT * FROM issue_templates WHERE id = ?",
            (template_id,)).fetchone()
        return _row_to_template(row) if row else None

    def _by_name(self, repo_id: int, name: object) -> IssueTemplate | None:
        if not isinstance(name, str) or not name.strip():
            return None
        row = self._conn.execute(
            "SELECT * FROM issue_templates WHERE repo_id = ?"
            " AND name_lower = ?",
            (repo_id, name.strip().lower())).fetchone()
        return _row_to_template(row) if row else None

    def _emit(self, actor: User, action: str, current: Repository,
              detail: dict, source_ip: str | None) -> None:
        if self._audit is not None:
            self._audit.append(
                actor_kind="user", actor_id=actor.id, action=action,
                target_kind="repo", target_id=current.full_name,
                outcome="success", source_ip=source_ip, detail=detail)
