"""The Address Editor's jump menus offer only addresses that the Address Editor holds."""

import pytest
from pyclickplc.addresses import iter_address_slots

from clicknick.views.address_editor.jump_sidebar import ADDRESS_JUMPS, SIDEBAR_TYPES
from clicknick.views.address_editor.view_builder import COMBINED_TYPES

_HELD = set(iter_address_slots())
# XD and YD have no jump menu today.
_WITH_MENU = [t for t in SIDEBAR_TYPES if t not in ("XD", "YD")]


@pytest.mark.parametrize("type_name", _WITH_MENU)
def test_every_jump_is_an_address_the_editor_holds(type_name):
    assert type_name in ADDRESS_JUMPS, f"{type_name} has no jump menu"
    jumps = ADDRESS_JUMPS[type_name]
    for mem_type in COMBINED_TYPES.get(type_name, [type_name]):
        missing = [a for a in jumps if (mem_type, a) not in _HELD]
        assert not missing, f"{mem_type} has no row for {missing}"


def test_x_and_y_jump_to_the_first_address_of_every_slot():
    for mem_type in ("X", "Y"):
        assert 21 in ADDRESS_JUMPS[mem_type]
        assert ADDRESS_JUMPS[mem_type][:3] == [1, 21, 101]
