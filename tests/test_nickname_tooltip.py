"""The overlay's nickname tooltip compares Retentive with its memory type's default."""

from clicknick.models.nickname import Nickname


def _details(address_type: str, data_type: str, retentive: bool, initial_value: str = "0") -> str:
    return Nickname(
        nickname="Name",
        address=f"{address_type}1",
        data_type_display=data_type,
        initial_value=initial_value,
        retentive=retentive,
        address_type=address_type,
    ).details()


def test_retentive_ds_shows_no_initial_value():
    assert "Initial Value" not in _details("DS", "INT", retentive=True)


def test_non_retentive_ds_shows_its_initial_value():
    assert "Initial Value = 100" in _details("DS", "INT", retentive=False, initial_value="100")


def test_retentive_counter_is_the_default():
    assert "Retentive" not in _details("CT", "BIT", retentive=True)


def test_retentive_c_bit_is_shown():
    assert "Retentive" in _details("C", "BIT", retentive=True)
