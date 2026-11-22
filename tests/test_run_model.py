"""S-345 acceptance battery: the run model.

Acceptance (roadmap S-345): one process serves web,
API, transports' HTTP half, and background jobs are
separate worker processes under the same unit family;
the topology is drawn in the operator guide.

The centre is samverk/run_model.py: the standing
topology as data (one server role serving exactly the
HTTP surfaces; four worker roles, each its own process
and entry), the pure `validate_topology` judge naming
every broken law, `render_topology` drawing the
picture docs/RUN_MODEL.md carries (a test keeps code
and guide from drifting), and proofs against the real
seams the topology names -- server.serve/make_server,
the worker modules' own `main` entry points, the
mirror scheduler's `run_due`, git_http's smart-HTTP
service and ssh_serve's forced-command shape.
No migration (schema stays 139); taxonomy unmoved
at 138.

Counted with: python3 -m unittest tests.test_run_model
"""
from __future__ import annotations

import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from samverk import run_model, taxonomy
from samverk.config import DEFAULT_HOST, DEFAULT_PORT, Config
from samverk.db import init_db, schema_version
from samverk.run_model import (
    CADENCE_ALWAYS_ON,
    HTTP_SURFACES,
    ROLE_SERVER,
    ROLE_WORKER,
    build_topology,
    operator_words,
    render_topology,
    topology_stands,
    validate_topology,
)

ROOT = Path(__file__).resolve().parent.parent


class StandingTopologyTest(unittest.TestCase):
    def setUp(self):
        self.topo = build_topology()

    def test_standing_topology_validates_clean(self):
        self.assertEqual(validate_topology(self.topo), [])
        self.assertTrue(topology_stands(self.topo))

    def test_exactly_one_server_role(self):
        servers = [r for r in self.topo.roles if r.kind == ROLE_SERVER]
        self.assertEqual(len(servers), 1)
        self.assertIs(servers[0], self.topo.server)

    def test_server_serves_exactly_the_http_surfaces(self):
        self.assertEqual(set(self.topo.server.serves), set(HTTP_SURFACES))
        self.assertEqual(set(HTTP_SURFACES),
                         {"web", "api", "git-http", "lfs-http"})

    def test_server_runs_no_background_jobs(self):
        self.assertEqual(self.topo.server.jobs, ())
        self.assertEqual(self.topo.server.cadence, CADENCE_ALWAYS_ON)

    def test_workers_are_separate_and_serve_no_http(self):
        self.assertEqual(len(self.topo.workers), 4)
        for worker in self.topo.workers:
            self.assertEqual(worker.kind, ROLE_WORKER)
            self.assertEqual(worker.serves, ())
            self.assertTrue(worker.jobs)
            self.assertTrue(worker.entry)
            self.assertNotEqual(worker.cadence, CADENCE_ALWAYS_ON)

    def test_each_job_run_by_exactly_one_worker(self):
        jobs = [j for w in self.topo.workers for j in w.jobs]
        self.assertEqual(len(jobs), len(set(jobs)))
        self.assertEqual(set(jobs), {"webhook-delivery", "weekly-digest",
                                     "artifact-expiry", "mirror-sync"})

    def test_one_unit_family(self):
        for role in self.topo.roles:
            self.assertTrue(role.unit.startswith("samverk-"), role.unit)
        units = [r.unit for r in self.topo.roles]
        self.assertEqual(len(units), len(set(units)))

    def test_role_lookup_by_name_and_unit(self):
        self.assertIs(self.topo.role_named("server"), self.topo.server)
        self.assertIs(self.topo.role_for_unit("samverk-mirror-sync"),
                      self.topo.role_named("mirror-sync"))
        self.assertIsNone(self.topo.role_named("nope"))
        self.assertIsNone(self.topo.role_for_unit("other-server"))

    def test_ssh_is_an_external_door_not_a_role(self):
        names = [r.name for r in self.topo.roles]
        self.assertNotIn("ssh", names)
        self.assertTrue(any("ssh" in d for d in self.topo.external_doors))


class JudgeTest(unittest.TestCase):
    def setUp(self):
        self.topo = build_topology()

    def test_worker_serving_http_is_refused(self):
        bad_worker = replace(self.topo.workers[0], serves=("web",))
        bad = replace(self.topo, workers=(bad_worker,) + self.topo.workers[1:])
        problems = validate_topology(bad)
        self.assertTrue(any("only the server serves HTTP" in p
                            for p in problems), problems)

    def test_server_missing_a_surface_is_refused(self):
        bad = replace(self.topo, server=replace(
            self.topo.server, serves=("web", "api")))
        problems = validate_topology(bad)
        self.assertTrue(any("git-http" in p for p in problems), problems)
        self.assertTrue(any("lfs-http" in p for p in problems), problems)

    def test_server_running_jobs_is_refused(self):
        bad = replace(self.topo, server=replace(
            self.topo.server, jobs=("weekly-digest",)))
        self.assertTrue(any("background jobs" in p
                            for p in validate_topology(bad)))

    def test_unit_outside_family_is_refused(self):
        bad_worker = replace(self.topo.workers[0], unit="other-delivery")
        bad = replace(self.topo, workers=(bad_worker,) + self.topo.workers[1:])
        self.assertTrue(any("outside the samverk family" in p
                            for p in validate_topology(bad)))

    def test_duplicate_job_and_always_on_worker_refused(self):
        bad_worker = replace(self.topo.workers[1],
                             jobs=self.topo.workers[0].jobs,
                             cadence=CADENCE_ALWAYS_ON)
        bad = replace(self.topo, workers=self.topo.workers[:1]
                      + (bad_worker,) + self.topo.workers[2:])
        problems = validate_topology(bad)
        self.assertTrue(any("more than one worker" in p for p in problems))
        self.assertTrue(any("always-on" in p for p in problems))

    def test_worker_with_no_job_or_entry_is_refused(self):
        bad_worker = replace(self.topo.workers[0], jobs=(), entry="")
        bad = replace(self.topo, workers=(bad_worker,) + self.topo.workers[1:])
        problems = validate_topology(bad)
        self.assertTrue(any("runs no job" in p for p in problems))
        self.assertTrue(any("no entry point" in p for p in problems))


class RealSeamsTest(unittest.TestCase):
    def test_server_entry_is_the_real_serve(self):
        from samverk import server
        self.assertTrue(callable(server.serve))
        self.assertTrue(callable(server.make_server))
        topo = build_topology()
        self.assertIn("samverk serve", topo.server.entry)

    def test_make_server_binds_the_configured_address(self):
        from samverk.server import make_server
        with tempfile.TemporaryDirectory() as td:
            cfg = Config(host="127.0.0.1", port=0, data_root=Path(td))
            httpd = make_server(cfg)
            try:
                self.assertEqual(httpd.server_address[0], "127.0.0.1")
            finally:
                httpd.server_close()
        self.assertEqual((DEFAULT_HOST, DEFAULT_PORT), ("127.0.0.1", 8737))

    def test_cli_worker_modules_carry_their_own_main(self):
        from samverk import artifact_expiry, digest_job, webhook_delivery
        for module in (webhook_delivery, digest_job, artifact_expiry):
            self.assertTrue(callable(module.main), module.__name__)
        topo = build_topology()
        cli_workers = [w for w in topo.workers if w.has_cli]
        self.assertEqual(len(cli_workers), 3)
        for worker in cli_workers:
            self.assertIn("-m samverk.", worker.entry)

    def test_mirror_sync_worker_names_the_real_seam(self):
        from samverk.sync_scheduler import SyncSchedulerService
        self.assertTrue(callable(SyncSchedulerService.run_due))
        worker = build_topology().role_named("mirror-sync")
        self.assertFalse(worker.has_cli)
        self.assertIn("run_due", worker.entry)

    def test_http_half_and_ssh_seams_exist_as_named(self):
        from samverk.git_http import SmartHttpService
        from samverk.lfs_api import LFSApi
        from samverk.ssh_serve import SshServeService
        self.assertTrue(callable(SmartHttpService.advertise))
        self.assertIsNotNone(LFSApi)
        self.assertTrue(callable(SshServeService.serve))

    def test_no_migration_no_new_taxonomy_event(self):
        with tempfile.TemporaryDirectory() as td:
            conn = init_db(Path(td) / "samverk.db")
            try:
                self.assertEqual(schema_version(conn), 140)
            finally:
                conn.close()
        self.assertEqual(len(taxonomy.AUDIT_EVENTS), 142)


class DrawingAndWordsTest(unittest.TestCase):
    def test_render_names_every_role_and_unit(self):
        drawing = render_topology()
        topo = build_topology()
        for role in topo.roles:
            self.assertIn(role.unit, drawing)
            self.assertIn(role.name, drawing)
        self.assertIn("web, api, git-http, lfs-http", drawing)

    def test_operator_guide_carries_the_drawing(self):
        guide = (ROOT / "docs" / "RUN_MODEL.md").read_text("utf-8")
        for line in render_topology().splitlines():
            if line.strip():
                self.assertIn(line, guide)
        for role in build_topology().roles:
            self.assertIn(role.unit, guide)

    def test_operator_words_cover_every_role(self):
        words = operator_words()
        topo = build_topology()
        self.assertEqual(len(words), len(topo.roles))
        for line, role in zip(words, topo.roles):
            self.assertTrue(line.startswith(role.unit + ":"), line)

    def test_main_prints_and_check_passes(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_model.main(["--check"])
        self.assertEqual(rc, 0)
        self.assertIn("the standing topology stands", buf.getvalue())
        self.assertIn("samverk-server", buf.getvalue())

    def test_main_without_check_still_prints_topology(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = run_model.main([])
        self.assertEqual(rc, 0)
        self.assertIn("samverk-mirror-sync", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
