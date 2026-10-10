#!/usr/bin/env python3
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(TESTS.parent))
sys.path.insert(0, str(TESTS))

import build  # noqa: E402
import registry as r  # noqa: E402
from test_validate import RepoCase  # noqa: E402

STAMP = "2026-10-10T08:00:00Z"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
METADATA_CHUNKS = {"iCCP", "sRGB", "gAMA", "cHRM", "tEXt", "zTXt", "iTXt", "eXIf", "pHYs", "tIME"}


def save_png(path: Path, size: tuple, color: tuple, **params) -> None:
    from PIL import Image

    Image.new("RGBA", size, color).save(path, format="PNG", **params)


class BuildTests(RepoCase):
    def build(self, out="dist", release=None):
        return build.build(self.root, self.root / out, COMMIT, STAMP, release)

    def assertBuildsNothing(self, release=None):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            self.build(release=release)
        self.assertFalse((self.root / "dist").exists())

    def files(self, out="dist") -> dict:
        return {p.name: p.read_bytes() for p in (self.root / out).iterdir()}

    def test_index_matches_the_published_schema(self):
        index = self.build()
        validator = r.validator_for(self.root, r.INDEX_SCHEMA)
        self.assertEqual([e.message for e in validator.iter_errors(index)], [])
        self.assertEqual(json.loads((self.root / "dist" / "index.json").read_text(encoding="utf-8")), index)

    def test_two_builds_are_byte_identical(self):
        self.build("a")
        self.build("b")
        self.assertEqual(self.files("a"), self.files("b"))

    def test_release_tag_does_not_change_the_content_digest(self):
        plain = self.build("a")
        tagged = self.build("b", "v1.20261010.7")
        self.assertEqual(plain["contentSha256"], tagged["contentSha256"])
        self.assertEqual(tagged["release"], "v1.20261010.7")
        self.assertNotIn("release", plain)

    def test_checksums_list_index_and_every_image(self):
        index = self.build()
        files = self.files()
        listed = {}
        for line in files["SHA256SUMS"].decode("ascii").splitlines():
            digest, name = line.split("  ", 1)
            listed[name] = digest
        self.assertEqual(set(listed), set(files) - {"SHA256SUMS"})
        for name, digest in listed.items():
            self.assertEqual(hashlib.sha256(files[name]).hexdigest(), digest, name)
        named = {image["file"] for entry in index["integrations"] for image in entry["icon"].values()}
        self.assertEqual(set(listed), named | {"index.json"})

    def test_images_are_flat_reencoded_and_content_addressed(self):
        from PIL import Image, ImageCms
        from PIL.PngImagePlugin import PngInfo

        ddev = self.root / "integrations" / "ddev"
        text = PngInfo()
        text.add_text("Comment", "drawn by hand")
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        save_png(ddev / "icon.png", (512, 512), (10, 120, 200, 255), pnginfo=text, icc_profile=srgb, dpi=(144, 144))
        save_png(ddev / "screenshot-1.png", (1600, 1000), (240, 240, 240, 255))
        self.edit("ddev", lambda d: d.update(screenshots=[{"file": "screenshot-1.png", "alt": "The ddev tablepro command"}]))
        entry = {e["slug"]: e for e in self.build()["integrations"]}["ddev"]
        images = list(entry["icon"].items()) + [("shot", shot) for shot in entry["screenshots"]]
        self.assertEqual(entry["screenshots"][0]["alt"], "The ddev tablepro command")
        for label, image in images:
            path = self.root / "dist" / image["file"]
            data = path.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            self.assertEqual(image["sha256"], digest)
            self.assertRegex(image["file"], rf"^ddev-[a-z0-9-]+-{digest[:12]}\.png$")
            self.assertFalse(METADATA_CHUNKS & set(r.png_chunks(data)), label)
            with Image.open(path) as decoded:
                self.assertEqual(decoded.size, (image["width"], image["height"]))
                self.assertEqual(decoded.mode, "RGB", "an opaque image is stored without alpha")
        self.assertEqual([entry["icon"]["512"]["width"], entry["icon"]["128"]["width"]], [512, 128])
        self.assertRegex(entry["screenshots"][0]["file"], r"^ddev-screenshot-1-")

    def test_derived_fields(self):
        entries = {e["slug"]: e for e in self.build()["integrations"]}
        self.assertTrue(entries["ddev-manager"]["closedSource"])
        self.assertIsNone(entries["ddev-manager"]["license"])
        self.assertEqual(entries["ddev-manager"]["install"]["url"],
                         "https://marketplace.visualstudio.com/items?itemName=biati.ddev-manager")
        self.assertFalse(entries["ddev"]["closedSource"])
        self.assertEqual(entries["ddev"]["source"]["url"],
                         "https://github.com/ddev/ddev/tree/HEAD/pkg/ddevapp/global_dotddev_assets/commands/host/tablepro")
        self.assertEqual(entries["zed"]["install"]["url"], entries["zed"]["install"]["docs"])
        summary = self.manifest("zed")["summary"]
        self.assertEqual(entries["zed"]["summarySha256"], hashlib.sha256(summary.encode("utf-8")).hexdigest())
        self.assertNotIn("$schema", entries["zed"])

    def test_tombstones_are_published(self):
        (self.root / "curation" / "removed.json").write_text(json.dumps({
            "$schema": "../schema/curation.schema.json",
            "removed": [{"slug": "old-tool", "name": "Old Tool", "removedAt": "2026-10-01", "reason": "author-request",
                         "link": "https://github.com/TableProApp/integrations/issues/3"}],
        }))
        index = self.build()
        self.assertEqual(index["removed"], [{"slug": "old-tool", "removedAt": "2026-10-01", "reason": "author-request"}])

    def test_invalid_registry_builds_nothing(self):
        self.edit("ddev", lambda d: d.update(tier="official"))
        self.assertBuildsNothing()

    def test_bad_release_tag_builds_nothing(self):
        self.assertBuildsNothing(release="latest")


if __name__ == "__main__":
    unittest.main()
