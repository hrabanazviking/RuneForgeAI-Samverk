#!/usr/bin/env python3
"""S-414 -- browser and device reach register printer.
Usage: python3 tools/run_browser_reach.py
Prints the full matrix: every browser x every form
factor, its proof status in words, the one real run's
facts, and the code-layer audit results. This tool
runs no browser: the Firefox run it reports was
recorded in RUNS when it was actually executed
(2026-11-22, purplelongship). Every cell without a
recorded run prints NOT PROVEN (see
docs/BROWSER_REACH.md).
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from samverk.browser_reach import reach_data, reach_register

def main():
    data = reach_data()
    for e in reach_register():
        if e.status == "render_checked":
            words = (f"render_checked in {e.run['browser_version']} "
                     f"({e.run['date']})")
        else:
            words = "NOT PROVEN -- " + ", ".join(e.reasons)
        print(f"{e.browser}/{e.form_factor} "
              f"({e.viewport_css_px}px): {words}")
    print(f"touch_target_problems: {data['touch_target_problems']}")
    print(f"proprietary_problems: {data['proprietary_problems']}")
    print(f"viewport_problems: {len(data['viewport_problems'])} modules")
    print(f"small_screen_status: {data['small_screen_status']}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
