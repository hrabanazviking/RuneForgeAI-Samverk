"""Browser and device reach (S-414).

Roadmap S-414: Browser and device reach -- the web UI
verified in current Chrome, Firefox, Safari, and Edge,
and on phone and tablet browsers (small screens, touch
targets per S-386); the device matrix is the test list.

- **The matrix is the test list.** BROWSERS x
  FORM_FACTORS is every cell this slice owes: 4
  browsers x desktop/phone/tablet = 12 cells. A cell
  is proven only by a run in that cell, recorded in
  RUNS with browser, version, machine, method and
  date. Everything else is NOT PROVEN, in those
  words, everywhere it appears.
- **One real run, claimed exactly.** On 2026-11-22
  the rendered reach page was loaded in a real
  Mozilla Firefox 159.0 (headless, purplelongship)
  and a screenshot captured at 1280x800. That is a
  render check of ONE cell (firefox/desktop) -- not
  an interactive verification, and it proves nothing
  about any other browser or form factor. Full
  verification of every cell is owned by the S-416
  portability gate.
- **Code/render-layer checks that run here.** Touch
  targets: S-386's audit over the registry and the
  rendered nav is green. Proprietary features: no
  vendor-prefixed or browser-only token appears in
  any Samverk module source (this module excluded:
  it names the tokens in order to ban them) or in
  rendered output. Small screens: the viewport audit
  finds a DEFECT -- no page module emits a viewport
  meta tag, so phone/tablet rendering cannot be
  claimed; the defect is named viewport_meta_missing
  in every small-screen cell and owned by S-416.
- **No cross-browser claims, ever.** A run in one
  browser claims nothing about another; asking is
  refused by name (cross_browser_claim). Unknown
  browser or form factor is refused by name
  (browser_unknown / form_unknown), never defaulted.
- **No stored state.** A register is data the code
  states, not data the forge keeps. No migration,
  no audit event: schema 140 / taxonomy 142 stand.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .escaping import escape_html_text
from .layout_shell import render_nav
from .target_sizes import audit_rendered_nav, audit_targets

__all__ = [
    "BROWSERS", "FORM_FACTORS", "RUNS", "TEST_LIST",
    "BrowserReachError", "ReachEntry", "reach_register",
    "claim_for", "cell_status", "cross_browser_verdict",
    "audit_touch_targets", "audit_proprietary",
    "audit_viewport", "reach_data", "render_browser_reach_page",
]

BROWSERS = ("chrome", "firefox", "safari", "edge")
BROWSER_LABELS = {"chrome": "Chrome", "firefox": "Firefox",
                  "safari": "Safari", "edge": "Edge"}
FORM_FACTORS = ("desktop", "phone", "tablet")
FORM_LABELS = {"desktop": "desktop", "phone": "phone",
               "tablet": "tablet"}
FORM_VIEWPORT_CSS_PX = {"desktop": 1280, "phone": 360,
                        "tablet": 768}

# The only run this slice actually executed. Every
# other cell is absent here, never invented.
RUNS = {
    ("firefox", "desktop"): {
        "browser_version": "Mozilla Firefox 159.0",
        "machine": "purplelongship, x86-64",
        "method": "headless screenshot of the rendered "
                  "browser-reach page at 1280x800",
        "date": "2026-11-22",
        "result": "page rendered; screenshot captured",
    },
}

TEST_LIST = tuple(f"{b}/{f}" for b in BROWSERS
                  for f in FORM_FACTORS)

PROPRIETARY_TOKENS = ("-webkit-", "-moz-", "-ms-",
                      "ActiveX", "document.all")


class BrowserReachError(ValueError):
    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


def _require_browser(browser: str) -> None:
    if browser not in BROWSERS:
        raise BrowserReachError(
            "browser_unknown",
            f"No browser {browser!r} is in the matrix.")


def _require_form(form: str) -> None:
    if form not in FORM_FACTORS:
        raise BrowserReachError(
            "form_unknown",
            f"No form factor {form!r} is in the matrix.")


def audit_touch_targets() -> list:
    """S-386's law over the registry + rendered nav."""
    return audit_targets() + audit_rendered_nav()


def audit_proprietary() -> list:
    """No vendor-prefixed or browser-only token in any
    module source (this module excluded -- it names
    the tokens to ban them) or in rendered output."""
    problems = []
    here = Path(__file__).resolve()
    for path in sorted(here.parent.glob("*.py")):
        if path == here:
            continue
        text = path.read_text(encoding="utf-8")
        for token in PROPRIETARY_TOKENS:
            if token in text:
                problems.append(
                    f"proprietary_token:{path.name}:{token}")
    for token in PROPRIETARY_TOKENS:
        if token in render_nav("home"):
            problems.append(f"proprietary_rendered:{token}")
    return problems


def audit_viewport() -> list:
    """Every module emitting a full HTML page must
    carry a viewport meta tag for small screens.
    Returns one problem per offending module."""
    problems = []
    here = Path(__file__).resolve().parent
    for path in sorted(here.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "<!DOCTYPE html>" in text and "viewport" not in text:
            problems.append(
                f"viewport_meta_missing:{path.name}")
    return problems


@dataclass(frozen=True)
class ReachEntry:
    """One matrix cell: browser x form factor, its
    viewport width, its proof status in words, the
    run facts (only where a real run happened) and
    the named reasons a cell is not proven."""
    browser: str
    browser_label: str
    form_factor: str
    viewport_css_px: int
    status: str  # "render_checked" or "NOT PROVEN"
    run: dict | None
    reasons: tuple


def _reasons(browser: str, form: str) -> tuple:
    out = []
    if (browser, form) not in RUNS:
        out.append(f"no_run_recorded:{browser}/{form}")
    if form in ("phone", "tablet") and audit_viewport():
        out.append("viewport_meta_missing")
    return tuple(out)


def reach_register() -> tuple:
    """The whole matrix: every browser x every form
    factor, browsers in BROWSERS order, forms in
    FORM_FACTORS order."""
    out = []
    for browser in BROWSERS:
        for form in FORM_FACTORS:
            run = RUNS.get((browser, form))
            out.append(ReachEntry(
                browser=browser,
                browser_label=BROWSER_LABELS[browser],
                form_factor=form,
                viewport_css_px=FORM_VIEWPORT_CSS_PX[form],
                status="render_checked" if run else "NOT PROVEN",
                run=run, reasons=_reasons(browser, form)))
    return tuple(out)


def claim_for(browser: str, form: str) -> ReachEntry:
    """The register cell for one (browser, form) pair.
    Unknown browser or form is refused by name."""
    _require_browser(browser)
    _require_form(form)
    for entry in reach_register():
        if entry.browser == browser and entry.form_factor == form:
            return entry
    raise AssertionError("register is complete by construction")


def cell_status(browser: str, form: str) -> str:
    return claim_for(browser, form).status


def cross_browser_verdict(proven_in: str, claimed_for_browser: str,
                          form: str) -> bool:
    """May a run in one browser be claimed for another?
    Same browser: the claim is that cell's own (True
    only if a run is actually recorded). Any other
    browser: refused by name (cross_browser_claim)."""
    _require_browser(proven_in)
    _require_browser(claimed_for_browser)
    _require_form(form)
    if proven_in != claimed_for_browser:
        raise BrowserReachError(
            "cross_browser_claim",
            f"A run in {proven_in} claims nothing about "
            f"{claimed_for_browser}.")
    return claim_for(claimed_for_browser, form).status == "render_checked"


def reach_data() -> dict:
    """The register as JSON-safe data, plus the
    code-layer audits' results stated plainly."""
    viewport = audit_viewport()
    return {
        "entries": [{
            "browser": e.browser, "browser_label": e.browser_label,
            "form_factor": e.form_factor,
            "viewport_css_px": e.viewport_css_px,
            "status": e.status, "run": e.run,
            "reasons": list(e.reasons)}
            for e in reach_register()],
        "touch_target_problems": audit_touch_targets(),
        "proprietary_problems": audit_proprietary(),
        "viewport_problems": viewport,
        "small_screen_status": "NOT PROVEN",
    }


def render_browser_reach_page(data: dict) -> str:
    """The reach page: every matrix cell with its
    status in words; the one real run stated with
    its facts; NOT PROVEN cells say so plainly and
    name their reasons. All values pass through
    S-010 escaping."""
    parts = [
        "<h1>Browser and device reach</h1>",
        "<p>The device matrix is the test list: Chrome, "
        "Firefox, Safari and Edge, on desktop, phone and "
        "tablet. A cell is proven only by a run in that "
        "cell. Touch targets follow S-386 (44px).</p>",
        '<ul class="browser-reach-register">']
    for e in data["entries"]:
        if e["status"] == "render_checked":
            run = e["run"]
            words = (f"render checked in {run['browser_version']} "
                     f"on {run['machine']} -- {run['method']} "
                     f"({run['date']}): {run['result']}; full "
                     f"interactive verification NOT PROVEN")
        else:
            words = "NOT PROVEN -- " + ", ".join(e["reasons"])
        text = (f"{e['browser_label']} on {e['form_factor']} "
                f"({e['viewport_css_px']}px): {words}")
        parts.append(f"<li>{escape_html_text(text)}</li>")
    parts.append("</ul>")
    parts.append(
        "<p>Small screens are NOT PROVEN: no page module "
        "emits a viewport meta tag (defect "
        "viewport_meta_missing), owned by the S-416 "
        "portability gate.</p>")
    return "\n".join(parts)
