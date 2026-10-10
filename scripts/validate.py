#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
import json
import os
import subprocess
import sys
import tempfile
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry as r  # noqa: E402

MAINTAINER_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}


class Context:
    def __init__(self, root: Path, today: dt.date, curation: dict, entries: dict, report: r.Report,
                 base: Optional[str], author: str, maintainer: bool):
        self.root = root
        self.today = today
        self.curation = curation
        self.entries = entries
        self.report = report
        self.base = base
        self.author = author
        self.maintainer = maintainer
        self.base_entries: dict = {}
        self.changed_paths: list = []
        self.needs_consent: list = []

    def curated(self, name: str, key: str) -> list:
        return (self.curation.get(name) or {}).get(key, [])


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def load_base(ctx: Context) -> None:
    if not ctx.base:
        return
    ctx.changed_paths = [line.split("\t") for line in git(ctx.root, "diff", "--name-status", "--no-renames",
                                                           f"{ctx.base}...HEAD").splitlines() if line]
    listing = git(ctx.root, "ls-tree", "-r", "--name-only", ctx.base, "--", "integrations")
    for path in listing.splitlines():
        parts = path.split("/")
        if len(parts) == 3 and parts[2] == "integration.json":
            try:
                ctx.base_entries[parts[1]] = json.loads(git(ctx.root, "show", f"{ctx.base}:{path}"))
            except (subprocess.CalledProcessError, json.JSONDecodeError):
                ctx.base_entries[parts[1]] = None


def check_url(ctx: Context, file: str, url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https":
        ctx.report.error(file, f"{url}: use https")
    if parsed.username or parsed.password:
        ctx.report.error(file, f"{url}: remove the user name or password from the URL")
    try:
        ipaddress.ip_address(host)
        ctx.report.error(file, f"{url}: use a host name, not an IP address")
    except ValueError:
        pass
    if host in r.SHORTENER_HOSTS:
        ctx.report.error(file, f"{url}: link to the destination, not a URL shortener")


def check_text(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    file = entry.manifest_path
    fields = [("name", manifest.get("name")), ("summary", manifest.get("summary")),
              ("description", manifest.get("description")), ("publisher.name", (manifest.get("publisher") or {}).get("name"))]
    for label, value in fields:
        if not isinstance(value, str):
            continue
        if unicodedata.normalize("NFC", value) != value:
            ctx.report.error(file, f"{label}: normalize the text to NFC")
        bad = r.unsafe_characters(value.replace("\n", ""))
        if bad:
            ctx.report.error(file, f"{label}: remove {', '.join(sorted(set(bad)))}", r.line_of(entry.text, [label.split('.')[-1]]))


def check_naming(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    file = entry.manifest_path
    if manifest.get("tier") == "official":
        return
    reserved = ctx.curation.get("reserved.json") or {}
    name = manifest.get("name", "")
    if entry.slug in reserved.get("slugs", []):
        ctx.report.error(file, f"slug `{entry.slug}` is reserved")
    reserved_names = {r.normalized_name(n) for n in reserved.get("names", [])}
    if r.normalized_name(name) in reserved_names:
        ctx.report.error(file, f"name `{name}` is reserved", r.line_of(entry.text, ["name"]))
    for fragment in reserved.get("nameFragments", []):
        if r.contains_fragment(entry.slug, fragment):
            ctx.report.error(file, f"slug may not contain `{fragment}`")
        if r.contains_fragment(name, fragment):
            ctx.report.error(file, f"name may not contain `{fragment}`: the directory already says it works with TablePro",
                             r.line_of(entry.text, ["name"]))


def check_tier(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    file = entry.manifest_path
    tier = manifest.get("tier")
    publisher = manifest.get("publisher") or {}
    if tier == "official":
        allowed = {(p["github"].lower(), p["githubId"]) for p in ctx.curated("official-publishers.json", "publishers")}
        if (publisher.get("github", "").lower(), publisher.get("githubId")) not in allowed:
            ctx.report.error(file, "tier official needs a publisher listed in curation/official-publishers.json",
                             r.line_of(entry.text, ["tier"]))
    if tier == "partner":
        rows = [p for p in ctx.curated("partners.json", "partners") if p["slug"] == entry.slug]
        if not rows:
            ctx.report.error(file, "tier partner needs a row in curation/partners.json", r.line_of(entry.text, ["tier"]))
        elif rows[0]["githubId"] != publisher.get("githubId"):
            ctx.report.error(file, "publisher does not match the verified partner in curation/partners.json")


def check_dates(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    file = entry.manifest_path
    added = r.parse_date(manifest.get("addedAt"))
    verified = r.parse_date(manifest.get("lastVerifiedAt"))
    if added and added > ctx.today:
        ctx.report.error(file, "addedAt is in the future", r.line_of(entry.text, ["addedAt"]))
    if verified and verified > ctx.today:
        ctx.report.error(file, "lastVerifiedAt is in the future", r.line_of(entry.text, ["lastVerifiedAt"]))
    if added and verified and verified < added:
        ctx.report.error(file, "lastVerifiedAt is before addedAt", r.line_of(entry.text, ["lastVerifiedAt"]))
    status = manifest.get("status") or {}
    if status.get("state") == "archived":
        since = r.parse_date(status.get("since"))
        if since and added and since < added:
            ctx.report.error(file, "status.since is before addedAt")
        replacement = status.get("replacement")
        if replacement and replacement not in ctx.entries:
            ctx.report.error(file, f"status.replacement `{replacement}` is not an entry")
    grace = (manifest.get("compliance") or {}).get("grace")
    if grace:
        started = r.parse_date(grace.get("startedAt"))
        ends = r.parse_date(grace.get("endsAt"))
        if started and ends:
            if ends <= started:
                ctx.report.error(file, "compliance.grace.endsAt must be after startedAt")
            elif (ends - started).days > r.GRACE_MAX_DAYS:
                ctx.report.error(file, f"compliance.grace is {(ends - started).days} days; the policy allows {r.GRACE_MAX_DAYS}")
            if ends < ctx.today:
                ctx.report.warning(file, f"compliance.grace ended on {ends.isoformat()}: fix the items or archive the entry")


def check_consistency(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    file = entry.manifest_path
    if manifest.get("slug") != entry.slug:
        ctx.report.error(file, f"slug `{manifest.get('slug')}` must equal the folder name `{entry.slug}`",
                         r.line_of(entry.text, ["slug"]))
    platforms = set(manifest.get("platforms") or [])
    for key in (manifest.get("minTableProVersion") or {}):
        if key not in platforms:
            ctx.report.error(file, f"minTableProVersion.{key} is set but {key} is not in platforms")
    source = manifest.get("source") or {}
    install = manifest.get("install") or {}
    if install.get("type") == "github-release" and source.get("type") == "github":
        repo = "/".join(install["url"].split("/")[3:5])
        if repo.lower() != source.get("repo", "").lower():
            ctx.report.error(file, f"install.url points at {repo}, not the source repository {source.get('repo')}")
    if install.get("type") == "github-release" and source.get("type") != "github":
        ctx.report.error(file, "a github-release install needs a github source")
    if install.get("type") == "page":
        ctx.report.warning(file, "install type page needs a maintainer to approve the destination")
    for url in r.collect_urls(manifest):
        check_url(ctx, file, url)


def check_files(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    prefix = f"integrations/{entry.slug}/"
    for path in sorted(entry.directory.iterdir()):
        if path.is_symlink() or not path.is_file() or not r.ENTRY_FILE.match(path.name):
            ctx.report.error(prefix + path.name, "only integration.json, icon.png and screenshot-1.png to screenshot-4.png belong in an entry folder")
    icon = entry.directory / "icon.png"
    if icon.is_file() and not icon.is_symlink():
        problems = r.check_png(icon, r.ICON_SIZE, r.ICON_MAX_BYTES)
        for problem in problems:
            ctx.report.error(prefix + "icon.png", "icon " + problem)
        if not problems:
            check_protected_mark(ctx, entry, manifest, icon)
    else:
        ctx.report.error(prefix + "icon.png", "icon.png is missing")
    listed = [s.get("file") for s in manifest.get("screenshots") or []]
    if len(set(listed)) != len(listed):
        ctx.report.error(entry.manifest_path, "a screenshot is listed twice")
    expected = [f"screenshot-{i}.png" for i in range(1, len(listed) + 1)]
    if sorted(listed) != expected:
        ctx.report.error(entry.manifest_path, "number screenshots from screenshot-1.png without gaps")
    present = sorted(p.name for p in entry.directory.glob("screenshot-*.png"))
    for name in sorted(set(present) - set(listed)):
        ctx.report.error(prefix + name, "this screenshot is not listed in integration.json")
    for name in listed:
        path = entry.directory / name
        if not path.is_file():
            ctx.report.error(prefix + name, "listed in integration.json but missing")
            continue
        for problem in r.check_png(path, r.SHOT_SIZE, r.SHOT_MAX_BYTES):
            ctx.report.error(prefix + name, "screenshot " + problem)


def check_protected_mark(ctx: Context, entry: r.Entry, manifest: dict, icon) -> None:
    if manifest.get("tier") == "official":
        return
    marks = ctx.curation.get("protected-marks.json") or {}
    try:
        digest = r.mark_hash(icon)
    except Exception as exc:
        ctx.report.error(f"integrations/{entry.slug}/icon.png", f"could not compare the icon with the TablePro marks: {exc}")
        return
    limit = marks.get("maxDistance", 0)
    for mark in marks.get("marks", []):
        distance = r.hash_distance(digest, mark["hash"])
        if distance <= limit:
            ctx.report.error(f"integrations/{entry.slug}/icon.png",
                             f"icon looks like the TablePro mark `{mark['id']}` (distance {distance}). Use your own icon; a small TablePro badge in a corner is fine")
            return


def check_cross(ctx: Context) -> None:
    seen_names: dict = {}
    seen_sources: dict = {}
    seen_installs: dict = {}
    removed = {row["slug"]: row for row in ctx.curated("removed.json", "removed")}
    for slug, entry in ctx.entries.items():
        manifest = entry.manifest
        if not isinstance(manifest, dict):
            continue
        file = entry.manifest_path
        if slug in removed:
            ctx.report.error(file, f"slug `{slug}` was removed on {removed[slug]['removedAt']} ({removed[slug]['reason']}) and cannot be reused")
        key = r.normalized_name(manifest.get("name", ""))
        if key in seen_names:
            ctx.report.error(file, f"name duplicates the entry `{seen_names[key]}`")
        seen_names.setdefault(key, slug)
        source = manifest.get("source") or {}
        built_in = (manifest.get("install") or {}).get("type") == "built-in"
        if source.get("type") == "github" and not built_in:
            source_key = (source.get("repoId"), source.get("path", ""))
            if source_key in seen_sources:
                ctx.report.error(file, f"source duplicates the entry `{seen_sources[source_key]}`")
            seen_sources.setdefault(source_key, slug)
        install = manifest.get("install") or {}
        if install.get("type") and install.get("type") != "built-in":
            target = r.install_url(install).lower()
            if target in seen_installs:
                ctx.report.error(file, f"install target duplicates the entry `{seen_installs[target]}`")
            seen_installs.setdefault(target, slug)
    changed = changed_slugs(ctx)
    names = {slug: r.normalized_name((e.manifest or {}).get("name", "")) for slug, e in ctx.entries.items()
             if isinstance(e.manifest, dict)}
    for slug in changed:
        for other, other_name in names.items():
            if other == slug or slug not in names:
                continue
            if 0 < r.levenshtein(names[slug], other_name) <= r.SIMILAR_NAME_DISTANCE:
                ctx.report.warning(ctx.entries[slug].manifest_path, f"name is close to the entry `{other}`")


def changed_slugs(ctx: Context) -> list:
    if not ctx.base:
        return list(ctx.entries)
    slugs = set()
    for parts in ctx.changed_paths:
        segments = parts[-1].split("/")
        if len(segments) >= 2 and segments[0] == "integrations":
            slugs.add(segments[1])
    return sorted(slugs)


def check_change_scope(ctx: Context) -> None:
    if not ctx.base:
        return
    touched_entries = set()
    other_paths = []
    for parts in ctx.changed_paths:
        path = parts[-1]
        segments = path.split("/")
        if segments[0] == "integrations" and len(segments) >= 3:
            touched_entries.add(segments[1])
        else:
            other_paths.append(path)
    removed_rows = {row["slug"] for row in ctx.curated("removed.json", "removed")}
    for slug in sorted(touched_entries):
        before = ctx.base_entries.get(slug)
        entry = ctx.entries.get(slug)
        file = f"integrations/{slug}/integration.json"
        if entry is None:
            if slug not in removed_rows:
                ctx.report.error(file, "an entry was deleted without a tombstone in curation/removed.json; archive it instead, or add the tombstone")
            if not ctx.maintainer:
                ctx.report.error(file, "only maintainers remove entries; open a removal request issue")
            continue
        if before is None or not isinstance(entry.manifest, dict):
            continue
        after = entry.manifest
        if before.get("addedAt") != after.get("addedAt"):
            ctx.report.error(file, "addedAt never changes after the first merge", r.line_of(entry.text, ["addedAt"]))
        for label, old, new in (
            ("source.repoId", (before.get("source") or {}).get("repoId"), (after.get("source") or {}).get("repoId")),
            ("publisher.githubId", (before.get("publisher") or {}).get("githubId"), (after.get("publisher") or {}).get("githubId")),
            ("tier", before.get("tier"), after.get("tier")),
            ("compliance", before.get("compliance"), after.get("compliance")),
            ("lastVerifiedAt", before.get("lastVerifiedAt"), after.get("lastVerifiedAt")),
        ):
            if old != new and not ctx.maintainer:
                ctx.report.error(file, f"{label} changed; only a maintainer changes it")
    added = [s for s in touched_entries if s in ctx.entries and s not in ctx.base_entries]
    deleted = [s for s in touched_entries if s not in ctx.entries and s in ctx.base_entries]
    if added and deleted:
        ctx.report.error("integrations/", f"a slug cannot be renamed ({', '.join(deleted)} to {', '.join(added)}); slugs are permanent")
    if not ctx.maintainer:
        if len(touched_entries) > 1:
            ctx.report.error("integrations/", "change one entry folder per pull request")
        for path in other_paths:
            ctx.report.error(path, "only maintainers change files outside integrations/<slug>/")


def check_online(ctx: Context, gh: r.GitHub, slugs: list) -> None:
    for slug in slugs:
        entry = ctx.entries.get(slug)
        if entry is None or not isinstance(entry.manifest, dict):
            continue
        manifest = entry.manifest
        file = entry.manifest_path
        publisher = manifest.get("publisher") or {}
        status, user = gh.user(publisher.get("github", ""))
        if status != 200:
            ctx.report.error(file, f"GitHub account {publisher.get('github')} not found")
        elif user.get("id") != publisher.get("githubId"):
            ctx.report.error(file, f"publisher.githubId {publisher.get('githubId')} does not match {publisher.get('github')} ({user.get('id')})")
        source = manifest.get("source") or {}
        if source.get("type") == "github":
            check_github_source(ctx, gh, entry, source, manifest)
        check_ownership(ctx, gh, entry, source, publisher)
        grace = (manifest.get("compliance") or {}).get("grace")
        if grace:
            parts = grace["tracking"].split("/")
            status, issue = gh.issue(f"{parts[3]}/{parts[4]}", int(parts[6]))
            if status != 200:
                ctx.report.error(file, "compliance.grace.tracking issue not found")
        check_install_target(ctx, entry, manifest)


def check_github_source(ctx: Context, gh: r.GitHub, entry: r.Entry, source: dict, manifest: dict) -> None:
    file = entry.manifest_path
    status, repo = gh.repository(source["repoId"])
    if status != 200:
        ctx.report.error(file, f"repository id {source['repoId']} not found")
        return
    if repo["full_name"].lower() != source["repo"].lower():
        ctx.report.error(file, f"repository id {source['repoId']} is {repo['full_name']}, not {source['repo']}")
    if repo.get("archived"):
        ctx.report.error(file, f"{repo['full_name']} is archived on GitHub")
    if repo.get("private"):
        ctx.report.error(file, f"{repo['full_name']} is private")
    if repo.get("fork") and entry.slug not in ctx.base_entries:
        ctx.report.warning(file, f"{repo['full_name']} is a fork; the policy needs the original author's approval")
    if source.get("path"):
        status, _ = gh.contents(repo["full_name"], source["path"])
        if status != 200:
            ctx.report.error(file, f"source.path {source['path']} not found in {repo['full_name']}")
        return
    status, license_info = gh.license(repo["full_name"])
    declared = manifest.get("license", "")
    if status != 200:
        ctx.report.error(file, f"{repo['full_name']} has no LICENSE file GitHub can find")
        return
    detected = ((license_info or {}).get("license") or {}).get("spdx_id") or "NOASSERTION"
    if detected == "NOASSERTION":
        ctx.report.warning(file, f"GitHub cannot identify the license of {repo['full_name']}; a maintainer checks it against {declared}")
    elif detected not in (declared, declared.replace("-only", ""), declared.replace("-or-later", "")):
        ctx.report.error(file, f"license is {declared} here but GitHub reports {detected}")


def check_ownership(ctx: Context, gh: r.GitHub, entry: r.Entry, source: dict, publisher: dict) -> None:
    if ctx.maintainer or not ctx.author or entry.slug in ctx.base_entries:
        return
    author = ctx.author.lower()
    if author == publisher.get("github", "").lower():
        return
    if source.get("type") == "github":
        owner = source["repo"].split("/")[0]
        if author == owner.lower() or gh.public_member(owner, ctx.author):
            return
        status, contributors = gh.contributors(source["repo"])
        if status == 200 and contributors:
            top = contributors[0].get("contributions", 0)
            mine = next((c.get("contributions", 0) for c in contributors if c.get("login", "").lower() == author), 0)
            if top and mine * 3 >= top:
                return
    ctx.needs_consent.append(entry.slug)
    ctx.report.warning(entry.manifest_path, f"@{ctx.author} is not the publisher, the repository owner or a major contributor; the PR needs the owner's consent in a comment")


def check_install_target(ctx: Context, entry: r.Entry, manifest: dict) -> None:
    install = manifest.get("install") or {}
    kind = install.get("type")
    url = None
    if kind == "homebrew":
        url = f"https://formulae.brew.sh/api/{install['kind']}/{install['token']}.json"
    elif kind == "vscode-marketplace":
        publisher, name = install["id"].split(".", 1)
        if install.get("openVsx"):
            status = r.http_status(f"https://open-vsx.org/api/{publisher}/{name}")
            if status != 200:
                ctx.report.error(entry.manifest_path, f"Open VSX has no {install['id']} (HTTP {status})")
        url = r.install_url(install)
    elif kind in ("raycast-store", "alfred-gallery", "app-store", "github-release"):
        url = install["url"]
    if url:
        status = r.http_status(url)
        if status != 200:
            ctx.report.error(entry.manifest_path, f"install target {url} answered HTTP {status}")


def scan_sources(ctx: Context, slugs: list) -> None:
    allow = {(a["slug"], a["file"], a["rule"]) for a in ctx.curated("scan-allowlist.json", "allow")}
    for slug in slugs:
        entry = ctx.entries.get(slug)
        if entry is None or not isinstance(entry.manifest, dict):
            continue
        source = entry.manifest.get("source") or {}
        if source.get("type") != "github" or entry.manifest.get("install", {}).get("type") == "built-in":
            continue
        with tempfile.TemporaryDirectory() as tmp:
            try:
                tree = r.fetch_source(source["repo"], source.get("path"), Path(tmp) / "src")
            except Exception as exc:
                ctx.report.warning(entry.manifest_path, f"could not fetch the source to scan it: {exc}")
                continue
            for file, line, rule, text in r.scan_tree(tree):
                if (slug, file, rule) in allow:
                    continue
                ctx.report.error(entry.manifest_path,
                                 f"{source['repo']}/{source.get('path', '')} {file}:{line} reads TablePro's private storage ({rule}: `{text}`). Use a documented interface")


def validate_entries(ctx: Context, validator) -> None:
    for slug, entry in ctx.entries.items():
        file = entry.manifest_path
        if not r.SLUG.match(slug):
            ctx.report.error(f"integrations/{slug}/", "folder name must be lowercase words joined by hyphens")
        if entry.load_error:
            ctx.report.error(file, entry.load_error)
            continue
        if r.schema_errors(validator, entry.manifest, entry.text, file, ctx.report):
            check_files(ctx, entry, entry.manifest if isinstance(entry.manifest, dict) else {})
            continue
        manifest = entry.manifest
        check_consistency(ctx, entry, manifest)
        check_text(ctx, entry, manifest)
        check_naming(ctx, entry, manifest)
        check_tier(ctx, entry, manifest)
        check_dates(ctx, entry, manifest)
        check_files(ctx, entry, manifest)


def run(root: Path, today: dt.date, base: Optional[str] = None, author: str = "", maintainer: bool = True,
        online: bool = False, scan: bool = False, gh: Optional[r.GitHub] = None) -> Context:
    report = r.Report()
    r.check_schema_files(root, report)
    curation = r.load_curation(root, report)
    entries = r.load_entries(root)
    ctx = Context(root, today, curation, entries, report, base, author, maintainer)
    load_base(ctx)
    validator = r.validator_for(root, r.INTEGRATION_SCHEMA)
    validate_entries(ctx, validator)
    check_cross(ctx)
    check_change_scope(ctx)
    if online:
        check_online(ctx, gh or r.GitHub(), changed_slugs(ctx))
    if scan:
        scan_sources(ctx, changed_slugs(ctx))
    return ctx


def emit(ctx: Context, annotations: bool) -> None:
    for finding in ctx.report.findings:
        if annotations:
            message = finding.message.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
            line = f",line={finding.line}" if finding.line else ""
            print(f"::{finding.level} file={finding.file}{line}::{message}")
        else:
            where = f"{finding.file}:{finding.line}" if finding.line else finding.file
            print(f"{finding.level}: {where}: {finding.message}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(f"### Registry validation\n\n{len(ctx.report.errors)} errors, {len(ctx.report.warnings)} warnings\n\n")
            for finding in ctx.report.findings:
                handle.write(f"- **{finding.level}** `{finding.file}`: {finding.message}\n")


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Validate the TablePro integrations registry.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--base", help="git ref of the target branch; enables change-scope checks")
    parser.add_argument("--author", default="", help="pull request author login")
    parser.add_argument("--author-association", default="OWNER", help="GitHub author_association of the PR author")
    parser.add_argument("--online", action="store_true", help="check GitHub, licenses, ownership and install targets")
    parser.add_argument("--scan-sources", action="store_true", help="clone changed sources and scan for private-file access")
    parser.add_argument("--urls-out", help="write every URL of the changed entries to this file")
    parser.add_argument("--today", help="override today's date (YYYY-MM-DD)")
    parser.add_argument("--annotations", action="store_true", help="print GitHub Actions annotations")
    args = parser.parse_args(argv)
    today = dt.date.fromisoformat(args.today) if args.today else dt.datetime.now(dt.timezone.utc).date()
    ctx = run(Path(args.root), today, args.base, args.author,
              args.author_association.upper() in MAINTAINER_ASSOCIATIONS, args.online, args.scan_sources)
    if args.urls_out:
        urls = set()
        for slug in changed_slugs(ctx):
            entry = ctx.entries.get(slug)
            if entry and isinstance(entry.manifest, dict):
                urls.update(r.collect_urls(entry.manifest))
        Path(args.urls_out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.urls_out).write_text("".join(u + "\n" for u in sorted(urls)), encoding="utf-8")
    emit(ctx, args.annotations)
    print(f"{len(ctx.entries)} entries, {len(ctx.report.errors)} errors, {len(ctx.report.warnings)} warnings")
    return 1 if ctx.report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
