# Browser and device reach (S-414)

The device matrix is the test list: Chrome, Firefox,
Safari and Edge, each on desktop, phone and tablet --
12 cells. A cell is proven only by a run in that
cell, recorded with browser, version, machine,
method and date. Everything else reads NOT PROVEN,
in those words. Full verification of every cell is
owned by the S-416 portability gate.

## The one real run

On 2026-11-22 the rendered browser-reach page was
loaded in a real Mozilla Firefox 159.0 (headless) on
purplelongship and a screenshot captured at 1280x800
(147,822 bytes, 1280x800 PNG). That cell --
firefox/desktop -- is therefore "render_checked":
the page renders in a current Firefox. It is NOT an
interactive verification, and this slice does not
call it one. A second screenshot at a 360x740 window
in the same desktop Firefox (86,909 bytes) is
supporting evidence only: a small window in a
desktop browser is not a phone browser, and no
phone or tablet cell claims anything from it.
Firefox's headless dump-dom did not complete on
this machine (graphics-stack error), so no DOM
claim is made.

## NOT PROVEN, plainly

- Chrome (all forms): NOT PROVEN -- no Chrome run
  was executed; no Chrome binary is installed on
  purplelongship.
- Safari (all forms): NOT PROVEN -- no Safari run
  was executed; Safari needs Apple hardware/OS.
- Edge (all forms): NOT PROVEN -- no Edge run was
  executed; no Edge binary is installed here.
- Firefox on phone and tablet: NOT PROVEN -- no
  phone or tablet device was run.
- Every phone and tablet cell in every browser:
  NOT PROVEN, and carrying the defect below.

## Code/render-layer checks (run, green)

- Touch targets per S-386: the registry audit and
  the rendered-nav audit both pass -- every target
  at least 44x44px, controls in the 40-48px band.
- No browser-proprietary features: no vendor-prefixed
  or browser-only token (-webkit-, -moz-, -ms-,
  ActiveX, document.all) appears in any Samverk
  module source (samverk/browser_reach.py excluded:
  it names the tokens in order to ban them) or in
  rendered navigation output.

## Defect found: viewport_meta_missing

The viewport audit scans every module that emits a
full HTML page for a viewport meta tag. It finds 70
page modules and not one viewport tag. Without
`<meta name="viewport" content="width=device-width,
initial-scale=1">` a phone or tablet browser
renders at a desktop-width layout viewport and
scales down -- small-screen rendering cannot be
claimed for any page. The defect is recorded by
name in samverk/browser_reach.py, stated in every
phone/tablet cell, and owned by the S-416
portability gate, which must either fix it (add the
tag at every page head) and re-run, or keep every
small-screen cell NOT PROVEN.

## The law in code

samverk/browser_reach.py holds the matrix as data
(reach_register / claim_for / TEST_LIST), the run
record (RUNS), the three audits, and the refusal
rules: carrying one browser's run to another is
refused by name (cross_browser_claim); an unknown
browser or form factor is refused by name
(browser_unknown / form_unknown), never defaulted
to a neighbour's verdict. No stored state, no
migration, no audit event.
