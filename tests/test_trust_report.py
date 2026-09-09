"""Release checks in devtools/trust_report.py must catch what they claim to catch."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "devtools"))

import trust_report as tr  # noqa: E402


def _dist(name: str, source: str = "PyPI", license: str = "MIT", purpose: str = "x") -> tr.Dist:
    return tr.Dist(
        name=name,
        version="1.0",
        source=source,
        license=license,
        direct=True,
        purpose=purpose,
        native="no",
        homepage="",
    )


def _scan(tmp_path: Path, files: dict[str, str], dists: list[tr.Dist] | None = None):
    src = tmp_path / "src" / "clicknick"
    for name, body in files.items():
        path = src / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    checks, urls, subs, execs = tr.scan_sources(dists or [_dist("clicknick")], src, tmp_path)
    return {c.label: c for c in checks}, urls, subs, execs


CLEAN = """
    import sys
    import subprocess
    from multiprocessing.connection import Listener

    def go(powershell_path):
        Listener(("localhost", 0), family="AF_INET")
        argv = [str(powershell_path()), "-NoProfile"]
        subprocess.Popen(argv)
        subprocess.run([sys.executable, "-m", "x"])
"""


def test_clean_tree_passes_every_source_check(tmp_path):
    checks, urls, subs, execs = _scan(tmp_path, {"a.py": CLEAN})
    assert all(c.passed for c in checks.values()), [c for c in checks.values() if not c.passed]
    assert urls == []
    assert [t for _, t in subs] == ["str(powershell_path())", "sys.executable"]
    assert execs == []


def test_urls_in_docstrings_and_comments_are_ignored(tmp_path):
    checks, urls, *_ = _scan(
        tmp_path,
        {
            "a.py": '''
                """Adapted from https://stackoverflow.com/a/1."""
                # see https://example.org/comment
                LINK = "https://github.com/ssweber/clicknick"
            ''',
            "w.ps1": "# https://evil.example/comment\nWrite-Host 'hi'\n",
        },
    )
    assert [u for _, u in urls] == ["https://github.com/ssweber/clicknick"]
    assert checks["No external runtime endpoints"].passed


def test_unexpected_host_in_string_literal_fails(tmp_path):
    checks, *_ = _scan(tmp_path, {"a.py": 'URL = "https://api.example.com/v1/ping"\n'})
    check = checks["No external runtime endpoints"]
    assert not check.passed
    assert "api.example.com" in check.detail


def test_network_client_import_fails(tmp_path):
    checks, *_ = _scan(tmp_path, {"a.py": "import urllib.request\n"})
    assert not checks["No HTTP, FTP or mail client imports in runtime source"].passed


def test_decode_then_exec_fails_but_icon_data_does_not(tmp_path):
    checks, *_ = _scan(
        tmp_path,
        {
            "bad.py": 'import base64\nexec(base64.b64decode("aGk="))\n',
            "bad2.py": 'from zlib import decompress\neval(decompress(b""))\n',
            "icons.py": 'import base64\nPNG = base64.b64decode("aGk=")\n',
        },
    )
    check = checks["No Python decoded at runtime (base64/zlib/marshal fed to exec/eval/compile)"]
    assert not check.passed
    assert "bad.py" in check.detail and "bad2.py" in check.detail
    assert "icons.py" not in check.detail


def test_tk_eval_is_not_dynamic_python_execution(tmp_path):
    _, _, _, execs = _scan(
        tmp_path,
        {"a.py": 'def f(w):\n    w.tk.eval("winfo exists .")\n    exec("x = 1")\n'},
    )
    assert len(execs) == 1 and execs[0][1] == "exec('x = 1')"


def test_foreign_subprocess_target_fails(tmp_path):
    checks, *_ = _scan(
        tmp_path,
        {"a.py": 'import subprocess\nsubprocess.run(["curl.exe", "https://x"])\n'},
    )
    label = (
        "Subprocesses launch only the same Python interpreter or the built-in Windows PowerShell"
    )
    assert not checks[label].passed
    assert "curl.exe" in checks[label].detail
    assert not checks["No download commands in shipped scripts"].passed


def test_non_localhost_listener_fails(tmp_path):
    checks, *_ = _scan(
        tmp_path,
        {"a.py": 'from multiprocessing.connection import Listener\nListener(("0.0.0.0", 5000))\n'},
    )
    assert not checks["Local listeners bind to localhost only"].passed


def test_http_client_and_telemetry_dependencies_fail(tmp_path):
    checks, *_ = _scan(
        tmp_path,
        {"a.py": "x = 1\n"},
        [_dist("clicknick"), _dist("requests"), _dist("opentelemetry-sdk")],
    )
    assert not checks["No HTTP client dependency (requests, httpx, aiohttp, urllib3, ...)"].passed
    assert not checks["No telemetry or analytics SDK dependency"].passed


def test_dependency_checks_flag_gaps():
    dists = [
        _dist("clicknick", source="This repository"),
        _dist("weird", source="git: https://x", license="UNRESOLVED", purpose=""),
    ]
    vulns = [{"dependency": {"name": "weird", "version": "1.0"}, "display_id": "GHSA-1"}]
    results = {c.label: c for c in tr.dependency_checks(dists, vulns)}
    assert not results["All third-party dependencies come from PyPI"].passed
    assert not results["Every runtime distribution has a resolved license"].passed
    assert not results["Every runtime distribution has a documented purpose"].passed
    assert not results["No known vulnerabilities (uv audit)"].passed
    assert "GHSA-1" in results["No known vulnerabilities (uv audit)"].detail


def test_audit_not_run_is_a_failed_check():
    results = {c.label: c for c in tr.dependency_checks([_dist("clicknick")], None)}
    assert not results["No known vulnerabilities (uv audit)"].passed


def test_wheel_with_binary_fails(tmp_path):
    import zipfile

    wheel = tmp_path / "clicknick-1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as zf:
        zf.writestr("clicknick/__init__.py", "")
        zf.writestr("clicknick/helper.exe", b"MZ")
    check, _ = tr.wheel_checks(wheel)
    assert not check.passed and "helper.exe" in check.detail


@pytest.mark.parametrize("name", sorted(tr.PURPOSES))
def test_every_purpose_entry_is_normalized(name):
    assert name == tr.norm(name)


def test_real_tree_passes_source_checks():
    """The shipped source must pass its own checks (no uv, no network needed)."""
    dists = [_dist(name) for name in tr.PURPOSES]
    checks, *_ = tr.scan_sources(dists)
    failed = [c for c in checks if not c.passed]
    assert not failed, [(c.label, c.detail) for c in failed]


def test_unpinned_dependency_fails_pin_check():
    pinned = _dist("pyodbc")
    pinned.requirement = "==1.0"
    loose = _dist("pywin32")
    loose.requirement = ">=1.0"
    results = {c.label: c for c in tr.dependency_checks([_dist("clicknick"), pinned, loose], [])}
    label = "Every runtime distribution is pinned exactly in pyproject.toml to its locked version"
    assert not results[label].passed
    assert "pywin32" in results[label].detail and "pyodbc" not in results[label].detail
