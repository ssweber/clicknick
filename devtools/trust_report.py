"""Build the ClickNick trust report: a one-page, self-contained HTML release report.

Inputs: ``uv.lock`` (via ``uv export --format cyclonedx1.5``), ``uv audit``, the
installed distribution metadata of the current environment, the runtime source
tree, and optionally the built wheel.

Outputs (in ``--out``): ``clicknick-trust-report-<version>.html`` and
``clicknick-sbom-<version>.cyclonedx.json``.

Run with ``make trust-report``. Exits non-zero when any release check fails, so a
release cannot ship with a red check.

The "For IT / security review" narrative is rendered from the marked sections of
``docs/security/index.md`` in this checkout. A release therefore captures the
narrative from its tagged source, alongside the generated release evidence.
"""

from __future__ import annotations

import argparse
import ast
import datetime as dt
import hashlib
import html
import importlib.metadata as md
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from markdown import Markdown
from markdown.treeprocessors import Treeprocessor

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "clicknick"
PROJECT = "clicknick"

# ---- Handwritten, release-stable content -----------------------------------

FIRST_PARTY = {
    "clicknick": "https://github.com/ssweber/clicknick",
    "pyrung": "https://github.com/ssweber/pyrung",
    "pyclickplc": "https://github.com/ssweber/pyclickplc",
    "laddercodec": "https://github.com/ssweber/laddercodec",
}

# Every runtime distribution must have an entry here; a missing one fails a check.
PURPOSES = {
    "clicknick": "Application",
    "pyrung": "PLC program model: offline run and static checks",
    "pyclickplc": "CLICK project formats, address model, Modbus access",
    "laddercodec": "Ladder diagram codec (read/write CLICK ladder)",
    "pyodbc": "ODBC access to the CLICK project database",
    "pywin32": "Windows API (window detection, overlay placement)",
    "tksheet": "Spreadsheet widget for the Address Editor",
    "pymodbus": "Modbus TCP protocol (used by pyclickplc)",
    "executing": "Python source introspection (used by pyrung)",
    "pyrsistent": "Immutable data structures (used by pyrung)",
    "tomlkit": "TOML editing that preserves formatting for check settings (used by pyrung)",
}

# Package names that would indicate an HTTP client or a telemetry SDK.
HTTP_CLIENT_DISTS = {
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "httpcore",
    "pycurl",
    "websockets",
    "websocket-client",
    "treq",
    "niquests",
    "h2",
}
TELEMETRY_DISTS = {
    "sentry-sdk",
    "posthog",
    "segment-analytics-python",
    "analytics-python",
    "mixpanel",
    "amplitude-analytics",
    "datadog",
    "ddtrace",
    "newrelic",
    "bugsnag",
    "rollbar",
    "raygun4py",
    "honeybadger",
    "applicationinsights",
    "azure-monitor-opentelemetry",
    "elastic-apm",
    "scout-apm",
    "launchdarkly-server-sdk",
    "statsig",
}
TELEMETRY_PREFIXES = ("opentelemetry", "sentry", "google-analytics")

# Stdlib network client modules that must not appear in runtime imports.
NETWORK_CLIENT_MODULES = {
    "urllib.request",
    "http.client",
    "ftplib",
    "smtplib",
    "telnetlib",
    "xmlrpc.client",
    "poplib",
    "imaplib",
    "nntplib",
    "requests",
    "httpx",
    "aiohttp",
    "urllib3",
    "websocket",
    "websockets",
}

# Hosts that may appear as URLs in runtime source. They are documentation links
# handed to the user's browser, never contacted by ClickNick itself.
ALLOWED_URL_HOSTS = {"github.com", "pyrung.com"}

DECODERS = {
    "b64decode",
    "a85decode",
    "b85decode",
    "decompress",
    "loads",
    "fromhex",
    "unhexlify",
    "decode",
}
DECODER_MODULES = {"base64", "zlib", "marshal", "binascii", "lzma", "bz2", "gzip", "codecs"}
EXECUTORS = {"exec", "eval", "compile"}

DOWNLOAD_PATTERNS = re.compile(
    r"Invoke-WebRequest|Invoke-RestMethod|Net\.WebClient|DownloadFile|DownloadString|"
    r"Start-BitsTransfer|\bcurl\b|\bwget\b|certutil|bitsadmin",
    re.IGNORECASE,
)

URL_RE = re.compile(r"https?://([A-Za-z0-9.-]+)[^\s\"'<>)]*")

BINARY_SUFFIXES = {".exe", ".dll", ".pyd", ".so", ".dylib", ".pyc", ".bat", ".cmd", ".msi"}


@dataclass
class Check:
    label: str
    passed: bool
    detail: str = ""


@dataclass
class Dist:
    name: str
    version: str
    source: str
    license: str
    direct: bool
    purpose: str
    native: str
    homepage: str
    requirement: str = ""
    used_by: str = ""
    depends_on: list[str] = field(default_factory=list)

    @property
    def first_party(self) -> bool:
        return self.name in FIRST_PARTY


@dataclass
class Report:
    version: str
    python_requires: str
    commit: str
    generated: str
    uv_version: str
    dists: list[Dist]
    checks: list[Check]
    vulnerabilities: list[dict] | None  # None = audit not run
    audited_packages: int
    sbom_sha256: str
    sbom_name: str
    wheel_name: str | None
    wheel_sha256: str | None
    sidecar_sha256: str
    is_release: bool
    urls_found: list[tuple[str, str]]
    subprocess_targets: list[tuple[str, str]]
    dynamic_exec: list[tuple[str, str]]


# ---- Helpers ----------------------------------------------------------------


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, check=False, **kwargs)


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def git_commit() -> str:
    result = run(["git", "rev-parse", "HEAD"])
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def resolve_license(name: str) -> str:
    try:
        meta = md.metadata(name)
    except md.PackageNotFoundError:
        return "UNRESOLVED (not installed)"
    expr = meta.get("License-Expression")
    if expr:
        return expr.strip()
    lic = (meta.get("License") or "").strip()
    if lic and "\n" not in lic and len(lic) <= 40:
        return lic
    for classifier in meta.get_all("Classifier") or []:
        if classifier.startswith("License ::"):
            return classifier.split("::")[-1].strip()
    return "UNRESOLVED"


def resolve_homepage(name: str) -> str:
    if name in FIRST_PARTY:
        return FIRST_PARTY[name]
    try:
        meta = md.metadata(name)
    except md.PackageNotFoundError:
        return ""
    urls = {}
    for entry in meta.get_all("Project-URL") or []:
        label, _, url = entry.partition(",")
        urls[label.strip().lower()] = url.strip()
    for key in ("repository", "source code", "source", "homepage", "documentation"):
        if key in urls:
            return urls[key]
    return meta.get("Home-page") or ""


def native_summary(name: str) -> str:
    """Describe compiled files inside the installed distribution (not launcher stubs)."""
    try:
        files = md.files(name) or []
    except md.PackageNotFoundError:
        return "?"
    counts: dict[str, int] = {}
    for f in files:
        parts = f.parts
        if parts and parts[0] == "..":  # Scripts/ launcher stubs made by the installer
            continue
        suffix = f.suffix.lower()
        if suffix in {".pyd", ".dll", ".exe", ".so"}:
            counts[suffix] = counts.get(suffix, 0) + 1
    if not counts:
        return "no"
    return "yes (" + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())) + ")"


# ---- Collection -------------------------------------------------------------


def load_sbom(uv: str) -> tuple[bytes, dict]:
    result = run([uv, "export", "--frozen", "--no-dev", "--format", "cyclonedx1.5"])
    if result.returncode != 0:
        sys.exit(f"uv export failed:\n{result.stderr}")
    return result.stdout.encode("utf-8"), json.loads(result.stdout)


def load_lock() -> dict[str, dict]:
    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    return {norm(p["name"]): p for p in lock["package"]}


def describe_source(pkg: dict) -> str:
    source = pkg.get("source", {})
    if "registry" in source:
        return "PyPI" if "pypi.org" in source["registry"] else source["registry"]
    if "editable" in source or "virtual" in source:
        return "This repository"
    for key in ("git", "url", "path", "directory"):
        if key in source:
            return f"{key}: {source[key]}"
    return "unknown"


def requirement_specs(pyproject: dict) -> dict[str, str]:
    """Map normalized direct dependency name -> version specifier from pyproject."""
    specs: dict[str, str] = {}
    for req in pyproject["project"].get("dependencies", []):
        m = re.match(r"\s*([A-Za-z0-9._-]+)\s*(\[[^\]]*\])?\s*(.*)$", req)
        if m:
            specs[norm(m.group(1))] = m.group(3).strip().replace(" ", "") or "any"
    return specs


def runtime_sources(src_dir: Path = SRC) -> list[Path]:
    return sorted(
        p
        for p in src_dir.rglob("*")
        if p.suffix in {".py", ".ps1"} and "__pycache__" not in p.parts
    )


def imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
            names.update(f"{node.module}.{alias.name}" for alias in node.names)
    return names


def dists_imported_by_project(src_dir: Path = SRC) -> set[str]:
    """Normalized names of distributions whose modules ClickNick's own source imports."""
    top_level: set[str] = set()
    for path in runtime_sources(src_dir):
        if path.suffix != ".py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        top_level.update(m.split(".")[0] for m in imported_modules(tree))
    module_to_dists = md.packages_distributions()
    return {norm(d) for mod in top_level for d in module_to_dists.get(mod, [])}


def collect_dists(
    sbom: dict, lock: dict[str, dict], version: str, specs: dict[str, str] | None = None
) -> list[Dist]:
    specs = specs or {}
    imported = dists_imported_by_project()
    refs = {c["bom-ref"]: c for c in sbom["components"]}
    deps = {d["ref"]: d.get("dependsOn", []) for d in sbom.get("dependencies", [])}
    root_ref = sbom["metadata"]["component"]["bom-ref"]
    direct = {norm(refs[r]["name"]) for r in deps.get(root_ref, []) if r in refs}

    parents: dict[str, list[str]] = {}
    for ref, children in deps.items():
        if ref in refs:
            for child in children:
                if child in refs:
                    parents.setdefault(norm(refs[child]["name"]), []).append(refs[ref]["name"])

    def make(name: str, ver: str, depends: list[str]) -> Dist:
        key = norm(name)
        requirement = "" if key == norm(PROJECT) else specs.get(key, "not listed")
        users = sorted({u for u in parents.get(key, []) if u != PROJECT})
        if key in imported:
            users.insert(0, "ClickNick")
        used_by = "" if key == norm(PROJECT) else (", ".join(users) or "ClickNick")
        return Dist(
            name=name,
            version=ver,
            source=describe_source(lock.get(key, {})),
            license=resolve_license(name),
            direct=key in direct,
            purpose=PURPOSES.get(key, ""),
            native=native_summary(name),
            homepage=resolve_homepage(name),
            requirement=requirement,
            used_by=used_by,
            depends_on=sorted(depends),
        )

    dists = [make(PROJECT, version, sorted(refs[r]["name"] for r in deps.get(root_ref, [])))]
    for comp in sorted(sbom["components"], key=lambda c: c["name"].lower()):
        depends = [refs[r]["name"] for r in deps.get(comp["bom-ref"], []) if r in refs]
        dists.append(make(comp["name"], comp.get("version", "?"), depends))
    return dists


def run_audit(uv: str, runtime_names: set[str]) -> tuple[list[dict] | None, int]:
    result = run(
        [uv, "audit", "--frozen", "--no-dev", "--no-group", "docs", "--output-format", "json"]
    )
    if result.returncode not in (0, 1) or not result.stdout.strip():
        print(f"warning: uv audit did not run cleanly:\n{result.stderr}", file=sys.stderr)
        return None, 0
    data = json.loads(result.stdout)
    vulns = [
        v for v in data.get("vulnerabilities", []) if norm(v["dependency"]["name"]) in runtime_names
    ]
    return vulns, int(data.get("summary", {}).get("audited_packages", 0))


def rel(path: Path, root: Path = ROOT) -> str:
    return path.relative_to(root).as_posix()


def call_name(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        base = func.value
        prefix = base.id if isinstance(base, ast.Name) else "?"
        return f"{prefix}.{func.attr}"
    return ""


def first_argv_element(node: ast.Call, scope: ast.AST) -> str:
    """Render the first element of a subprocess argv list for reporting.

    A bare variable is resolved to the last list assigned to that name inside
    the enclosing function, so ``argv = [...]; Popen(argv)`` is inspected too.
    """
    if not node.args:
        return "(no positional argv)"
    first = node.args[0]
    if isinstance(first, ast.Name):
        assigned = [
            n.value
            for n in ast.walk(scope)
            if isinstance(n, ast.Assign)
            and n.lineno < node.lineno
            and any(isinstance(t, ast.Name) and t.id == first.id for t in n.targets)
        ]
        if not assigned:
            return f"variable {first.id} (unresolved)"
        first = assigned[-1]
    if isinstance(first, ast.List | ast.Tuple) and first.elts:
        first = first.elts[0]
    return ast.unparse(first)


def docstring_nodes(tree: ast.AST) -> set[int]:
    ids: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                ids.add(id(body[0].value))
    return ids


def enclosing_scopes(tree: ast.AST) -> dict[int, ast.AST]:
    """Map id(node) -> nearest enclosing function (or module) node."""
    scopes: dict[int, ast.AST] = {}

    def visit(node: ast.AST, scope: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            scopes[id(child)] = scope
            inner = child if isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef) else scope
            visit(child, inner)

    visit(tree, tree)
    return scopes


def scan_sources(
    dists: list[Dist], src_dir: Path = SRC, root: Path = ROOT
) -> tuple[list[Check], list, list, list]:
    checks: list[Check] = []
    urls: list[tuple[str, str]] = []
    subprocess_targets: list[tuple[str, str]] = []
    dynamic_exec: list[tuple[str, str]] = []
    bad_imports: list[str] = []
    bad_subprocess: list[str] = []
    decode_exec: list[str] = []
    downloads: list[str] = []
    listeners: list[str] = []
    bad_listeners: list[str] = []

    for path in runtime_sources(src_dir):
        loc = rel(path, root)
        text = path.read_text(encoding="utf-8", errors="replace")
        if DOWNLOAD_PATTERNS.search(text):
            downloads.append(loc)
        if path.suffix != ".py":
            # PowerShell: scan everything except comment lines.
            code_only = "\n".join(
                line for line in text.splitlines() if not line.lstrip().startswith("#")
            )
            for m in URL_RE.finditer(code_only):
                urls.append((loc, m.group(0)))
            continue
        tree = ast.parse(text, filename=str(path))
        # URLs in string literals only: comments and docstrings are not runtime data.
        skip = docstring_nodes(tree)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and id(node) not in skip
            ):
                for m in URL_RE.finditer(node.value):
                    urls.append((f"{loc}:{node.lineno}", m.group(0)))
        scopes = enclosing_scopes(tree)
        mods = imported_modules(tree)
        for mod in sorted(mods):
            if mod in NETWORK_CLIENT_MODULES or mod.split(".")[0] in NETWORK_CLIENT_MODULES:
                bad_imports.append(f"{loc}: {mod}")
        decoders_used: list[str] = []
        executors_used: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = call_name(node)
            short = name.split(".")[-1]
            if short in EXECUTORS and (name == short or name.startswith("builtins.")):
                executors_used.append(name)
                if short != "compile":  # compile() alone runs nothing; exec/eval is the event
                    dynamic_exec.append((f"{loc}:{node.lineno}", ast.unparse(node)[:90]))
            if short in DECODERS and (
                name.split(".")[0] in DECODER_MODULES
                or short in {"b64decode", "fromhex"}
                or any(f"{m}.{short}" in mods for m in DECODER_MODULES)
            ):
                decoders_used.append(name)
            if name in {
                "subprocess.run",
                "subprocess.Popen",
                "subprocess.call",
                "subprocess.check_call",
                "subprocess.check_output",
                "Popen",
            }:
                target = first_argv_element(node, scopes.get(id(node), tree))
                subprocess_targets.append((f"{loc}:{node.lineno}", target))
                if target not in {"sys.executable", "str(powershell_path())"}:
                    bad_subprocess.append(f"{loc}:{node.lineno} -> {target}")
            if short in {"Listener", "bind"} and node.args:
                addr = node.args[0]
                host = None
                if isinstance(addr, ast.Tuple) and addr.elts:
                    host = addr.elts[0]
                if isinstance(host, ast.Constant) and host.value in {"localhost", "127.0.0.1"}:
                    listeners.append(f"{loc}:{node.lineno} ({host.value})")
                elif short == "Listener" or isinstance(host, ast.Constant):
                    bad_listeners.append(f"{loc}:{node.lineno}: {ast.unparse(node)[:80]}")
        if decoders_used and executors_used:
            decode_exec.append(
                f"{loc}: {sorted(set(decoders_used))} + {sorted(set(executors_used))}"
            )

    runtime_names = {norm(d.name) for d in dists}
    http_hits = sorted(runtime_names & HTTP_CLIENT_DISTS)
    telemetry_hits = sorted(
        n for n in runtime_names if n in TELEMETRY_DISTS or n.startswith(TELEMETRY_PREFIXES)
    )
    hosts = {m.group(1) for _, u in urls if (m := URL_RE.match(u))}
    foreign_hosts = sorted(hosts - ALLOWED_URL_HOSTS)

    checks.append(
        Check(
            "No HTTP client dependency (requests, httpx, aiohttp, urllib3, ...)",
            not http_hits,
            "found: " + ", ".join(http_hits)
            if http_hits
            else "none of the known HTTP client packages in the runtime set",
        )
    )
    checks.append(
        Check(
            "No telemetry or analytics SDK dependency",
            not telemetry_hits,
            "found: " + ", ".join(telemetry_hits)
            if telemetry_hits
            else "none of the known telemetry SDKs in the runtime set",
        )
    )
    checks.append(
        Check(
            "No HTTP, FTP or mail client imports in runtime source",
            not bad_imports,
            "; ".join(bad_imports)
            if bad_imports
            else "no urllib.request, http.client, ftplib, smtplib or third-party HTTP imports",
        )
    )
    checks.append(
        Check(
            "No external runtime endpoints",
            not foreign_hosts and not bad_imports,
            "unexpected hosts: " + ", ".join(foreign_hosts)
            if foreign_hosts
            else f"every URL in runtime source points at {' or '.join(sorted(ALLOWED_URL_HOSTS))} (browser links, listed below)",
        )
    )
    checks.append(
        Check(
            "Local listeners bind to localhost only",
            bool(listeners) and not bad_listeners,
            "; ".join(bad_listeners)
            if bad_listeners
            else "; ".join(listeners) or "no listeners found",
        )
    )
    checks.append(
        Check(
            "Subprocesses launch only the same Python interpreter or the built-in Windows PowerShell",
            not bad_subprocess,
            "; ".join(bad_subprocess)
            if bad_subprocess
            else f"{len(subprocess_targets)} launch sites, all sys.executable or powershell_path()",
        )
    )
    checks.append(
        Check(
            "No download commands in shipped scripts",
            not downloads,
            "found in: " + ", ".join(downloads)
            if downloads
            else "no Invoke-WebRequest, WebClient, BitsTransfer, curl or wget",
        )
    )
    checks.append(
        Check(
            "No Python decoded at runtime (base64/zlib/marshal fed to exec/eval/compile)",
            not decode_exec,
            "; ".join(decode_exec)
            if decode_exec
            else "no module both decodes a blob and executes it; the PowerShell worker is Base64 of a shipped .ps1, hashed above",
        )
    )
    return checks, urls, subprocess_targets, dynamic_exec


def wheel_checks(wheel: Path | None) -> tuple[Check, dict[str, int]]:
    if wheel is None:
        return Check(
            "Wheel contains no compiled code or executables", False, "no wheel given (--wheel)"
        ), {}
    counts: dict[str, int] = {}
    with zipfile.ZipFile(wheel) as zf:
        names = [n for n in zf.namelist() if not n.endswith("/")]
    for n in names:
        suffix = Path(n).suffix.lower() or "(none)"
        counts[suffix] = counts.get(suffix, 0) + 1
    binaries = sorted(n for n in names if Path(n).suffix.lower() in BINARY_SUFFIXES)
    detail = (
        "found: " + ", ".join(binaries)
        if binaries
        else f"{len(names)} files: " + ", ".join(f"{c} {s}" for s, c in sorted(counts.items()))
    )
    return Check("Wheel contains no compiled code or executables", not binaries, detail), counts


def dependency_checks(dists: list[Dist], vulns: list[dict] | None) -> list[Check]:
    non_pypi = [d.name for d in dists if d.name != PROJECT and d.source != "PyPI"]
    unresolved = [d.name for d in dists if d.license.startswith("UNRESOLVED")]
    no_purpose = [d.name for d in dists if not d.purpose]
    checks = [
        Check(
            "All third-party dependencies come from PyPI",
            not non_pypi,
            "non-PyPI: " + ", ".join(non_pypi)
            if non_pypi
            else f"{len(dists) - 1} distributions, all from pypi.org",
        ),
        Check(
            "Every runtime distribution has a resolved license",
            not unresolved,
            "unresolved: " + ", ".join(unresolved)
            if unresolved
            else "license expression or classifier found for each",
        ),
        Check(
            "Every runtime distribution has a documented purpose",
            not no_purpose,
            "missing purpose entry: " + ", ".join(no_purpose)
            if no_purpose
            else "purpose column filled from PURPOSES in devtools/trust_report.py",
        ),
    ]
    unpinned = [
        f"{d.name} (locked {d.version}, requirement {d.requirement or 'none'})"
        for d in dists
        if d.name != PROJECT and d.requirement != f"=={d.version}"
    ]
    checks.append(
        Check(
            "Every runtime distribution is pinned exactly in pyproject.toml to its locked version",
            not unpinned,
            "; ".join(unpinned)
            if unpinned
            else f"{len(dists) - 1} distributions pinned with ==; a fresh install matches this table",
        )
    )
    if vulns is None:
        checks.append(Check("No known vulnerabilities (uv audit)", False, "uv audit did not run"))
    else:
        detail = "; ".join(
            f"{v['dependency']['name']} {v['dependency']['version']}: {v['display_id']}"
            for v in vulns
        )
        checks.append(
            Check(
                "No known vulnerabilities (uv audit)",
                not vulns,
                detail or "advisory database reports none for the runtime set",
            )
        )
    return checks


# ---- Rendering --------------------------------------------------------------

CSS = """
body{font:15px/1.5 system-ui,Segoe UI,Arial,sans-serif;color:#1c2420;background:#fff;margin:0}
main{max-width:960px;margin:0 auto;padding:2rem 1.5rem 4rem}
h1{font-size:1.7rem;margin:0 0 .2rem}h2{font-size:1.2rem;margin:2.2rem 0 .6rem;border-bottom:2px solid #17653a;padding-bottom:.2rem}
h3{font-size:1rem;margin:1.4rem 0 .4rem}
.sub{color:#5b665f;margin:0 0 1.5rem}
table{border-collapse:collapse;width:100%;font-size:.92rem;margin:.6rem 0}
th,td{border:1px solid #d9e3dc;padding:.35rem .55rem;text-align:left;vertical-align:top}
th{background:#eaf5ee}
.wrap{overflow-x:auto}
code,.mono{font-family:Consolas,Menlo,monospace;font-size:.9em}
.hash{word-break:break-all}
ul{padding-left:1.3rem}li{margin:.25rem 0}
.ok{color:#17653a;font-weight:700}.bad{color:#b3261e;font-weight:700}
.checks li{list-style:none;margin:.4rem 0}.checks .d{display:block;color:#5b665f;font-size:.86rem;margin-left:1.6rem}
.kv td:first-child{width:38%;color:#5b665f}
.note{background:#f7f9f7;border:1px solid #d9e3dc;border-radius:.4rem;padding:.7rem .9rem;font-size:.92rem}
@media print{main{padding:0}h2{page-break-after:avoid}}
"""


def esc(value: object) -> str:
    return html.escape(str(value))


class SecurityNarrativeLinks(Treeprocessor):
    """Keep documentation links usable when the report is opened as a local file."""

    def run(self, root):
        for element in root.iter():
            if element.tag in {"h2", "h3", "h4", "h5"}:
                element.tag = f"h{int(element.tag[1]) + 1}"
            if element.tag != "a":
                continue
            target = urlsplit(element.get("href", ""))
            if target.scheme or target.netloc:
                continue
            path = target.path
            if path.endswith(".md"):
                path = (
                    (path[:-8] or "./")
                    if path.rsplit("/", 1)[-1] == "index.md"
                    else path[:-3] + "/"
                )
            absolute = urljoin(
                "https://pyrung.com/clicknick/security/",
                urlunsplit(target._replace(path=path)),
            )
            element.set("href", absolute)


def render_security_narrative(path: Path | None = None) -> str:
    """Read the local source, never the live website or a previous release report."""
    source = (path or ROOT / "docs/security/index.md").read_text(encoding="utf-8")
    start = "<!-- trust-report:start -->"
    end = "<!-- trust-report:end -->"
    if not source.count(start) or source.count(start) != source.count(end):
        raise ValueError("Security page must contain matching trust-report markers")
    sections = []
    parts = source.split(start)
    if end in parts[0]:
        raise ValueError("Security page has out-of-order trust-report markers")
    for part in parts[1:]:
        body, marker, remainder = part.partition(end)
        if not marker or end in remainder or not body.strip():
            raise ValueError("Security page has empty or out-of-order trust-report markers")
        sections.append(body.strip())
    renderer = Markdown(extensions=["tables", "fenced_code"])
    renderer.treeprocessors.register(SecurityNarrativeLinks(renderer), "report_links", 0)
    return renderer.convert("\n\n".join(sections))


def render_checks(checks: list[Check]) -> str:
    items = []
    for c in checks:
        mark = (
            '<span class="ok">&#10003;</span>' if c.passed else '<span class="bad">&#10007;</span>'
        )
        items.append(f"<li>{mark} {esc(c.label)}<span class='d'>{esc(c.detail)}</span></li>")
    return "<ul class='checks'>" + "".join(items) + "</ul>"


def render(rep: Report) -> str:
    checkout_ref = (
        f"v{rep.version}" if rep.is_release else f"{rep.commit}  # development build, no tag"
    )
    first = [d for d in rep.dists if d.first_party]
    third = [d for d in rep.dists if not d.first_party]
    failed = [c for c in rep.checks if not c.passed]
    vuln_count = "not run" if rep.vulnerabilities is None else str(len(rep.vulnerabilities))
    wheel_row = (
        f"<tr><td>Wheel SHA256 ({esc(rep.wheel_name)})</td><td class='mono hash'>{esc(rep.wheel_sha256)}</td></tr>"
        if rep.wheel_name
        else "<tr><td>Wheel SHA256</td><td>no wheel built for this report</td></tr>"
    )
    status = (
        "<p class='ok'>All release checks passed.</p>"
        if not failed
        else f"<p class='bad'>{len(failed)} release check(s) failed. This build must not be released.</p>"
    )
    if not rep.is_release:
        status += (
            "<p class='bad'>Development build, not a release. Version numbers and hashes here "
            "belong to an untagged commit; use the report attached to a tagged release for review.</p>"
        )

    rows = []
    for d in rep.dists:
        link = f"<a href='{esc(d.homepage)}'>{esc(d.name)}</a>" if d.homepage else esc(d.name)
        source = "First-party" if d.first_party and d.name != PROJECT else d.source
        if d.name == PROJECT:
            source = "This release"
        rows.append(
            "<tr>"
            f"<td>{link}</td><td class='mono'>{esc(d.version)}</td>"
            f"<td class='mono'>{esc(d.requirement)}</td><td>{esc(source)}</td>"
            f"<td>{esc(d.license)}</td><td>{esc(d.used_by)}</td>"
            f"<td>{esc(d.native)}</td><td>{esc(d.purpose) or '<span class=bad>missing</span>'}</td>"
            "</tr>"
        )

    tree_lines = []

    def walk(name: str, depth: int, seen: set[str]) -> None:
        d = next((x for x in rep.dists if x.name == name), None)
        tree_lines.append("  " * depth + f"{name} {d.version if d else ''}".rstrip())
        if d is None or name in seen:
            return
        seen.add(name)
        for child in d.depends_on:
            walk(child, depth + 1, seen)

    walk(PROJECT, 0, set())

    url_rows = "".join(
        f"<tr><td class='mono'>{esc(f)}</td><td class='mono'>{esc(u)}</td></tr>"
        for f, u in rep.urls_found
    )
    sub_rows = "".join(
        f"<tr><td class='mono'>{esc(f)}</td><td class='mono'>{esc(t)}</td></tr>"
        for f, t in rep.subprocess_targets
    )
    exec_rows = "".join(
        f"<tr><td class='mono'>{esc(f)}</td><td class='mono'>{esc(t)}</td></tr>"
        for f, t in rep.dynamic_exec
    )
    vuln_rows = "".join(
        f"<tr><td>{esc(v['dependency']['name'])} {esc(v['dependency']['version'])}</td>"
        f"<td><a href='{esc(v.get('link', ''))}'>{esc(v['display_id'])}</a></td><td>{esc(v.get('summary', ''))}</td>"
        f"<td>{esc(', '.join(v.get('fix_versions', [])))}</td></tr>"
        for v in rep.vulnerabilities or []
    )

    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClickNick {esc(rep.version)} trust report</title><style>{CSS}</style></head>
<body><main>
<h1>ClickNick {esc(rep.version)} trust report</h1>
<p class="sub">Generated {esc(rep.generated)} from <code>uv.lock</code> at commit <code>{esc(rep.commit[:12])}</code>.
This file is self-contained: no scripts, no external resources. Latest reports and the explanation of this
format: <a href="https://pyrung.com/clicknick/security/">pyrung.com/clicknick/security</a>.</p>
{status}

<h2>For IT / security review</h2>
<p class="note">The narrative below comes from <code>docs/security/index.md</code> in this
report's source checkout. It describes intended behavior; the generated checks below provide
release-specific evidence, not a formal security audit.</p>
{render_security_narrative()}

<h2>Release summary</h2>
<table class="kv">
<tr><td>Release</td><td>ClickNick {esc(rep.version)}</td></tr>
<tr><td>Python</td><td>{esc(rep.python_requires)}</td></tr>
<tr><td>Runtime distributions</td><td>{len(rep.dists)}</td></tr>
<tr><td>First-party</td><td>{len(first)}</td></tr>
<tr><td>Third-party</td><td>{len(third)}</td></tr>
<tr><td>Known vulnerabilities</td><td>{esc(vuln_count)} ({rep.audited_packages} dependencies audited against the advisory database; ClickNick itself is the package being built)</td></tr>
<tr><td>Non-PyPI third-party dependencies</td><td>{len([d for d in third if d.source != "PyPI"])}</td></tr>
<tr><td>Unresolved licenses</td><td>{len([d for d in rep.dists if d.license.startswith("UNRESOLVED")])}</td></tr>
<tr><td>SBOM SHA256 ({esc(rep.sbom_name)})</td><td class="mono hash">{esc(rep.sbom_sha256)}</td></tr>
{wheel_row}
<tr><td>PowerShell worker SHA256 (clicknick/resources/jet_sidecar.ps1)</td><td class="mono hash">{esc(rep.sidecar_sha256)}</td></tr>
<tr><td>Generated from</td><td><code>uv.lock</code>, exported as CycloneDX 1.5 by uv {esc(rep.uv_version)}</td></tr>
<tr><td>Source commit</td><td class="mono">{esc(rep.commit)}</td></tr>
</table>

<h2>Release checks</h2>
{render_checks(rep.checks)}

<h2>Runtime dependencies</h2>
<p>Every distribution that <code>uv tool install clicknick=={esc(rep.version)}</code> installs. ClickNick pins its
whole runtime tree exactly (the "Pin" column), so a fresh install matches this table and the SBOM; a release check
below confirms the pins match <code>uv.lock</code>. "Used by" names the package that needs it. "First-party" means
written by the ClickNick author. "Native code" reflects the Windows x64 wheels installed in the build environment.</p>
<div class="wrap"><table>
<tr><th>Package</th><th>Version</th><th>Pin</th><th>Source</th><th>License</th><th>Used by</th><th>Native code</th><th>Purpose</th></tr>
{"".join(rows)}
</table></div>
<h3>Dependency tree</h3>
<pre class="mono">{esc(chr(10).join(tree_lines))}</pre>
{"<h3>Known vulnerabilities</h3><table><tr><th>Package</th><th>Advisory</th><th>Summary</th><th>Fixed in</th></tr>" + vuln_rows + "</table>" if vuln_rows else ""}

<h2>Source transparency</h2>
<p>Evidence behind the release checks, listed so a reviewer can look at the exact lines.</p>
<h3>URLs in runtime source</h3>
<p>Every URL found in a string literal of the runtime code (comments and docstrings excluded). All of these are
opened in the user's browser on click or shown as help text. None is contacted by ClickNick.</p>
<table><tr><th>File</th><th>URL</th></tr>{url_rows or "<tr><td colspan=2>none</td></tr>"}</table>
<h3>Subprocess launch sites</h3>
<table><tr><th>Location</th><th>Program</th></tr>{sub_rows or "<tr><td colspan=2>none</td></tr>"}</table>
<h3>Dynamic code execution</h3>
<p>Every <code>exec</code> or <code>eval</code> call in runtime code. Each one runs Python that ClickNick
generated from the user's own ladder project, or files from the user's project workspace. Nothing downloaded,
nothing decoded.</p>
<table><tr><th>Location</th><th>Call</th></tr>{exec_rows or "<tr><td colspan=2>none</td></tr>"}</table>

<h2>Verify it yourself</h2>
<p>Rebuild from a clean checkout of the tagged release using its own build recipe.
Build dependencies are pinned in pyproject.toml; Hatch supplies stable timestamps when SOURCE_DATE_EPOCH is unset, and Git attributes select LF checkout line endings.
Compare the rebuilt wheel's SHA256 with this report to verify that its bytes match.
Older release tags retain their original settings.</p>
<pre class="mono">git clone https://github.com/ssweber/clicknick
cd clicknick
git checkout {esc(checkout_ref)}
uv export --frozen --no-dev --format cyclonedx1.5      # the dependency list in this report
uv audit --frozen --no-dev --no-group docs             # the vulnerability check
uv build
certutil -hashfile dist\\{esc(rep.wheel_name or "clicknick-*.whl")} SHA256
uv run python devtools/trust_report.py                 # regenerate this page into dist/trust/</pre>
<p>To check the copy that was installed: <code>uv tool dir</code> shows the install folder; the wheel's files are
unpacked there, and <code>pip download clicknick=={esc(rep.version)} --no-deps</code> fetches the exact wheel
from PyPI for hashing. To install this exact version rather than the latest:
<code>uv tool install clicknick=={esc(rep.version)}</code>.</p>
</main></body></html>
"""


# ---- Main -------------------------------------------------------------------


def detect_version(wheel: Path | None) -> str:
    if wheel is not None:
        return wheel.name.split("-")[1]
    try:
        return md.version(PROJECT)
    except md.PackageNotFoundError:
        return "unknown"


def find_wheel(explicit: str | None) -> Path | None:
    if explicit:
        path = Path(explicit)
        if not path.is_file():
            sys.exit(f"wheel not found: {path}")
        return path
    wheels = sorted((ROOT / "dist").glob(f"{PROJECT}-*.whl"), key=lambda p: p.stat().st_mtime)
    return wheels[-1] if wheels else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the ClickNick trust report.")
    parser.add_argument(
        "--out", type=Path, default=ROOT / "dist" / "trust", help="output directory"
    )
    parser.add_argument(
        "--wheel", help="built wheel to hash and inspect (default: newest in dist/)"
    )
    parser.add_argument("--no-wheel", action="store_true", help="do not look for a wheel")
    parser.add_argument(
        "--skip-audit", action="store_true", help="skip uv audit (offline use; fails that check)"
    )
    parser.add_argument("--uv", default="uv", help="uv executable")
    args = parser.parse_args()

    wheel = None if args.no_wheel else find_wheel(args.wheel)
    version = detect_version(wheel)
    uv_version = run([args.uv, "--version"]).stdout.strip().removeprefix("uv ").split(" ")[0]

    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    sbom_bytes, sbom = load_sbom(args.uv)
    sbom["metadata"]["component"]["version"] = version  # uv cannot see the dynamic version
    sbom_bytes = json.dumps(sbom, indent=2).encode("utf-8") + b"\n"
    lock = load_lock()
    dists = collect_dists(sbom, lock, version, requirement_specs(pyproject))
    runtime_names = {norm(d.name) for d in dists}

    vulns, audited = (None, 0) if args.skip_audit else run_audit(args.uv, runtime_names)
    source_checks, urls, sub_targets, dyn_exec = scan_sources(dists)
    wheel_check, _wheel_files = wheel_checks(wheel)
    checks = dependency_checks(dists, vulns) + [wheel_check] + source_checks

    args.out.mkdir(parents=True, exist_ok=True)
    sbom_name = f"{PROJECT}-sbom-{version}.cyclonedx.json"
    (args.out / sbom_name).write_bytes(sbom_bytes)

    rep = Report(
        version=version,
        python_requires=pyproject["project"]["requires-python"],
        commit=git_commit(),
        generated=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M UTC"),
        uv_version=uv_version,
        dists=dists,
        checks=checks,
        vulnerabilities=vulns,
        audited_packages=audited,
        sbom_sha256=sha256_of(sbom_bytes),
        sbom_name=sbom_name,
        wheel_name=wheel.name if wheel else None,
        wheel_sha256=sha256_of(wheel.read_bytes()) if wheel else None,
        sidecar_sha256="",
        is_release=False,
        urls_found=urls,
        subprocess_targets=sub_targets,
        dynamic_exec=dyn_exec,
    )
    rep.sidecar_sha256 = sha256_of((SRC / "resources" / "jet_sidecar.ps1").read_bytes())
    rep.is_release = re.fullmatch(r"\d+\.\d+\.\d+", version) is not None
    report_path = args.out / f"{PROJECT}-trust-report-{version}.html"
    report_path.write_text(render(rep), encoding="utf-8")

    failed = [c for c in checks if not c.passed]
    for c in checks:
        print(
            ("PASS " if c.passed else "FAIL ")
            + c.label
            + (f"  [{c.detail}]" if not c.passed else "")
        )
    print()
    print(f"wrote {report_path}")
    print(f"wrote {args.out / sbom_name}")
    if failed:
        print(f"\n{len(failed)} release check(s) failed.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
