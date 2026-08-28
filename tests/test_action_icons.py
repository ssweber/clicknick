"""Main-window action icon resource and cache tests."""

from importlib.resources import files
from unittest.mock import MagicMock

from clicknick.resources.action_icons import ACTION_ICON_FILES, ActionIconCache


def test_all_action_icon_resources_are_packaged_pngs() -> None:
    resources = files("clicknick.resources").joinpath("action_icons")

    assert set(ACTION_ICON_FILES) == {
        "address_editor",
        "data_view",
        "check_program",
        "console",
        "rung_apply",
        "reload_from_click",
    }
    for filename in ACTION_ICON_FILES.values():
        png = resources.joinpath(filename).read_bytes()
        assert png.startswith(b"\x89PNG\r\n\x1a\n")
        assert int.from_bytes(png[16:20]) == 24
        assert int.from_bytes(png[20:24]) == 24


def test_action_icon_cache_loads_each_image_only_once() -> None:
    master = object()
    image = object()
    image_factory = MagicMock(return_value=image)
    cache = ActionIconCache(master, image_factory=image_factory)

    first = cache.get("address_editor")
    second = cache.get("address_editor")

    assert first is image
    assert second is image
    image_factory.assert_called_once()
    assert image_factory.call_args.kwargs["master"] is master
