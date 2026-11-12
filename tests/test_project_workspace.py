"""PlcSourceWatch: whether a project's src/plc still holds what a simulation launched with."""

from __future__ import annotations

import os

from clicknick.services.project_workspace import PlcSourceWatch, plc_source_dir


def _source(tmp_path, text: str = "rung = 1\n"):
    source = plc_source_dir(tmp_path)
    source.mkdir(parents=True)
    main = source / "main.py"
    main.write_text(text, encoding="utf-8")
    return main


def _later(path) -> None:
    """Move *path*'s modification time on, as a save a moment later would."""
    info = path.stat()
    os.utime(path, ns=(info.st_atime_ns, info.st_mtime_ns + 2_000_000_000))


def test_an_edit_counts_until_it_is_undone(tmp_path):
    main = _source(tmp_path)
    watch = PlcSourceWatch(tmp_path)
    assert not watch.changed()

    main.write_text("rung = 2\n", encoding="utf-8")
    _later(main)
    assert watch.changed()
    assert watch.changed(), "still changed on the next check"

    main.write_text("rung = 1\n", encoding="utf-8")
    _later(main)
    assert not watch.changed()


def test_a_file_saved_unchanged_or_a_cache_does_not_count(tmp_path):
    main = _source(tmp_path)
    watch = PlcSourceWatch(tmp_path)
    _later(main)
    cache = main.parent / "__pycache__"
    cache.mkdir()
    (cache / "main.cpython-311.pyc").write_bytes(b"compiled")
    assert not watch.changed()


def test_a_new_or_removed_file_counts(tmp_path):
    main = _source(tmp_path)
    watch = PlcSourceWatch(tmp_path)
    extra = main.parent / "extra.py"
    extra.write_text("x = 1\n", encoding="utf-8")
    assert watch.changed()
    extra.unlink()
    assert not watch.changed()
    main.unlink()
    assert watch.changed()
