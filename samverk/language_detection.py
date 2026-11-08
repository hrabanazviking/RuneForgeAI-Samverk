"""Language detection (S-218).

For code filters and highlighting (S-099) from one
shared table — Part X's census slice. Before this
slice the language table lived as a seed inside
S-099's blob view: S-207's indexer imported its
detect_language, S-208's filters matched whatever
string the indexer recorded, and the highlighter
read the same names — one table in fact, but owned
by a view. This slice gives the census its own home
and grows it to the fuller table S-099's docstring
promised S-218 would own.

- **One shared table, single source of truth.**
  LANGUAGE_BY_EXTENSION, LANGUAGE_BY_FILENAME and
  LANGUAGE_BY_SHEBANG are defined HERE and nowhere
  else. S-099's blob view re-exports them and
  delegates its detect_language to this module;
  S-207's indexer imports detection from here
  directly; S-208's language filter canonicalises
  through here. There is no second divergent table
  to drift: the battery pins object identity for
  the re-export and proves indexer, search and
  highlighting all answer from this census.
- **Detection precedence, never guessed.**
  detect_language answers in a fixed order: an
  exact well-known filename first (Makefile,
  Dockerfile, CMakeLists.txt, ...), then the
  file extension, then the shebang line of an
  extensionless (or unrecognised) file, then the
  honest unknown. The unknown is UNKNOWN_LANGUAGE
  (\"text\") — the same plain-text answer S-099
  has always given — never a silent guess at a
  real language. A name with no dot, a dotfile
  with no stem, empty data and a non-shebang first
  line all land on the unknown, in the open.
- **Shebangs are parsed, not substring-matched.**
  The interpreter is the basename of the shebang's
  program (skipping a leading env, and env's own
  options and assignments), with any version
  suffix stripped (python3.11 -> python, node18
  -> node), then looked up in the one shebang
  table. An interpreter the table does not name
  answers the unknown, exactly like an unknown
  extension.
- **Filters speak aliases, records speak canon.**
  canonical_language maps a filter word — case,
  surrounding space and the common aliases
  (py, js, ts, golang, c++, c#, sh, yml, md, ...)
  — to the one canonical name the table records,
  or returns None for a word that names no known
  language. language_matches is the filter law
  S-208 executes: an empty filter passes
  everything; a filter naming a known language
  matches exactly its canonical recorded name; a
  filter naming NO known language matches nothing
  (fail closed — an unknown filter word is a
  refusal-shaped empty result, never a pass-all
  and never a substring hunt).
- **The census is data, pinned as data.**
  all_languages is the sorted set of every name
  the three tables can produce plus the unknown;
  every extension maps to a census language, every
  filename and shebang answer is a census language,
  and no extension is claimed by two languages.
  Adding a language is adding table rows — the
  battery re-derives the census from the tables,
  so a row that escapes the census fails green.
- **Reads only.** Detection is a pure function of
  a name and bytes: it writes nothing, audits
  nothing, and needs no store. No migration (schema
  stays 84), no new taxonomy event (123 stand:
  31 auth / 79 repo / 13 admin).
"""
from __future__ import annotations

import re

from .escaping import escape_html_text

__all__ = [
    "LANGUAGE_ALIASES", "LANGUAGE_BY_EXTENSION",
    "LANGUAGE_BY_FILENAME", "LANGUAGE_BY_SHEBANG",
    "UNKNOWN_LANGUAGE", "LanguageDetectionError",
    "all_languages", "canonical_language",
    "detect_language", "language_for_extension",
    "language_for_filename", "language_for_shebang",
    "language_matches", "parse_shebang_interpreter",
    "render_language_page",
]

UNKNOWN_LANGUAGE = "text"

# ------------------------------------------------------------------
# The one shared census: extension -> canonical language
# ------------------------------------------------------------------

LANGUAGE_BY_EXTENSION = {
    ".py": "python", ".pyi": "python", ".pyw": "python",
    ".js": "javascript", ".mjs": "javascript", ".cjs": "javascript",
    ".jsx": "javascript",
    ".ts": "typescript", ".tsx": "typescript",
    ".mts": "typescript", ".cts": "typescript",
    ".go": "go", ".rs": "rust",
    ".java": "java", ".kt": "kotlin", ".kts": "kotlin",
    ".scala": "scala", ".sc": "scala",
    ".c": "c", ".h": "c",
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".hpp": "cpp",
    ".hh": "cpp", ".hxx": "cpp",
    ".cs": "csharp", ".rb": "ruby", ".php": "php",
    ".sh": "shell", ".bash": "shell", ".zsh": "shell",
    ".ksh": "shell", ".fish": "shell",
    ".sql": "sql", ".html": "html", ".htm": "html",
    ".css": "css", ".scss": "css", ".sass": "css", ".less": "css",
    ".json": "json", ".jsonc": "json",
    ".toml": "toml", ".yaml": "yaml", ".yml": "yaml",
    ".md": "markdown", ".markdown": "markdown",
    ".lua": "lua", ".pl": "perl", ".pm": "perl", ".php3": "php",
    ".swift": "swift", ".hs": "haskell", ".lhs": "haskell",
    ".ml": "ocaml", ".mli": "ocaml",
    ".ex": "elixir", ".exs": "elixir", ".erl": "erlang",
    ".hrl": "erlang", ".clj": "clojure", ".cljs": "clojure",
    ".groovy": "groovy", ".gradle": "groovy",
    ".dart": "dart", ".vue": "vue", ".xml": "xml",
    ".svg": "xml", ".ini": "ini", ".cfg": "ini", ".conf": "ini",
    ".csv": "csv", ".tsv": "csv", ".txt": "text",
    ".rst": "restructuredtext", ".tex": "latex",
    ".r": "r", ".jl": "julia", ".vim": "vimscript",
    ".el": "elisp", ".lisp": "lisp", ".scm": "scheme",
    ".asm": "assembly", ".s": "assembly",
    ".mk": "make", ".cmake": "cmake", ".proto": "protobuf",
    ".graphql": "graphql", ".gql": "graphql",
}

# Exact well-known filenames (lower-cased basename) -> language.
LANGUAGE_BY_FILENAME = {
    "makefile": "make", "gnumakefile": "make",
    "dockerfile": "dockerfile", "cmakelists.txt": "cmake",
    "rakefile": "ruby", "gemfile": "ruby", "vagrantfile": "ruby",
    "jenkinsfile": "groovy", "brewfile": "ruby",
}

# Shebang interpreter basename (version suffix stripped) -> language.
LANGUAGE_BY_SHEBANG = {
    "python": "python", "pythonw": "python",
    "node": "javascript", "nodejs": "javascript",
    "deno": "typescript", "bun": "javascript",
    "ruby": "ruby", "perl": "perl", "php": "php",
    "sh": "shell", "bash": "shell", "zsh": "shell",
    "ksh": "shell", "dash": "shell", "fish": "shell",
    "lua": "lua", "groovy": "groovy", "osascript": "applescript",
    "pwsh": "powershell", "powershell": "powershell",
    "rscript": "r", "julia": "julia", "swift": "swift",
    "go": "go", "ts-node": "typescript",
}

# Filter words -> canonical language (aliases; keys lower-cased).
LANGUAGE_ALIASES = {
    "py": "python", "python3": "python",
    "js": "javascript", "node": "javascript", "nodejs": "javascript",
    "ts": "typescript", "golang": "go",
    "c++": "cpp", "cplusplus": "cpp", "cxx": "cpp",
    "c#": "csharp", "cs": "csharp", "f#": "fsharp",
    "sh": "shell", "bash": "shell", "zsh": "shell",
    "yml": "yaml", "md": "markdown", "rb": "ruby",
    "rs": "rust", "kt": "kotlin", "ml": "ocaml",
    "hs": "haskell", "ex": "elixir", "erl": "erlang",
    "clj": "clojure", "pl": "perl", "svg": "xml",
    "plain": "text", "plaintext": "text", "txt": "text",
    "rst": "restructuredtext", "tex": "latex",
}


class LanguageDetectionError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def all_languages() -> tuple[str, ...]:
    """Every canonical language name the shared census
    can produce, sorted, the unknown included. Re-derived
    from the tables on every call, so the census can
    never disagree with the tables it describes."""
    names = {UNKNOWN_LANGUAGE}
    names.update(LANGUAGE_BY_EXTENSION.values())
    names.update(LANGUAGE_BY_FILENAME.values())
    names.update(LANGUAGE_BY_SHEBANG.values())
    names.update(LANGUAGE_ALIASES.values())
    return tuple(sorted(names))


def _basename(filename: object) -> str:
    if not isinstance(filename, str):
        return ""
    return filename.rsplit("/", 1)[-1].lower()


def language_for_filename(filename: object) -> str | None:
    """The language an exact well-known filename names,
    or None when the filename is not in the census."""
    return LANGUAGE_BY_FILENAME.get(_basename(filename))


def language_for_extension(filename: object) -> str | None:
    """The language a filename's extension names, or
    None. A leading-dot dotfile has no extension: the
    dot must follow at least one stem character."""
    name = _basename(filename)
    dot = name.rfind(".")
    if dot <= 0:
        return None
    return LANGUAGE_BY_EXTENSION.get(name[dot:])


_VERSION_SUFFIX_RE = re.compile(r"[0-9][0-9.]*$")


def parse_shebang_interpreter(data: object) -> str | None:
    """The interpreter basename a byte string's shebang
    line names (version suffix stripped, env unwrapped),
    or None when there is no usable shebang. Pure parsing:
    an interpreter is reported as written even when the
    census cannot name its language."""
    if not isinstance(data, (bytes, bytearray)) or not data:
        return None
    first = bytes(data).split(b"\n", 1)[0].decode("utf-8", "replace").strip()
    if not first.startswith("#!"):
        return None
    words = first[2:].split()
    if not words:
        return None
    program = words[0].rsplit("/", 1)[-1]
    rest = words[1:]
    if program == "env":
        program = ""
        for word in rest:
            if word.startswith("-") or "=" in word:
                continue
            program = word.rsplit("/", 1)[-1]
            break
        if not program:
            return None
    cleaned = _VERSION_SUFFIX_RE.sub("", program)
    return cleaned or program


def language_for_shebang(data: object) -> str | None:
    """The language a byte string's shebang names, or
    None when there is no shebang or its interpreter is
    not in the census."""
    interpreter = parse_shebang_interpreter(data)
    if interpreter is None:
        return None
    return LANGUAGE_BY_SHEBANG.get(interpreter)


def detect_language(filename: object, data: object = b"") -> str:
    """The one detection law, in precedence order: exact
    filename, then extension, then shebang, then the
    honest unknown (UNKNOWN_LANGUAGE). The same answer
    S-099's highlighting, S-207's indexer and S-208's
    recorded values have always used — now from here."""
    by_name = language_for_filename(filename)
    if by_name is not None:
        return by_name
    by_ext = language_for_extension(filename)
    if by_ext is not None:
        return by_ext
    by_shebang = language_for_shebang(data)
    if by_shebang is not None:
        return by_shebang
    return UNKNOWN_LANGUAGE


def canonical_language(word: object) -> str | None:
    """One filter word -> its canonical census name, or
    None when the word names no known language. Case and
    surrounding space are forgiven; aliases resolve; a
    canonical name resolves to itself. Non-text and empty
    words name nothing."""
    if not isinstance(word, str):
        return None
    cleaned = word.strip().lower()
    if not cleaned:
        return None
    if cleaned in LANGUAGE_ALIASES:
        return LANGUAGE_ALIASES[cleaned]
    if cleaned in all_languages():
        return cleaned
    return None


def language_matches(recorded: object, language_filter: object) -> bool:
    """The code-filter law over a recorded language,
    exactly S-208's pinned law executed over the one
    census: an empty filter passes everything; a filter
    naming a canonical census language (any case)
    matches exactly the rows recorded under that name;
    anything else - an alias like py, or a word naming
    no known language - matches nothing (fail closed:
    S-208's battery pins that py does NOT match python;
    aliases resolve only through canonical_language,
    never silently inside a filter)."""
    if language_filter is None or language_filter == "":
        return True
    if not isinstance(language_filter, str):
        return False
    wanted = language_filter.strip().lower()
    if wanted not in all_languages():
        return False
    return isinstance(recorded, str) and recorded.strip().lower() == wanted


def render_language_page() -> str:
    """The census page: every canonical language with the
    extensions, filenames and interpreters that name it,
    and the honest unknown said in words. Every value
    passes through S-010 escaping."""
    parts = [
        "<h1>Languages</h1>",
        "<p>One shared table names every language for code "
        "filters and highlighting. A file no signal names is "
        f"{escape_html_text(UNKNOWN_LANGUAGE)} — plain text, "
        "never a guess.</p>",
        '<ul class="languages">',
    ]
    for language in all_languages():
        exts = sorted(e for e, lang in LANGUAGE_BY_EXTENSION.items()
                      if lang == language)
        names = sorted(n for n, lang in LANGUAGE_BY_FILENAME.items()
                       if lang == language)
        interps = sorted(i for i, lang in LANGUAGE_BY_SHEBANG.items()
                         if lang == language)
        bits = []
        if exts:
            bits.append("extensions " + ", ".join(exts))
        if names:
            bits.append("filenames " + ", ".join(names))
        if interps:
            bits.append("interpreters " + ", ".join(interps))
        detail = "; ".join(bits) if bits else "the honest unknown"
        parts.append(
            f"<li>{escape_html_text(language)}: "
            f"{escape_html_text(detail)}.</li>")
    parts.append("</ul>")
    return "\n".join(parts)
