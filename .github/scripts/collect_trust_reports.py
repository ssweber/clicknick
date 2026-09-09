#!/usr/bin/env python3
"""Mirror per-release trust reports onto the docs site.

Downloads ``clicknick-trust-report-<version>.html`` and
``clicknick-sbom-<version>.cyclonedx.json`` from every published GitHub release
into ``docs/security/`` and rewrites ``docs/security/reports.md`` as an index.

Runs in the docs workflow with ``gh`` and ``GH_TOKEN`` available. Locally, with
no ``gh``, it leaves the committed placeholder ``reports.md`` alone.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPORT_RE = re.compile(r"^clicknick-trust-report-(?P<version>.+)\.html$")
SBOM_RE = re.compile(r"^clicknick-sbom-(?P<version>.+)\.cyclonedx\.json$")
PATTERNS = ["clicknick-trust-report-*.html", "clicknick-sbom-*.cyclonedx.json"]

HEADER = """\
# Release reports

Every release ships a versioned trust report and its CycloneDX SBOM. The same
files are attached to the matching [GitHub release](https://github.com/ssweber/clicknick/releases).
See [Security](index.md) for what the report contains and how to verify it.

"""

PLACEHOLDER = (
    HEADER
    + "_Report links are filled in when the site is built. Until then, download them "
    "from the GitHub release page._\n"
)


def version_key(version: str) -> tuple:
    return tuple(int(p) if p.isdigit() else p for p in re.split(r"[.+-]", version))


def gh(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], capture_output=True, text=True, check=False)


def release_tags(repo: str) -> list[str]:
    result = gh(
        ["release", "list", "--repo", repo, "--limit", "200", "--json", "tagName,isDraft"]
    )
    if result.returncode != 0:
        print(f"WARN: gh release list failed: {result.stderr.strip()}")
        return []
    return [r["tagName"] for r in json.loads(result.stdout) if not r.get("isDraft")]


def download(repo: str, tag: str, dest: Path) -> None:
    args = ["release", "download", tag, "--repo", repo, "--dir", str(dest), "--skip-existing"]
    for pattern in PATTERNS:
        args += ["--pattern", pattern]
    result = gh(args)
    if result.returncode != 0 and "no assets" not in result.stderr.lower():
        print(f"WARN: {tag}: {result.stderr.strip()}")


def write_index(dest: Path) -> int:
    reports: dict[str, dict[str, str]] = {}
    for path in dest.iterdir():
        if path.name in {"clicknick-trust-report-latest.html", "clicknick-sbom-latest.cyclonedx.json"}:
            continue
        if m := REPORT_RE.match(path.name):
            reports.setdefault(m["version"], {})["report"] = path.name
        elif m := SBOM_RE.match(path.name):
            reports.setdefault(m["version"], {})["sbom"] = path.name
    if not reports:
        (dest / "reports.md").write_text(PLACEHOLDER, encoding="utf-8")
        return 0

    versions = sorted(reports, key=version_key, reverse=True)
    lines = [
        HEADER,
        "Stable links to the newest release: "
        "[clicknick-trust-report-latest.html](clicknick-trust-report-latest.html) and "
        "[clicknick-sbom-latest.cyclonedx.json](clicknick-sbom-latest.cyclonedx.json).",
        "",
        "| Release | Trust report | SBOM |",
        "|---|---|---|",
    ]
    for version in versions:
        files = reports[version]
        report = f"[HTML]({files['report']})" if "report" in files else "-"
        sbom = f"[CycloneDX JSON]({files['sbom']})" if "sbom" in files else "-"
        lines.append(f"| {version} | {report} | {sbom} |")
    (dest / "reports.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # Stable "latest" copies for linking from the security page.
    latest = reports[versions[0]]
    if "report" in latest:
        shutil.copyfile(dest / latest["report"], dest / "clicknick-trust-report-latest.html")
    if "sbom" in latest:
        shutil.copyfile(dest / latest["sbom"], dest / "clicknick-sbom-latest.cyclonedx.json")
    return len(versions)


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror per-release trust reports onto the docs site.")
    parser.add_argument("--repo", default="ssweber/clicknick")
    parser.add_argument("--dest", type=Path, default=Path("docs/security"))
    args = parser.parse_args()
    args.dest.mkdir(parents=True, exist_ok=True)

    if shutil.which("gh") is None:
        print("WARN: gh not found; leaving reports.md as committed.")
        return 0
    for tag in release_tags(args.repo):
        download(args.repo, tag, args.dest)
    count = write_index(args.dest)
    print(f"OK: indexed trust reports for {count} release(s) in {args.dest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
