"""S-067 acceptance battery: server-side hooks seam.

Acceptance (roadmap S-067): pre/post-receive hook runner with
timeout and kill discipline; later parts hang protection and
scanning here.

Counted with: python3 -m unittest discover -s tests -v
"""
from __future__ import annotations
import sys, time, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from samverk.hooks import (
    HookError, HookRunner, HookVeto, RefUpdate,
)

UPDATE = RefUpdate("refs/heads/main", "0" * 40, "a" * 40)

def allow(ctx):
    return None

def veto_with_reason(ctx):
    return "branch is protected"

def veto_raised(ctx):
    raise HookVeto("secret detected in push")

def broken(ctx):
    raise RuntimeError("hook exploded")

def hangs(ctx):
    time.sleep(60)

class RegistrationTests(unittest.TestCase):
    def test_registration_law(self):
        runner = HookRunner(timeout_seconds=1.0)
        runner.register_pre_receive("guard", allow)
        runner.register_post_receive("notify", allow)
        self.assertEqual(runner.names("pre-receive"), ("guard",))
        self.assertEqual(runner.names("post-receive"), ("notify",))
        with self.assertRaises(HookError):
            runner.register_pre_receive("guard", allow)      # duplicate name
        with self.assertRaises(HookError):
            runner.register("mid-receive", "x", allow)       # unknown phase
        with self.assertRaises(HookError):
            runner.register_pre_receive("bad", "not-callable")
        with self.assertRaises(HookError):
            HookRunner(timeout_seconds=0)                    # no unbounded wait

class PreReceiveTests(unittest.TestCase):
    def test_no_hooks_and_allowing_hooks_pass_the_push(self):
        runner = HookRunner(timeout_seconds=2.0)
        self.assertTrue(runner.run_pre_receive("volmarr/proj", [UPDATE]).allowed)
        seen = []
        def recorder(ctx):
            seen.append((ctx.phase, ctx.repo, ctx.updates[0].ref))
        runner.register_pre_receive("recorder", recorder)
        runner.register_pre_receive("guard", allow)
        result = runner.run_pre_receive("volmarr/proj", [UPDATE], actor="volmarr")
        self.assertTrue(result.allowed)
        self.assertEqual([o.status for o in result.outcomes],
                         ["allowed", "allowed"])

    def test_veto_stops_the_chain_and_carries_the_reason(self):
        calls = []
        def after(ctx):
            calls.append("after")
        runner = HookRunner(timeout_seconds=2.0)
        runner.register_pre_receive("guard", veto_with_reason)
        runner.register_pre_receive("after", after)
        result = runner.run_pre_receive("volmarr/proj", [UPDATE])
        self.assertFalse(result.allowed)
        self.assertEqual(result.vetoed_by, "guard")
        self.assertEqual(result.reason, "branch is protected")
        self.assertEqual(calls, [])          # the chain stopped at the veto
        runner2 = HookRunner(timeout_seconds=2.0)
        runner2.register_pre_receive("scanner", veto_raised)
        result2 = runner2.run_pre_receive("volmarr/proj", [UPDATE])
        self.assertFalse(result2.allowed)
        self.assertEqual(result2.reason, "secret detected in push")

    def test_a_broken_pre_receive_hook_fails_closed(self):
        runner = HookRunner(timeout_seconds=2.0)
        runner.register_pre_receive("broken", broken)
        result = runner.run_pre_receive("volmarr/proj", [UPDATE])
        self.assertFalse(result.allowed)
        self.assertEqual(result.outcomes[0].status, "error")
        self.assertIn("hook exploded", result.reason)

    def test_a_hanging_pre_receive_hook_is_killed_and_refuses(self):
        runner = HookRunner(timeout_seconds=0.5)
        runner.register_pre_receive("sleeper", hangs)
        started = time.monotonic()
        result = runner.run_pre_receive("volmarr/proj", [UPDATE])
        elapsed = time.monotonic() - started
        self.assertFalse(result.allowed)
        self.assertEqual(result.outcomes[0].status, "timeout")
        # Kill discipline: the runner returned in about the budget,
        # not after the hook's 60-second sleep.
        self.assertLess(elapsed, 10.0)

class PostReceiveTests(unittest.TestCase):
    def test_post_receive_records_everything_and_vetoes_nothing(self):
        runner = HookRunner(timeout_seconds=0.5)
        runner.register_post_receive("notify", allow)
        runner.register_post_receive("late-veto", veto_with_reason)
        runner.register_post_receive("broken", broken)
        runner.register_post_receive("sleeper", hangs)
        started = time.monotonic()
        outcomes = runner.run_post_receive("volmarr/proj", [UPDATE])
        elapsed = time.monotonic() - started
        self.assertEqual([o.name for o in outcomes],
                         ["notify", "late-veto", "broken", "sleeper"])
        self.assertEqual([o.status for o in outcomes],
                         ["completed", "vetoed", "error", "timeout"])
        self.assertLess(elapsed, 10.0)       # the hang was killed, not waited out

if __name__ == "__main__":
    unittest.main()
