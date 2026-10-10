#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import shutil
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))

import registry as r  # noqa: E402
import validate  # noqa: E402

ICON_SIZES = (512, 128)
SOURCE_ONLY = ("$schema", "schemaVersion")
NOT_CONTENT = ("generatedAt", "commit", "release", "contentSha256")


def encode_png(source: Path, size: tuple) -> bytes:
    from PIL import Image, ImageCms

    with Image.open(source) as opened:
        opened.load()
        profile = opened.info.get("icc_profile")
        image = opened.convert("RGBA")
    if profile:
        icc = ImageCms.ImageCmsProfile(io.BytesIO(profile))
        # The profile is not kept, and an untagged PNG is shown as sRGB.
        if icc.profile.xcolor_space.strip() == "RGB":
            alpha = image.getchannel("A")
            image = ImageCms.profileToProfile(image.convert("RGB"), icc, ImageCms.createProfile("sRGB"), outputMode="RGB")
            image.putalpha(alpha)
    if image.size != size:
        image = image.resize(size, Image.Resampling.LANCZOS)
    if image.getchannel("A").getextrema() == (255, 255):
        image = image.convert("RGB")
    clean = Image.frombytes(image.mode, image.size, image.tobytes())
    out = io.BytesIO()
    clean.save(out, format="PNG", optimize=True)
    return out.getvalue()


def write_image(out: Path, name: str, data: bytes, size: tuple) -> dict:
    digest = hashlib.sha256(data).hexdigest()
    file = f"{name}-{digest[:12]}.png"
    (out / file).write_bytes(data)
    return {"file": file, "width": size[0], "height": size[1], "sha256": digest}


def build_entry(entry: r.Entry, out: Path) -> dict:
    manifest = entry.manifest
    data = {k: v for k, v in manifest.items() if k not in SOURCE_ONLY}
    data["summarySha256"] = hashlib.sha256(manifest["summary"].encode("utf-8")).hexdigest()
    data["closedSource"] = manifest["source"]["type"] == "closed"
    data["license"] = manifest.get("license")
    url = r.source_url(manifest["source"])
    if url:
        data["source"] = dict(manifest["source"], url=url)
    data["install"] = dict(manifest["install"], url=r.install_url(manifest["install"]))
    icon = entry.directory / "icon.png"
    data["icon"] = {
        str(size): write_image(out, f"{entry.slug}-icon-{size}", encode_png(icon, (size, size)), (size, size))
        for size in ICON_SIZES
    }
    data["screenshots"] = [
        dict(write_image(out, f"{entry.slug}-{shot['file'][:-4]}", encode_png(entry.directory / shot["file"], r.SHOT_SIZE),
                         r.SHOT_SIZE), alt=shot["alt"])
        for shot in manifest.get("screenshots") or []
    ]
    return data


def content_digest(index: dict) -> str:
    content = {k: v for k, v in index.items() if k not in NOT_CONTENT}
    text = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fail(findings: list, reason: str) -> None:
    for finding in findings:
        print(f"error: {finding.file}: {finding.message}", file=sys.stderr)
    raise SystemExit(f"{reason}; nothing was built")


def build(root: Path, out: Path, commit: str, generated_at: str, release: Optional[str] = None) -> dict:
    if out.exists() and any(out.iterdir()):
        raise SystemExit(f"{out} is not empty")
    ctx = validate.run(root, dt.date.fromisoformat(generated_at[:10]))
    if ctx.report.errors:
        fail(ctx.report.errors, "the registry does not validate")
    out.mkdir(parents=True, exist_ok=True)
    try:
        return write(root, out, ctx, commit, generated_at, release)
    except BaseException:
        shutil.rmtree(out)
        raise


def write(root: Path, out: Path, ctx: validate.Context, commit: str, generated_at: str, release: Optional[str]) -> dict:
    index = {"schemaVersion": 1, "generatedAt": generated_at, "commit": commit}
    if release:
        index["release"] = release
    index["contentSha256"] = ""
    index["integrations"] = [build_entry(entry, out) for _, entry in sorted(ctx.entries.items())]
    index["removed"] = [{"slug": row["slug"], "removedAt": row["removedAt"], "reason": row["reason"]}
                        for row in ctx.curated("removed.json", "removed")]
    index["contentSha256"] = content_digest(index)
    report = r.Report()
    r.schema_errors(r.validator_for(root, r.INDEX_SCHEMA), index, "", "index.json", report)
    if report.errors:
        fail(report.errors, "index.json does not match schema/index.schema.json")
    (out / "index.json").write_bytes((json.dumps(index, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))
    names = sorted(p.name for p in out.iterdir())
    sums = "".join(f"{hashlib.sha256((out / name).read_bytes()).hexdigest()}  {name}\n" for name in names)
    (out / "SHA256SUMS").write_bytes(sums.encode("ascii"))
    return index


def main(argv: Optional[list] = None) -> int:
    parser = argparse.ArgumentParser(description="Build index.json, its images and SHA256SUMS for a release and Pages.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parent.parent))
    parser.add_argument("--out", default="build/dist", help="an empty or missing directory")
    parser.add_argument("--release", help="release tag, v1.YYYYMMDD.N")
    args = parser.parse_args(argv)
    root = Path(args.root)
    commit = validate.git(root, "rev-parse", "HEAD").strip()
    committed = dt.datetime.fromisoformat(validate.git(root, "log", "-1", "--format=%cI").strip())
    generated_at = committed.astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    index = build(root, Path(args.out), commit, generated_at, args.release)
    print(f"{len(index['integrations'])} entries, {len(index['removed'])} removed, contentSha256 {index['contentSha256']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
