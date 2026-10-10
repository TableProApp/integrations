#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry as r  # noqa: E402
import validate  # noqa: E402

STALE_PUSH_DAYS = 548
VERIFY_AGE_DAYS = 365
GRACE_NOTICE_DAYS = 14
NEW_DOMAIN_DAYS = 90
RETRY_SECONDS = 30
ISSUE_BODY_LIMIT = 60000
CLIENTS_REPO = "TableProApp/TablePro"
CLIENTS_FILE = "TablePro/Views/Settings/Components/IntegrationClient.swift"
ENUM_CASE = re.compile(r"^[ \t]*case[ \t]+([a-z][A-Za-z0-9]*(?:[ \t]*,[ \t]*[a-z][A-Za-z0-9]*)*)[ \t]*(?:=[^\n]*)?$", re.M)
# Domains that many unrelated entries share; their age says nothing about one entry.
SHARED_DOMAINS = {"github.com", "github.io", "gitlab.com", "visualstudio.com", "open-vsx.org", "raycast.com",
                  "apple.com", "alfred.app", "brew.sh", "tablepro.app"}
PLAIN_URL_INSTALLS = {"built-in", "ships-with-host", "page"}


def registered_on(host: str) -> Optional[dt.date]:
    domain = ".".join(host.split(".")[-2:])
    request = urllib.request.Request(f"https://rdap.org/domain/{urllib.parse.quote(domain)}")
    request.add_header("Accept", "application/rdap+json")
    request.add_header("User-Agent", "tablepro-integrations-health")
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read())
    except urllib.error.HTTPError as exc:
        exc.close()
        return None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return None
    for event in data.get("events") or []:
        if event.get("eventAction") == "registration":
            return r.parse_date(str(event.get("eventDate", ""))[:10])
    return None


class Health:
    def __init__(self, root: Path, today: dt.date, gh: r.GitHub, wait: Callable[[], None]):
        self.today = today
        self.gh = gh
        self.wait = wait
        self.findings = r.Report()
        curation = r.load_curation(root, r.Report())
        entries = {slug: entry for slug, entry in r.load_entries(root).items()
                   if isinstance(entry.manifest, dict) and (entry.manifest.get("status") or {}).get("state") == "active"}
        self.ctx = validate.Context(root, today, curation, entries, r.Report(), None, "", True)
        # Every entry is already listed, so the validator's checks for new entries do not apply.
        self.ctx.base_entries = {slug: entry.manifest for slug, entry in entries.items()}

    def add(self, where: str, message: str) -> None:
        self.findings.warning(where, message)

    def twice(self, slug: str, check: Callable[[], None]) -> None:
        for attempt in (1, 2):
            self.ctx.report = r.Report()
            check()
            if not self.ctx.report.errors:
                return
            if attempt == 1:
                self.wait()
        for finding in self.ctx.report.errors:
            self.add(slug, finding.message)

    def check_source(self, entry: r.Entry) -> None:
        source = entry.manifest["source"]
        if source["type"] != "github":
            return
        self.twice(entry.slug, lambda: validate.check_github_source(self.ctx, self.gh, entry, source, entry.manifest))
        if source.get("path"):
            return
        status, repo = self.gh.repository(source["repoId"])
        pushed = r.parse_date(str((repo or {}).get("pushed_at") or "")[:10]) if status == 200 else None
        if pushed and (self.today - pushed).days > STALE_PUSH_DAYS:
            self.add(entry.slug, f"{repo['full_name']} has had no push since {pushed.isoformat()}")

    def check_install(self, entry: r.Entry) -> None:
        install = entry.manifest["install"]

        def check() -> None:
            validate.check_install_target(self.ctx, entry, entry.manifest)
            if install["type"] in PLAIN_URL_INSTALLS:
                url = r.install_url(install)
                status = r.http_status(url)
                if status != 200:
                    self.ctx.report.error(entry.manifest_path, f"install target {url} answered HTTP {status}")

        self.twice(entry.slug, check)

    def check_links(self, entry: r.Entry) -> None:
        target = r.install_url(entry.manifest["install"])
        for url in sorted(set(r.collect_urls(entry.manifest)) - {target}):
            def check(url: str = url) -> None:
                status = r.http_status(url)
                if status not in (200, 429):
                    self.ctx.report.error(entry.manifest_path, f"{url} answered HTTP {status}")

            self.twice(entry.slug, check)

    def check_domain(self, entry: r.Entry) -> None:
        host = urllib.parse.urlsplit(entry.manifest["links"]["homepage"]).hostname or ""
        if not host or ".".join(host.split(".")[-2:]) in SHARED_DOMAINS:
            return
        registered = registered_on(host)
        added = r.parse_date(entry.manifest["addedAt"])
        if registered and added and registered > added:
            self.add(entry.slug, f"{host} was registered on {registered.isoformat()}, after the entry was added: check who owns it now")
        elif registered and (self.today - registered).days < NEW_DOMAIN_DAYS:
            self.add(entry.slug, f"{host} was registered on {registered.isoformat()}")

    def check_dates(self, entry: r.Entry) -> None:
        grace = (entry.manifest.get("compliance") or {}).get("grace")
        if grace:
            ends = r.parse_date(grace["endsAt"])
            items = ", ".join(grace["items"])
            if ends and ends < self.today:
                self.add(entry.slug, f"grace for {items} ended on {ends.isoformat()}: archive the entry or close {grace['tracking']}")
            elif ends and (ends - self.today).days <= GRACE_NOTICE_DAYS:
                self.add(entry.slug, f"grace for {items} ends on {ends.isoformat()}: {grace['tracking']}")
        verified = r.parse_date(entry.manifest["lastVerifiedAt"])
        if verified and (self.today - verified).days > VERIFY_AGE_DAYS:
            self.add(entry.slug, f"last verified on {verified.isoformat()}")

    def check_clients(self) -> None:
        status, data = self.gh.contents(CLIENTS_REPO, CLIENTS_FILE)
        if status != 200 or not isinstance(data, dict) or "content" not in data:
            self.add("TablePro", f"could not read {CLIENTS_REPO}/{CLIENTS_FILE} (HTTP {status})")
            return
        text = base64.b64decode(data["content"]).decode("utf-8")
        offered = {re.sub(r"([a-z0-9])([A-Z])", r"\1-\2", name.strip()).lower()
                   for group in ENUM_CASE.findall(text) for name in group.split(",")}
        listed = {slug for slug, entry in self.ctx.entries.items()
                  if entry.manifest["install"]["type"] == "built-in" and "ai-clients" in entry.manifest["categories"]}
        for slug in sorted(offered - listed):
            self.add("TablePro", f"Connect a Client offers {slug}, which has no built-in entry")
        for slug in sorted(listed - offered):
            self.add(slug, f"{CLIENTS_FILE} no longer has this client")

    def scan(self) -> None:
        self.ctx.report = r.Report()
        validate.scan_sources(self.ctx, sorted(self.ctx.entries))
        for finding in self.ctx.report.findings:
            self.add(finding.file.split("/")[1], finding.message)

    def run(self, scan: bool) -> r.Report:
        for _, entry in sorted(self.ctx.entries.items()):
            self.check_source(entry)
            self.check_install(entry)
            self.check_links(entry)
            self.check_domain(entry)
            self.check_dates(entry)
        self.check_clients()
        if scan:
            self.scan()
        return self.findings


def markdown(findings: r.Report, today: dt.date) -> str:
    if not findings.findings:
        return ""
    body = f"Health check of {today.isoformat()}. It changes no entry; a maintainer decides what to do.\n\n"
    rows = sorted(findings.findings, key=lambda f: (f.file, f.message))
    for index, finding in enumerate(rows):
        # Code spans keep third-party text from mentioning users or linking issues.
        message = finding.message.replace("`", "'")
        line = f"- `{finding.file}`: `{message}`\n"
        if len(body) + len(line) > ISSUE_BODY_LIMIT:
            body += f"\n{len(rows) - index} more findings are in the workflow log.\n"
            break
        body += line
    return body


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Weekly health check. Writes a report and never changes an entry.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--out", default="build/health.md", help="empty when every entry passes")
    parser.add_argument("--scan-sources", action="store_true", help="clone each source and scan for private-file access")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    args = parser.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    findings = Health(Path(args.root), today, r.GitHub(), lambda: time.sleep(RETRY_SECONDS)).run(args.scan_sources)
    for finding in findings.findings:
        print(f"{finding.file}: {finding.message}")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markdown(findings, today), encoding="utf-8")
    print(f"{len(findings.findings)} findings")
    return 0


if __name__ == "__main__":
    sys.exit(main())
