# S-413 -- CPU honesty (slice record)

- Slice: S-413, parent 080cf8e (401/416 banked). HELD
  ahead-work: banking is blocked in roadmap order on
  founder-only S-402; this commit is built + committed
  in team-11 only, unpushed.
- Delivered: `samverk/cpu_honesty.py` (the one register:
  4 budget kinds x 3 hardware classes, built from the
  source modules' own dicts; `claim_for`, `class_status`,
  `cross_class_verdict` refusing cross-class claims by
  name, `restatement`, `render_cpu_honesty_page`),
  `tests/test_cpu_honesty.py`, `tools/run_cpu_honesty.py`,
  `docs/CPU_HONESTY.md`.
- Proof (counts read back from hidden_files/s413-*.log):
  own battery Ran 13 OK; neighbours repo_budgets Ran 3 OK,
  search_budgets Ran 18 OK, perf_verification Ran 11 OK,
  docs_completeness Ran 7 OK.
- Honest remainder: laptop x86-64 is NOT PROVEN — never
  measured by any slice; stated budgets only. This slice
  took no new measurement on any class: Pi-class ARM and
  desktop/server x86-64 stand on S-395's published run
  alone. S-073's coarse `hardware_class()` cannot tell a
  laptop from a server; named in docs/CPU_HONESTY.md.
- No migration and no new taxonomy event: the register
  stores nothing and audits nothing. No README touched,
  no Docker.
