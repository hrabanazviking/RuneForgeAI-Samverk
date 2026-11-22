# Screen-reader pass (S-389)

ARIA landmarks and labels on the core flows, audited over the pages
Samverk actually renders: `samverk/screen_reader_pass.py` checks
the per-surface landmark set (banner, navigation, main,
contentinfo), parses S-382's rendered navigation on every surface
(the Primary landmark labelled, every link carrying an accessible
name, heading levels never skipping), and holds S-387's seam that
every status's text is its accessible name. The structural audit
passes clean.

## Findings

- **F-S389-1 (NAMED, not fixed):** the live walkthrough with a real
  screen reader (Orca on the fleet laptops) has not been run — no
  reader session exists on the build seat. The roadmap's "verified
  with a real screen reader" leg closes only with that session;
  what this slice verifies is the complete structural audit the
  reader consumes. Recorded here and in the module header so the
  remainder is never mistaken for a pass.
- No structural findings: no fix was needed in the rendered nav or
  the landmark registry.
