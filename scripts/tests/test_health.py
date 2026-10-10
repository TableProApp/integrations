#!/usr/bin/env python3
from __future__ import annotations

import base64
import datetime as dt
import sys
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))

import health  # noqa: E402
import registry as r  # noqa: E402
from test_validate import TODAY, FakeResponse, RepoCase  # noqa: E402

CLIENTS = """enum IntegrationClient: String, CaseIterable, Identifiable, Sendable {
    case claudeCode
    case claudeDesktop
    case cursor
    case zed

    var displayName: String {
        switch self {
        case .claudeCode: return "Claude Code"
        case .claudeDesktop: return "Claude Desktop"
        case .cursor: return "Cursor"
        case .zed: return "Zed"
        }
    }
}
"""


class HealthTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.routes = {}
        for entry in r.load_entries(self.root).values():
            source = entry.manifest["source"]
            if source["type"] != "github":
                continue
            self.routes[f"/repositories/{source['repoId']}"] = (200, {
                "full_name": source["repo"], "archived": False, "private": False, "fork": False,
                "pushed_at": "2026-09-01T10:00:00Z"})
            if source.get("path"):
                self.routes[f"/repos/{source['repo']}/contents/{source['path']}"] = (200, [])
            else:
                self.routes[f"/repos/{source['repo']}/license"] = (200, {"license": {"spdx_id": entry.manifest["license"]}})
        self.clients(CLIENTS)
        self.statuses = {}
        self.registered = {}
        self.waits = 0

    def clients(self, text):
        path = f"/repos/{health.CLIENTS_REPO}/contents/{health.CLIENTS_FILE}"
        self.routes[path] = (200, {"content": base64.b64encode(text.encode()).decode()})

    def opener(self, request, timeout=30):
        path = request.full_url.replace("https://api.github.com", "")
        status, body = self.routes.get(path, (404, None))
        if status >= 400:
            raise urllib.error.HTTPError(request.full_url, status, "x", {}, None)
        return FakeResponse(status, body)

    def http_status(self, url, method="GET", opener=None):
        queue = self.statuses.get(url)
        return queue.pop(0) if queue else 200

    def wait(self):
        self.waits += 1

    def check(self):
        gh = r.GitHub(token="", opener=self.opener)
        with mock.patch.object(r, "http_status", self.http_status), \
                mock.patch.object(health, "registered_on", lambda host: self.registered.get(host)):
            report = health.Health(self.root, TODAY, gh, self.wait).run(scan=False)
        return [(f.file, f.message) for f in report.findings]

    def assertFinding(self, findings, where, fragment):
        self.assertTrue(any(w == where and fragment in m for w, m in findings), f"no {where} finding with {fragment!r}: {findings}")

    def test_healthy_registry_has_no_findings(self):
        self.assertEqual(self.check(), [])
        self.assertEqual(self.waits, 0)

    def test_install_target_failing_once_is_not_reported(self):
        self.statuses["https://www.raycast.com/ngoquocdat/tablepro"] = [503]
        self.assertEqual(self.check(), [])
        self.assertEqual(self.waits, 1)

    def test_install_target_failing_twice_is_reported(self):
        docs = self.manifest("zed")["install"]["docs"]
        self.statuses[docs] = [404, 404]
        self.assertFinding(self.check(), "zed", f"install target {docs} answered HTTP 404")

    def test_broken_link_is_reported(self):
        self.statuses["https://github.com/electricarts/local-tablepro/issues"] = [500, 410]
        self.assertFinding(self.check(), "localwp", "answered HTTP 410")

    def test_source_is_checked_by_repository_id(self):
        self.routes["/repositories/1309032022"] = (200, {"full_name": "someone/local-tablepro", "archived": True})
        findings = self.check()
        self.assertFinding(findings, "localwp", "is someone/local-tablepro, not electricarts/local-tablepro")
        self.assertFinding(findings, "localwp", "archived on GitHub")

    def test_deleted_source_is_reported(self):
        del self.routes["/repositories/80669528"]
        self.assertFinding(self.check(), "ddev", "repository id 80669528 not found")

    def test_removed_license_is_reported(self):
        del self.routes["/repos/electricarts/local-tablepro/license"]
        self.assertFinding(self.check(), "localwp", "no LICENSE file")

    def test_source_without_recent_push_is_reported(self):
        self.routes["/repositories/1309032022"][1]["pushed_at"] = "2024-12-31T00:00:00Z"
        self.assertFinding(self.check(), "localwp", "no push since 2024-12-31")

    def test_grace_ending_and_ended(self):
        def grace(ends):
            self.edit("localwp", lambda d: d["compliance"]["grace"].update(
                startedAt=(ends - dt.timedelta(days=60)).isoformat(), endsAt=ends.isoformat()))
        grace(TODAY + dt.timedelta(days=10))
        self.assertFinding(self.check(), "localwp", "ends on 2026-10-20")
        grace(TODAY - dt.timedelta(days=1))
        self.assertFinding(self.check(), "localwp", "ended on 2026-10-09")

    def test_old_verification_is_reported(self):
        self.edit("ddev", lambda d: d.update(addedAt="2025-01-01", lastVerifiedAt="2025-06-01"))
        self.assertFinding(self.check(), "ddev", "last verified on 2025-06-01")

    def test_homepage_domain_registered_after_the_entry(self):
        self.edit("ddev", lambda d: d.update(addedAt="2026-01-05"))
        self.registered["ddev.com"] = dt.date(2026, 3, 1)
        self.assertFinding(self.check(), "ddev", "ddev.com was registered on 2026-03-01, after the entry was added")

    def test_new_client_in_the_app_is_reported(self):
        self.clients(CLIENTS.replace("    case zed\n", "    case zed\n    case vsCode\n"))
        self.assertFinding(self.check(), "TablePro", "offers vs-code, which has no built-in entry")

    def test_client_dropped_by_the_app_is_reported(self):
        self.clients(CLIENTS.replace("    case zed\n", ""))
        self.assertFinding(self.check(), "zed", "no longer has this client")

    def test_archived_entries_are_skipped(self):
        self.edit("raycast", lambda d: d.update(status={"state": "archived", "since": "2026-10-10", "reason": "unmaintained"}))
        self.statuses["https://www.raycast.com/ngoquocdat/tablepro"] = [404, 404]
        self.assertEqual(self.check(), [])

    def test_markdown_puts_findings_in_code_spans(self):
        report = r.Report()
        self.assertEqual(health.markdown(report, TODAY), "")
        report.warning("ddev", "src/@someone `x` #12 reads it")
        self.assertIn("- `ddev`: `src/@someone 'x' #12 reads it`\n", health.markdown(report, TODAY))


if __name__ == "__main__":
    unittest.main()
