from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import struct
import subprocess
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

SCHEMA_BASE = "https://integrations.tablepro.app/schema/v1/"
INTEGRATION_SCHEMA = SCHEMA_BASE + "integration.schema.json"
CURATION_SCHEMA = SCHEMA_BASE + "curation.schema.json"
INDEX_SCHEMA = SCHEMA_BASE + "index.schema.json"

CURATION_FILES = {
    "official-publishers.json": "officialPublishers",
    "partners.json": "partners",
    "reserved.json": "reserved",
    "removed.json": "removed",
    "protected-marks.json": "protectedMarks",
    "scan-allowlist.json": "scanAllowlist",
}

ENTRY_FILE = re.compile(r"^(?:integration\.json|icon\.png|screenshot-[1-4]\.png)$")
SLUG = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

ICON_SIZE = (512, 512)
ICON_MAX_BYTES = 512 * 1024
SHOT_SIZE = (1600, 1000)
SHOT_MAX_BYTES = 1024 * 1024
GRACE_MAX_DAYS = 60
SIMILAR_NAME_DISTANCE = 2

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"

# Characters that render as nothing or reorder text: zero-width, bidi controls, BOM.
INVISIBLE = re.compile("[\u200b-\u200f\u202a-\u202e\u2060-\u2069\ufeff]")

# Hosts that hide the real destination.
SHORTENER_HOSTS = {"bit.ly", "t.co", "tinyurl.com", "goo.gl", "ow.ly", "is.gd", "buff.ly", "rebrand.ly", "cutt.ly"}

SCAN_RULES = [
    ("app-support-dir", re.compile(r"Application Support/TablePro\b")),
    ("handshake-file", re.compile(r"mcp-handshake\.json")),
    ("audit-db", re.compile(r"mcp-audit\.db")),
    ("prefs-plist", re.compile(r"com\.TablePro\.plist")),
    ("prefs-keys", re.compile(r"com\.TablePro\.(?:connections|groups|tags)\b")),
    ("defaults-domain", re.compile(r"defaults\s+(?:read|export|write)\s+com\.TablePro\b")),
    ("keychain", re.compile(r"(?:find-(?:generic|internet)-password|kSecAttrService)[^\n]{0,120}com\.TablePro\b")),
]
SCAN_SKIP_DIRS = {".git", "node_modules"}
SCAN_MAX_FILE_BYTES = 2 * 1024 * 1024


@dataclass
class Finding:
    level: str
    file: str
    message: str
    line: int = 0


@dataclass
class Report:
    findings: list = field(default_factory=list)

    def error(self, file: str, message: str, line: int = 0) -> None:
        self.findings.append(Finding("error", file, message, line))

    def warning(self, file: str, message: str, line: int = 0) -> None:
        self.findings.append(Finding("warning", file, message, line))

    @property
    def errors(self) -> list:
        return [f for f in self.findings if f.level == "error"]

    @property
    def warnings(self) -> list:
        return [f for f in self.findings if f.level == "warning"]


@dataclass
class Entry:
    slug: str
    directory: Path
    manifest: Optional[dict]
    text: str
    load_error: Optional[str] = None

    @property
    def manifest_path(self) -> str:
        return f"integrations/{self.slug}/integration.json"


def read_json(path: Path) -> tuple:
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "", "file is missing"
    except UnicodeDecodeError:
        return None, "", "file is not UTF-8"
    try:
        return json.loads(text), text, None
    except json.JSONDecodeError as exc:
        return None, text, f"invalid JSON at line {exc.lineno}: {exc.msg}"


def schema_registry(root: Path) -> Registry:
    resources = []
    for name in ("integration.schema.json", "curation.schema.json", "index.schema.json"):
        data = json.loads((root / "schema" / name).read_text(encoding="utf-8"))
        resources.append((data["$id"], Resource.from_contents(data)))
    return Registry().with_resources(resources)


def validator_for(root: Path, ref: str) -> Draft202012Validator:
    registry = schema_registry(root)
    return Draft202012Validator(
        {"$ref": ref},
        registry=registry,
        format_checker=Draft202012Validator.FORMAT_CHECKER,
    )


def check_schema_files(root: Path, report: Report) -> None:
    for path in sorted((root / "schema").glob("*.json")):
        data, _, error = read_json(path)
        rel = f"schema/{path.name}"
        if error:
            report.error(rel, error)
            continue
        try:
            Draft202012Validator.check_schema(data)
        except Exception as exc:
            report.error(rel, f"not a valid draft 2020-12 schema: {getattr(exc, 'message', exc)}")


def line_of(text: str, path: Iterable) -> int:
    keys = [p for p in path if isinstance(p, str)]
    if not keys:
        return 1
    match = re.search(r'"' + re.escape(keys[-1]) + r'"\s*:', text)
    return text.count("\n", 0, match.start()) + 1 if match else 1


def schema_errors(validator: Draft202012Validator, data: Any, text: str, file: str, report: Report) -> int:
    count = 0
    for error in sorted(validator.iter_errors(data), key=lambda e: list(e.absolute_path)):
        if error.validator in ("allOf", "if") and error.context:
            continue
        where = "/".join(str(p) for p in error.absolute_path) or "(root)"
        report.error(file, f"{where}: {error.message}", line_of(text, error.absolute_path))
        count += 1
    return count


def load_curation(root: Path, report: Report) -> dict:
    curation = {}
    for name, definition in CURATION_FILES.items():
        path = root / "curation" / name
        rel = f"curation/{name}"
        data, text, error = read_json(path)
        if error:
            report.error(rel, error)
            continue
        validator = validator_for(root, f"{CURATION_SCHEMA}#/$defs/{definition}")
        schema_errors(validator, data, text, rel, report)
        curation[name] = data
    return curation


def load_entries(root: Path) -> dict:
    entries = {}
    base = root / "integrations"
    if not base.is_dir():
        return entries
    for directory in sorted(p for p in base.iterdir() if p.is_dir()):
        data, text, error = read_json(directory / "integration.json")
        entries[directory.name] = Entry(directory.name, directory, data, text, error)
    return entries


def name_tokens(value: str) -> list:
    value = unicodedata.normalize("NFKC", value)
    value = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", value)
    value = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1 \2", value)
    return [t for t in re.split(r"[^0-9A-Za-z]+", value.casefold()) if t]


def contains_fragment(value: str, fragment: str) -> bool:
    tokens = name_tokens(value)
    for size in (1, 2, 3):
        for start in range(0, len(tokens) - size + 1):
            if "".join(tokens[start:start + size]) == fragment:
                return True
    return False


def normalized_name(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", unicodedata.normalize("NFKC", value).casefold())


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def unsafe_characters(value: str) -> list:
    found = []
    for char in value:
        category = unicodedata.category(char)
        if INVISIBLE.match(char) or category in ("Cf", "Co", "Cs", "Cn"):
            found.append(f"U+{ord(char):04X}")
        elif category == "So":
            found.append(f"U+{ord(char):04X} (symbol or emoji)")
    return found


def parse_date(value: str) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def png_chunks(data: bytes) -> list:
    chunks = []
    offset = len(PNG_SIGNATURE)
    while offset + 8 <= len(data):
        (length,) = struct.unpack(">I", data[offset:offset + 4])
        kind = data[offset + 4:offset + 8].decode("latin-1")
        chunks.append(kind)
        offset += 12 + length
        if kind == "IEND":
            break
    return chunks


def check_png(path: Path, size: tuple, max_bytes: int) -> list:
    problems = []
    data = path.read_bytes()
    if len(data) > max_bytes:
        problems.append(f"is {len(data) // 1024} KB, over the {max_bytes // 1024} KB limit")
    if not data.startswith(PNG_SIGNATURE):
        return problems + ["is not a PNG file"]
    if "acTL" in png_chunks(data):
        problems.append("is an animated PNG")
    from PIL import Image

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            if image.format != "PNG":
                problems.append(f"decodes as {image.format}, not PNG")
            if image.size != size:
                problems.append(f"is {image.size[0]}x{image.size[1]}, expected {size[0]}x{size[1]}")
            if image.mode not in ("RGB", "RGBA", "P", "LA", "L"):
                problems.append(f"uses color mode {image.mode}")
    except Exception as exc:
        problems.append(f"does not decode: {exc}")
    return problems


def mark_hash(path: Path) -> str:
    from PIL import Image

    with Image.open(path) as source:
        image = source.convert("RGBA")
    alpha = image.getchannel("A").point(lambda v: 255 if v > 200 else 0)
    box = alpha.getbbox() or (0, 0) + image.size
    image = image.crop(box)
    flat = Image.new("RGBA", image.size, (255, 255, 255, 255))
    flat.alpha_composite(image)
    pixels = flat.convert("L").resize((17, 16), Image.Resampling.LANCZOS).tobytes()
    bits = [pixels[r * 17 + c] > pixels[r * 17 + c + 1] for r in range(16) for c in range(16)]
    value = 0
    for bit in bits:
        value = (value << 1) | int(bit)
    return f"{value:064x}"


def hash_distance(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def collect_urls(value: Any) -> list:
    urls = []
    if isinstance(value, dict):
        for item in value.values():
            urls.extend(collect_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(collect_urls(item))
    elif isinstance(value, str) and value.startswith(("http://", "https://")):
        urls.append(value)
    return urls


def install_url(install: dict) -> str:
    kind = install.get("type")
    if kind == "built-in":
        return install["docs"]
    if kind == "vscode-marketplace":
        return "https://marketplace.visualstudio.com/items?itemName=" + install["id"]
    if kind == "homebrew":
        return f"https://formulae.brew.sh/{install['kind']}/{install['token']}"
    return install["url"]


def source_url(source: dict) -> Optional[str]:
    if source.get("type") != "github":
        return None
    url = f"https://github.com/{source['repo']}"
    if source.get("path"):
        url += "/tree/HEAD/" + source["path"]
    return url


def scan_tree(root: Path, rules: Optional[list] = None) -> list:
    hits = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SCAN_SKIP_DIRS]
        for filename in filenames:
            path = Path(dirpath) / filename
            try:
                if path.is_symlink() or path.stat().st_size > SCAN_MAX_FILE_BYTES:
                    continue
                data = path.read_bytes()
            except OSError:
                continue
            if b"\x00" in data[:8192]:
                continue
            text = data.decode("utf-8", errors="replace")
            for rule, pattern in rules or SCAN_RULES:
                match = pattern.search(text)
                if match:
                    line = text.count("\n", 0, match.start()) + 1
                    hits.append((str(path.relative_to(root)), line, rule, match.group(0)))
    return hits


def fetch_source(repo: str, path: Optional[str], destination: Path) -> Path:
    url = f"https://github.com/{repo}.git"
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1")
    base = ["git", "-c", "core.symlinks=false", "-c", "protocol.file.allow=never"]
    clone = base + ["clone", "--quiet", "--depth", "1", "--no-tags", "--filter=blob:none"]
    if path:
        clone += ["--sparse"]
    subprocess.run(clone + [url, str(destination)], check=True, env=env, timeout=600)
    if path:
        subprocess.run(base + ["-C", str(destination), "sparse-checkout", "set", "--no-cone", "/" + path],
                       check=True, env=env, timeout=600)
        return destination / path
    return destination


class GitHub:
    def __init__(self, token: Optional[str] = None, opener: Optional[Callable] = None):
        self.token = token if token is not None else os.environ.get("GITHUB_TOKEN", "")
        self.opener = opener or urllib.request.urlopen

    def get(self, path: str) -> tuple:
        request = urllib.request.Request("https://api.github.com" + path)
        request.add_header("Accept", "application/vnd.github+json")
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
        request.add_header("User-Agent", "tablepro-integrations-validator")
        if self.token:
            request.add_header("Authorization", "Bearer " + self.token)
        try:
            with self.opener(request, timeout=30) as response:
                body = response.read()
                return response.status, json.loads(body) if body else None
        except urllib.error.HTTPError as exc:
            exc.close()
            return exc.code, None

    def repository(self, repo_id: int) -> tuple:
        return self.get(f"/repositories/{repo_id}")

    def license(self, repo: str) -> tuple:
        return self.get(f"/repos/{repo}/license")

    def user(self, login: str) -> tuple:
        return self.get(f"/users/{urllib.parse.quote(login)}")

    def contents(self, repo: str, path: str) -> tuple:
        return self.get(f"/repos/{repo}/contents/{urllib.parse.quote(path)}")

    def latest_release(self, repo: str) -> tuple:
        return self.get(f"/repos/{repo}/releases/latest")

    def contributors(self, repo: str) -> tuple:
        return self.get(f"/repos/{repo}/contributors?per_page=100")

    def public_member(self, org: str, login: str) -> bool:
        status, _ = self.get(f"/orgs/{org}/public_members/{urllib.parse.quote(login)}")
        return status == 204

    def issue(self, repo: str, number: int) -> tuple:
        return self.get(f"/repos/{repo}/issues/{number}")


def http_status(url: str, method: str = "GET", opener: Optional[Callable] = None) -> int:
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", "Mozilla/5.0 (compatible; tablepro-integrations-validator)")
    try:
        with (opener or urllib.request.urlopen)(request, timeout=30) as response:
            return response.status
    except urllib.error.HTTPError as exc:
        exc.close()
        return exc.code
    except (urllib.error.URLError, TimeoutError, OSError):
        return 0
