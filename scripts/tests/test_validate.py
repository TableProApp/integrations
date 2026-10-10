#!/usr/bin/env python3
from __future__ import annotations

import copy
import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent
REPO = SCRIPTS.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import registry as r  # noqa: E402
import validate  # noqa: E402

TODAY = dt.date(2026, 10, 10)
TABLEPRO_ICON = FIXTURES / "integrations" / "raycast" / "icon.png"


def schema_validator():
    return r.validator_for(REPO, r.INTEGRATION_SCHEMA)


def seed(slug: str) -> dict:
    return json.loads((FIXTURES / "integrations" / slug / "integration.json").read_text(encoding="utf-8"))


def messages(validator, data) -> list:
    return [e.message for e in validator.iter_errors(data)]


class SchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = schema_validator()

    def test_every_seed_passes(self):
        for path in sorted((FIXTURES / "integrations").glob("*/integration.json")):
            with self.subTest(entry=path.parent.name):
                self.assertEqual(messages(self.validator, json.loads(path.read_text())), [])

    def rejects(self, slug, mutate):
        data = copy.deepcopy(seed(slug))
        mutate(data)
        self.assertTrue(list(self.validator.iter_errors(data)), "expected the schema to reject this manifest")

    def test_unknown_tier(self):
        self.rejects("ddev", lambda d: d.update(tier="verified"))

    def test_extra_property(self):
        self.rejects("ddev", lambda d: d.update(stars=10))

    def test_http_url(self):
        self.rejects("ddev", lambda d: d["links"].update(homepage="http://ddev.com"))

    def test_url_with_user_info(self):
        self.rejects("ddev", lambda d: d["links"].update(homepage="https://user:pass@ddev.com"))

    def test_ip_literal_url(self):
        self.rejects("ddev", lambda d: d["links"].update(homepage="https://192.168.1.10/"))

    def test_javascript_url(self):
        self.rejects("ddev", lambda d: d["links"].update(docs="javascript:alert(1)"))

    def test_summary_without_period(self):
        self.rejects("ddev", lambda d: d.update(summary="Open the database of a DDEV project in TablePro"))

    def test_summary_with_markup(self):
        self.rejects("ddev", lambda d: d.update(summary="Open the <b>database</b> of a DDEV project in TablePro."))

    def test_name_with_bidi_control(self):
        self.rejects("ddev", lambda d: d.update(name="DD\u202eEV"))

    def test_description_with_three_newlines(self):
        self.rejects("ddev", lambda d: d.update(description=d["description"].replace("\n\n", "\n\n\n", 1)))

    def test_name_longer_than_32_characters(self):
        self.rejects("ddev", lambda d: d.update(name="D" * 33))

    def test_slug_with_uppercase(self):
        self.rejects("ddev", lambda d: d.update(slug="DDEV"))

    def test_schema_version_two(self):
        self.rejects("ddev", lambda d: d.update(schemaVersion=2))

    def test_github_source_without_license(self):
        self.rejects("ddev", lambda d: d.pop("license"))

    def test_closed_source_with_license(self):
        self.rejects("ddev-manager", lambda d: d.update(license="Apache-2.0"))

    def test_github_source_without_repo_id(self):
        self.rejects("ddev", lambda d: d["source"].pop("repoId"))

    def test_source_path_traversal(self):
        self.rejects("ddev", lambda d: d["source"].update(path="pkg/../../etc"))

    def test_built_in_on_community_tier(self):
        self.rejects("command-line", lambda d: d.update(tier="community"))

    def test_built_in_docs_outside_tablepro(self):
        self.rejects("command-line", lambda d: d["install"].update(docs="https://example.com/docs"))

    def test_raycast_install_on_another_host(self):
        self.rejects("raycast", lambda d: d["install"].update(url="https://raycast.example.com/a/b"))

    def test_github_release_must_be_latest_page(self):
        self.rejects("localwp", lambda d: d["install"].update(
            url="https://github.com/electricarts/local-tablepro/releases/download/v2.0.0/x.tgz"))

    def test_install_branch_rejects_foreign_keys(self):
        self.rejects("ddev-manager", lambda d: d["install"].update(url="https://example.com"))

    def test_unknown_install_type(self):
        self.rejects("ddev", lambda d: d.update(install={"type": "download", "url": "https://ddev.com/x.dmg"}))

    def test_unknown_category(self):
        self.rejects("ddev", lambda d: d.update(categories=["integration"]))

    def test_three_categories(self):
        self.rejects("ddev", lambda d: d.update(categories=["local-development", "command-line", "other"]))

    def test_unknown_surface(self):
        self.rejects("ddev", lambda d: d.update(surfaces=["connections-json"]))

    def test_lowers_safe_mode_without_note(self):
        self.rejects("localwp", lambda d: d["disclosures"].pop("safeModeNote"))

    def test_lowers_safe_mode_outside_local_development(self):
        self.rejects("localwp", lambda d: d.update(categories=["launchers"]))

    def test_internet_without_note(self):
        self.rejects("raycast", lambda d: d["disclosures"].pop("networkNote"))

    def test_paid_without_note(self):
        self.rejects("ddev", lambda d: d["disclosures"].update(payment="paid"))

    def test_account_without_privacy_link(self):
        self.rejects("ddev", lambda d: d["disclosures"].update(account=True))

    def test_archived_without_reason(self):
        self.rejects("ddev", lambda d: d.update(status={"state": "archived", "since": "2026-10-10"}))

    def test_archived_reason_outside_enum(self):
        self.rejects("ddev", lambda d: d.update(status={"state": "archived", "since": "2026-10-10", "reason": "removed"}))

    def test_superseded_without_replacement(self):
        self.rejects("ddev", lambda d: d.update(status={"state": "archived", "since": "2026-10-10", "reason": "superseded"}))

    def test_active_with_archive_fields(self):
        self.rejects("ddev", lambda d: d.update(status={"state": "active", "since": "2026-10-10"}))

    def test_grace_item_outside_enum(self):
        self.rejects("localwp", lambda d: d["compliance"]["grace"].update(items=["stars"]))

    def test_grace_tracking_not_an_issue(self):
        self.rejects("localwp", lambda d: d["compliance"]["grace"].update(tracking="https://example.com/issue"))

    def test_bad_date(self):
        self.rejects("ddev", lambda d: d.update(addedAt="2026-13-01"))

    def test_icon_other_than_png(self):
        self.rejects("ddev", lambda d: d.update(icon="icon.svg"))

    def test_five_screenshots(self):
        self.rejects("ddev", lambda d: d.update(screenshots=[{"file": f"screenshot-{i}.png", "alt": "A screenshot of it"} for i in range(1, 6)]))

    def test_wrong_schema_reference(self):
        self.rejects("ddev", lambda d: d.update({"$schema": "https://evil.example/schema.json"}))

    def test_publisher_login_with_double_hyphen(self):
        self.rejects("ddev", lambda d: d["publisher"].update(github="dd--ev"))


class IndexSchemaTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.validator = r.validator_for(REPO, r.INDEX_SCHEMA)

    def image(self, name, size):
        return {"file": name, "width": size, "height": size, "sha256": "0" * 64}

    def index(self, icon_file):
        entry = {k: v for k, v in seed("ddev").items() if k not in ("$schema", "schemaVersion")}
        entry.update(
            summarySha256="0" * 64,
            closedSource=False,
            install=dict(entry["install"], url=r.install_url(entry["install"])),
            icon={"512": self.image(icon_file, 512), "128": self.image("ddev-icon-128-0123456789ab.png", 128)},
            screenshots=[],
        )
        return {"schemaVersion": 1, "generatedAt": "2026-10-10T00:00:00Z", "commit": "0" * 40,
                "contentSha256": "0" * 64, "integrations": [entry], "removed": []}

    def test_flat_content_addressed_image_passes(self):
        self.assertEqual(messages(self.validator, self.index("ddev-icon-512-0123456789ab.png")), [])

    def test_image_in_a_folder_is_rejected(self):
        self.assertTrue(messages(self.validator, self.index("images/ddev/icon-512.0123456789ab.png")))

    def test_image_without_content_hash_is_rejected(self):
        self.assertTrue(messages(self.validator, self.index("ddev-icon-512.png")))


class EmptyRegistryTests(unittest.TestCase):
    def test_no_entries_is_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("schema", "curation"):
                shutil.copytree(REPO / name, root / name)
            (root / "integrations").mkdir()
            ctx = validate.run(root, TODAY)
        self.assertEqual(ctx.entries, {})
        self.assertEqual([f.message for f in ctx.report.findings], [])


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        for name in ("schema", "curation"):
            shutil.copytree(REPO / name, self.root / name)
        shutil.copytree(FIXTURES / "integrations", self.root / "integrations")

    def tearDown(self):
        self.tmp.cleanup()

    def manifest(self, slug: str) -> dict:
        return json.loads((self.root / "integrations" / slug / "integration.json").read_text())

    def write(self, slug: str, data: dict) -> None:
        folder = self.root / "integrations" / slug
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "integration.json").write_text(json.dumps(data, indent=2) + "\n")

    def edit(self, slug: str, mutate) -> None:
        data = self.manifest(slug)
        mutate(data)
        self.write(slug, data)

    def run_validator(self, **kwargs):
        return validate.run(self.root, TODAY, **kwargs)

    def assertError(self, ctx, fragment: str):
        found = [f.message for f in ctx.report.errors]
        self.assertTrue(any(fragment in m for m in found), f"no error containing {fragment!r}: {found}")


class SemanticTests(RepoCase):
    def test_seeds_are_clean(self):
        ctx = self.run_validator()
        self.assertEqual([f.message for f in ctx.report.errors], [])

    def test_slug_must_match_folder(self):
        self.edit("ddev", lambda d: d.update(slug="ddev-cli"))
        self.assertError(self.run_validator(), "must equal the folder name")

    def test_community_name_with_tablepro(self):
        self.edit("localwp", lambda d: d.update(name="TablePro Launcher"))
        self.assertError(self.run_validator(), "name may not contain `tablepro`")

    def test_spaced_and_camel_case_spellings_are_caught(self):
        for name in ("Table Pro for Local", "LocalTablePro", "TABLEPRO Local"):
            with self.subTest(name=name):
                self.assertTrue(r.contains_fragment(name, "tablepro"))

    def test_words_that_merely_contain_the_letters_pass(self):
        for name in ("Stable Prompt", "Portable Profiles", "Notable Projects"):
            with self.subTest(name=name):
                self.assertFalse(r.contains_fragment(name, "tablepro"))

    def test_reserved_slug(self):
        shutil.move(str(self.root / "integrations" / "ddev"), str(self.root / "integrations" / "brand"))
        self.edit("brand", lambda d: d.update(slug="brand"))
        self.assertError(self.run_validator(), "slug `brand` is reserved")

    def test_official_needs_allowlisted_publisher(self):
        self.edit("ddev", lambda d: d.update(tier="official"))
        self.assertError(self.run_validator(), "official-publishers.json")

    def test_partner_needs_a_curation_row(self):
        self.edit("ddev", lambda d: d.update(tier="partner"))
        self.assertError(self.run_validator(), "partners.json")

    def test_partner_with_curation_row_passes(self):
        self.edit("ddev", lambda d: d.update(tier="partner"))
        partners = self.root / "curation" / "partners.json"
        data = json.loads(partners.read_text())
        data["partners"].append({"slug": "ddev", "github": "ddev", "githubId": 595986, "domain": "ddev.com",
                                 "method": "github-verified-org", "verifiedAt": "2026-10-10",
                                 "evidence": "https://github.com/ddev"})
        partners.write_text(json.dumps(data))
        self.assertEqual([f.message for f in self.run_validator().report.errors], [])

    def test_removed_slug_cannot_return(self):
        removed = self.root / "curation" / "removed.json"
        removed.write_text(json.dumps({"$schema": "../schema/curation.schema.json", "removed": [
            {"slug": "ddev", "name": "DDEV", "removedAt": "2026-10-01", "reason": "author-request",
             "link": "https://github.com/TableProApp/integrations/issues/1"}]}))
        self.assertError(self.run_validator(), "cannot be reused")

    def test_removed_reason_outside_enum(self):
        removed = self.root / "curation" / "removed.json"
        removed.write_text(json.dumps({"$schema": "../schema/curation.schema.json", "removed": [
            {"slug": "old", "name": "Old", "removedAt": "2026-10-01", "reason": "Remove",
             "link": "https://github.com/TableProApp/integrations/issues/1"}]}))
        self.assertError(self.run_validator(), "is not one of")

    def test_duplicate_name(self):
        self.edit("ddev-manager", lambda d: d.update(name="D.D.E.V"))
        self.assertError(self.run_validator(), "name duplicates the entry")

    def test_similar_name_warns(self):
        self.edit("ddev-manager", lambda d: d.update(name="DDEW"))
        ctx = self.run_validator()
        self.assertTrue(any("close to the entry `ddev`" in f.message for f in ctx.report.warnings))

    def test_duplicate_install_target(self):
        self.edit("ddev-manager", lambda d: d.update(install=self.manifest("ddev")["install"]))
        self.assertError(self.run_validator(), "install target duplicates")

    def test_future_added_date(self):
        self.edit("ddev", lambda d: d.update(addedAt="2026-12-01", lastVerifiedAt="2026-12-01"))
        self.assertError(self.run_validator(), "addedAt is in the future")

    def test_verified_before_added(self):
        self.edit("ddev", lambda d: d.update(addedAt="2026-10-01", lastVerifiedAt="2026-09-01"))
        self.assertError(self.run_validator(), "lastVerifiedAt is before addedAt")

    def test_grace_longer_than_policy(self):
        self.edit("localwp", lambda d: d["compliance"]["grace"].update(endsAt="2026-12-31"))
        self.assertError(self.run_validator(), "the policy allows 60")

    def test_grace_ending_before_start(self):
        self.edit("localwp", lambda d: d["compliance"]["grace"].update(endsAt="2026-10-01"))
        self.assertError(self.run_validator(), "must be after startedAt")

    def test_min_version_for_unlisted_platform(self):
        self.edit("command-line", lambda d: d.update(minTableProVersion={"ios": "1.0"}))
        self.assertError(self.run_validator(), "ios is not in platforms")

    def test_release_install_from_another_repo(self):
        self.edit("localwp", lambda d: d["install"].update(url="https://github.com/evil/local-tablepro/releases/latest"))
        self.assertError(self.run_validator(), "not the source repository")

    def test_superseded_replacement_must_exist(self):
        self.edit("ddev-manager", lambda d: d.update(status={"state": "archived", "since": "2026-10-10",
                                                            "reason": "superseded", "replacement": "nope"}))
        self.assertError(self.run_validator(), "is not an entry")

    def test_shortener_url(self):
        self.edit("ddev", lambda d: d["links"].update(docs="https://bit.ly/abc"))
        self.assertError(self.run_validator(), "URL shortener")

    def test_emoji_in_name(self):
        self.edit("ddev", lambda d: d.update(name="DDEV \U0001F680"))
        self.assertError(self.run_validator(), "symbol or emoji")

    def test_non_nfc_text(self):
        self.edit("localwp", lambda d: d["publisher"].update(name="Rene\u0301 Peischl"))
        self.assertError(self.run_validator(), "NFC")

    def test_extra_file_in_entry_folder(self):
        (self.root / "integrations" / "ddev" / "README.md").write_text("hi")
        self.assertError(self.run_validator(), "belong in an entry folder")

    def test_svg_icon_is_rejected(self):
        (self.root / "integrations" / "ddev" / "icon.svg").write_text("<svg/>")
        self.assertError(self.run_validator(), "belong in an entry folder")

    def test_icon_wrong_size(self):
        from PIL import Image
        Image.new("RGBA", (256, 256), (1, 2, 3, 255)).save(self.root / "integrations" / "ddev" / "icon.png")
        self.assertError(self.run_validator(), "expected 512x512")

    def test_icon_that_is_not_a_png(self):
        (self.root / "integrations" / "ddev" / "icon.png").write_bytes(b"GIF89a" + b"\x00" * 64)
        self.assertError(self.run_validator(), "is not a PNG")

    def test_animated_png_icon(self):
        from PIL import Image
        frames = [Image.new("RGBA", (512, 512), (i * 80, 0, 0, 255)) for i in range(2)]
        path = self.root / "integrations" / "ddev" / "icon.png"
        frames[0].save(path, save_all=True, append_images=frames[1:], format="PNG")
        self.assertError(self.run_validator(), "animated PNG")

    def test_third_party_icon_that_is_the_tablepro_mark(self):
        shutil.copy(TABLEPRO_ICON, self.root / "integrations" / "localwp" / "icon.png")
        self.assertError(self.run_validator(), "looks like the TablePro mark")

    def test_icon_hash_failure_is_an_error(self):
        from unittest import mock
        with mock.patch.object(r, "mark_hash", side_effect=OSError("broken")):
            self.assertError(self.run_validator(), "could not compare the icon")

    def test_official_entry_may_use_the_mark(self):
        ctx = self.run_validator()
        self.assertFalse(any("TablePro mark" in f.message for f in ctx.report.findings))

    def test_listed_screenshot_missing(self):
        self.edit("ddev", lambda d: d.update(screenshots=[{"file": "screenshot-1.png", "alt": "DDEV opening TablePro"}]))
        self.assertError(self.run_validator(), "listed in integration.json but missing")

    def test_unlisted_screenshot(self):
        from PIL import Image
        Image.new("RGB", (1600, 1000)).save(self.root / "integrations" / "ddev" / "screenshot-1.png")
        self.assertError(self.run_validator(), "not listed in integration.json")

    def test_screenshot_wrong_size(self):
        from PIL import Image
        Image.new("RGB", (2000, 1250)).save(self.root / "integrations" / "ddev" / "screenshot-1.png")
        self.edit("ddev", lambda d: d.update(screenshots=[{"file": "screenshot-1.png", "alt": "DDEV opening TablePro"}]))
        self.assertError(self.run_validator(), "expected 1600x1000")

    def test_invalid_json(self):
        (self.root / "integrations" / "ddev" / "integration.json").write_text("{ nope")
        self.assertError(self.run_validator(), "invalid JSON")

    def test_curation_file_missing(self):
        (self.root / "curation" / "reserved.json").unlink()
        self.assertError(self.run_validator(), "file is missing")


class ChangeScopeTests(RepoCase):
    def setUp(self):
        super().setUp()
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.root)], check=True)
        self.commit("base")
        self.git("checkout", "-q", "-b", "pr")

    def git(self, *args):
        subprocess.run(["git", "-C", str(self.root), *args], check=True)

    def commit(self, message="change"):
        self.git("add", "-A")
        self.git("-c", "user.name=t", "-c", "user.email=t@example.com", "-c", "commit.gpgsign=false",
                 "commit", "-q", "-m", message)

    def run_pr(self, maintainer=False):
        return self.run_validator(base="main", author="someone", maintainer=maintainer)

    def test_added_at_is_immutable(self):
        self.edit("ddev", lambda d: d.update(addedAt="2026-10-09"))
        self.commit()
        self.assertError(self.run_pr(maintainer=True), "addedAt never changes")

    def test_contributor_cannot_change_tier(self):
        self.edit("ddev", lambda d: d.update(tier="official"))
        self.commit()
        self.assertError(self.run_pr(), "tier changed")

    def test_contributor_cannot_change_repo_id(self):
        self.edit("localwp", lambda d: d["source"].update(repoId=1))
        self.commit()
        self.assertError(self.run_pr(), "source.repoId changed")

    def test_contributor_touches_one_entry(self):
        self.edit("ddev", lambda d: d.update(keywords=["docker"]))
        self.edit("localwp", lambda d: d.update(keywords=["wordpress"]))
        self.commit()
        self.assertError(self.run_pr(), "one entry folder per pull request")

    def test_contributor_cannot_touch_curation(self):
        (self.root / "curation" / "partners.json").write_text(
            json.dumps({"$schema": "../schema/curation.schema.json", "partners": []}, indent=4))
        self.commit()
        self.assertError(self.run_pr(), "only maintainers change files outside")

    def test_rename_is_refused(self):
        shutil.move(str(self.root / "integrations" / "ddev"), str(self.root / "integrations" / "ddev-cli"))
        self.edit("ddev-cli", lambda d: d.update(slug="ddev-cli"))
        self.commit()
        self.assertError(self.run_pr(maintainer=True), "cannot be renamed")

    def test_deletion_needs_a_tombstone(self):
        shutil.rmtree(self.root / "integrations" / "ddev-manager")
        self.commit()
        self.assertError(self.run_pr(maintainer=True), "without a tombstone")

    def test_maintainer_deletion_with_tombstone_passes(self):
        shutil.rmtree(self.root / "integrations" / "ddev-manager")
        removed = self.root / "curation" / "removed.json"
        removed.write_text(json.dumps({"$schema": "../schema/curation.schema.json", "removed": [
            {"slug": "ddev-manager", "name": "DDEV Manager", "removedAt": "2026-10-10", "reason": "author-request",
             "link": "https://github.com/TableProApp/integrations/issues/2"}]}))
        self.commit()
        self.assertEqual([f.message for f in self.run_pr(maintainer=True).report.errors], [])

    def test_contributor_update_of_own_entry_passes(self):
        self.edit("localwp", lambda d: d.update(keywords=["wordpress", "mysql"]))
        self.commit()
        self.assertEqual([f.message for f in self.run_pr().report.errors], [])


class FakeResponse:
    def __init__(self, status, body):
        self.status = status
        self._body = json.dumps(body).encode() if body is not None else b""

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class OnlineTests(RepoCase):
    def github(self, routes):
        import urllib.error

        def opener(request, timeout=30):
            path = request.full_url.replace("https://api.github.com", "")
            if path in routes:
                status, body = routes[path]
                if status >= 400:
                    raise urllib.error.HTTPError(request.full_url, status, "x", {}, None)
                return FakeResponse(status, body)
            raise urllib.error.HTTPError(request.full_url, 404, "x", {}, None)
        return r.GitHub(token="", opener=opener)

    def local_routes(self, **overrides):
        routes = {
            "/users/electricarts": (200, {"id": 625286}),
            "/repositories/1309032022": (200, {"full_name": "electricarts/local-tablepro", "archived": False, "private": False, "fork": False}),
            "/repos/electricarts/local-tablepro/license": (200, {"license": {"spdx_id": "MIT"}}),
            "/repos/electricarts/local-tablepro/issues/10": (200, {"number": 10}),
        }
        routes.update(overrides)
        return routes

    def check(self, routes):
        report = r.Report()
        ctx = validate.Context(self.root, TODAY, r.load_curation(self.root, report), r.load_entries(self.root),
                               report, None, "", True)
        entry = ctx.entries["localwp"]
        manifest = entry.manifest
        publisher = manifest["publisher"]
        gh = self.github(routes)
        status, user = gh.user(publisher["github"])
        if status != 200 or user.get("id") != publisher["githubId"]:
            report.error(entry.manifest_path, "publisher.githubId does not match")
        validate.check_github_source(ctx, gh, entry, manifest["source"], manifest)
        return ctx

    def test_matching_repository_passes(self):
        self.assertEqual([f.message for f in self.check(self.local_routes()).report.errors], [])

    def test_repojacked_repository_id(self):
        ctx = self.check(self.local_routes(**{"/repositories/1309032022": (200, {"full_name": "attacker/local-tablepro"})}))
        self.assertError(ctx, "is attacker/local-tablepro")

    def test_archived_repository(self):
        ctx = self.check(self.local_routes(**{"/repositories/1309032022": (200, {"full_name": "electricarts/local-tablepro", "archived": True})}))
        self.assertError(ctx, "archived on GitHub")

    def test_missing_license(self):
        ctx = self.check(self.local_routes(**{"/repos/electricarts/local-tablepro/license": (404, None)}))
        self.assertError(ctx, "no LICENSE file")

    def test_license_mismatch(self):
        ctx = self.check(self.local_routes(**{"/repos/electricarts/local-tablepro/license": (200, {"license": {"spdx_id": "GPL-3.0"}})}))
        self.assertError(ctx, "GitHub reports GPL-3.0")

    def test_renamed_publisher_account(self):
        ctx = self.check(self.local_routes(**{"/users/electricarts": (200, {"id": 1})}))
        self.assertError(ctx, "publisher.githubId does not match")

    def test_ownership_for_a_stranger_needs_consent(self):
        report = r.Report()
        ctx = validate.Context(self.root, TODAY, r.load_curation(self.root, report), r.load_entries(self.root),
                               report, None, "stranger", False)
        gh = self.github({"/repos/electricarts/local-tablepro/contributors?per_page=100": (200, [
            {"login": "electricarts", "contributions": 90}, {"login": "stranger", "contributions": 3}])})
        entry = ctx.entries["localwp"]
        validate.check_ownership(ctx, gh, entry, entry.manifest["source"], entry.manifest["publisher"])
        self.assertEqual(ctx.needs_consent, ["localwp"])

    def test_major_contributor_does_not_need_consent(self):
        report = r.Report()
        ctx = validate.Context(self.root, TODAY, r.load_curation(self.root, report), r.load_entries(self.root),
                               report, None, "helper", False)
        gh = self.github({"/repos/electricarts/local-tablepro/contributors?per_page=100": (200, [
            {"login": "electricarts", "contributions": 90}, {"login": "helper", "contributions": 31}])})
        entry = ctx.entries["localwp"]
        validate.check_ownership(ctx, gh, entry, entry.manifest["source"], entry.manifest["publisher"])
        self.assertEqual(ctx.needs_consent, [])


class ScanTests(unittest.TestCase):
    def scan(self, files):
        with tempfile.TemporaryDirectory() as tmp:
            for name, text in files.items():
                path = Path(tmp) / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text)
            return [hit[2] for hit in r.scan_tree(Path(tmp))]

    def test_private_files_are_found(self):
        hits = self.scan({
            "a.ts": 'const APP = "Library/Application Support/TablePro";',
            "b.ts": 'join(dir, "mcp-handshake.json")',
            "c.py": 'Path.home() / "Library/Preferences/com.TablePro.plist"',
            "d.py": 'KEY = "com.TablePro.connections"',
            "e.sh": "security find-generic-password -s com.TablePro -w",
            "f.sh": "defaults read com.TablePro",
        })
        self.assertEqual(sorted(hits), sorted(["app-support-dir", "handshake-file", "prefs-plist", "prefs-keys", "keychain", "defaults-domain"]))

    def test_public_surfaces_are_not_flagged(self):
        hits = self.scan({
            "a.sh": 'open -b com.TablePro "mysql://db:db@127.0.0.1:3306/db"',
            "b.ts": 'open("tablepro://connect/" + id)',
            "node_modules/x/c.js": 'const p = "Application Support/TablePro"',
        })
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
