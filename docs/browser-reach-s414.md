# S-414 -- Browser and device reach (slice record)

- Slice: S-414, parent 080cf8e (401/416 banked). HELD
  ahead-work: banking is blocked in roadmap order on
  founder-only S-402; this commit is built + committed
  in team-12 only, unpushed.
- Delivered: `samverk/browser_reach.py` (the matrix as
  data: 4 browsers x 3 form factors = the 12-cell test
  list; `claim_for`, `cell_status`,
  `cross_browser_verdict` refusing cross-browser
  claims by name, three code-layer audits,
  `reach_data`, `render_browser_reach_page`),
  `tests/test_browser_reach.py`,
  `tools/run_browser_reach.py`, `docs/BROWSER_REACH.md`.
- Proof (counts read back from hidden_files/s414-*.log):
  own battery Ran 16 OK; neighbours target_sizes Ran 7
  OK, layout_shell Ran 10 OK, text_scaling Ran 7 OK,
  docs_completeness Ran 7 OK.
- Actually run: Firefox desktop only -- real Mozilla
  Firefox 159.0 headless on purplelongship, 2026-11-22,
  screenshot of the rendered reach page at 1280x800
  (147,822-byte PNG). Status render_checked, not
  verified; dump-dom did not complete (graphics-stack
  error), no DOM claim. A 360x740 screenshot in the
  same desktop Firefox is supporting evidence only.
- NOT PROVEN: Chrome, Safari and Edge on every form
  factor (no run executed; no Chrome/Edge binary on
  purplelongship, Safari needs Apple hardware), and
  every phone/tablet cell in every browser (no device
  run). Full verification is owned by the S-416 gate.
- Defect found, not fixed in this slice:
  viewport_meta_missing -- 70 page modules emit full
  HTML pages, none carries a viewport meta tag, so
  small-screen rendering cannot be claimed. Named in
  the register and every small-screen cell; fixing it
  (tag at every page head) + re-running is S-416's.
- No migration and no new taxonomy event: the register
  stores nothing and audits nothing. No README touched,
  no Docker.
