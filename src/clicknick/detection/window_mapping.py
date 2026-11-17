from dataclasses import dataclass

# Address types each edit control accepts. For CLICK v4's Receive, Send, Out, Set and Reset,
# they are the banks that the Address Picker leaves open when a field's "..." button opens it
# ("Address Picker : Pickup Mode" greys the others). Live probes found them (2026-11-16).
# The other lists were not probed.
BITS = ["X", "Y", "C", "T", "CT", "SC"]
COILS = ["Y", "C", "SC"]  # Out, Set and Reset
COMPARE = ["DS", "TD", "SD", "DD", "DH", "CTD", "DF"]
MATH = ["DS", "TD", "SD", "DD", "CTD", "DF"]
SEARCH = ["DS", "TD", "SD", "DD", "CTD", "DF", "DH", "XD", "YD", "TXT"]
ANY = [*BITS, "DS", "TD", "SD", "DD", "CTD", "DF", "DH", "XD", "YD", "TXT"]
STATUS_BIT = ["C"]
EXCEPTION_CODE = ["DS", "DD"]


@dataclass(frozen=True)
class ByChoice:
    """The address types that follow the item a drop-down list of the same dialog shows.

    *control* names the list the way the overlay names controls (``ComboBox2``). *types* maps
    each item to the address types that the field accepts with it. If the list cannot be
    read, or shows another item, every item's types apply (``every``).
    """

    control: str
    types: dict[str, list[str]]

    @property
    def every(self) -> list[str]:
        """Return the address types of all items, each once, in the order the items give them."""
        return list(dict.fromkeys(t for types in self.types.values() for t in types))

    def shown(self, item: str) -> list[str]:
        """Return the address types that the field accepts while the list shows *item*."""
        return self.types.get(item, self.every)


# Receive's Starting Master Address, by Modbus Function Code (v4 lists it as ComboBox2)
RECEIVE_LOCAL = ByChoice(
    "ComboBox2",
    {
        "01 - Read Coil Status": ["Y", "C"],
        "02 - Read Input Status": ["Y", "C"],
        "03 - Read Holding Registers": ["DS", "DD", "DH", "DF", "YD", "TXT"],
        "04 - Read Input Registers": ["DS", "DD", "DH", "DF", "YD", "TXT"],
    },
)
# Send's Starting Master Address, by Modbus Function Code (v4 lists it as ComboBox2)
SEND_LOCAL = ByChoice(
    "ComboBox2",
    {
        "05 - Write Single Coil": BITS,
        "06 - Write Single Register": ["DS", "DH", "XD", "YD", "TD", "SD", "TXT"],
        "15 - Write Multiple Coils": BITS,
        "16 - Write Multiple Registers": ["DS", "DD", "DH", "DF", "TD", "CTD", "SD", "TXT"],
    },
)

DIALOG_CLASS = "#32770"


def unprefixed(class_name: str) -> str:
    """Return a window or control class name without Delphi's leading T (TEdit1 -> Edit1)."""
    return class_name.removeprefix("T")


def window_key(window_class: str, title: str) -> str:
    """Return the CLICK_PLC_WINDOW_MAPPING key for a CLICK window.

    Delphi forms are keyed by class without the leading T. That covers every instruction
    dialog before CLICK v4, and the Data View and Address Picker in every version.

    Standard dialogs all share the class #32770, so they are keyed by title. That covers the
    v4 instruction dialogs, and Find / Replace in every version.
    """
    if window_class != DIALOG_CLASS:
        return unprefixed(window_class)
    if "Find" in title or "Replace" in title:
        return "Find"
    return title


# Each CLICK window (see window_key) maps to its edit controls (AHK ClassNN without the
# leading T). Each control maps to the address types it accepts, or to a ByChoice for types
# that follow a list of the dialog.
# A v4 dialog's edits are numbered over every Edit window in it, including hidden ones and
# those inside other controls. Receive's and Send's IP address control holds Edit2 to Edit5.
CLICK_PLC_WINDOW_MAPPING = {
    # CLICK v2/v3 instruction dialogs (Delphi forms)
    "frmContactNO": {"Edit1": BITS},  # "Contact Normally Open"
    "frmContactNC": {"Edit1": BITS},  # "Contact Normally Closed"
    "frmEdgeContact": {"Edit1": BITS},  # "Edge Contact"
    "frmContactCompare": {"Edit1": COMPARE, "Edit2": COMPARE},  # "Compare (A with B)"
    "frmOut": {"Edit2": COILS, "Edit1": COILS},  # "Out"
    "frmSet": {"Edit2": COILS, "Edit1": COILS},  # "Set"
    "frmCoilReset": {"Edit2": COILS, "Edit1": COILS},  # "Reset"
    "frmTimer": {  # "Timer"
        "Edit3": ["T"],  # Timer BIT address
        "Edit2": ["DS"],  # Timer value (DS)
    },
    "frmCounter": {  # "Counter"
        "Edit4": ["CT"],  # Counter BIT address
        "Edit3": ["DS", "DD"],  # Counter value (DS/DD)
    },
    "frmMath": {"Edit1": MATH},  # "Math"; the formula is a TTntRichEdit
    "frmShiftRegister": {"Edit2": ["C"], "Edit1": ["C"]},  # "Shift"
    "frmCopy": {"Edit1": ANY, "Edit2": ANY, "Edit3": ANY, "Edit4": ANY},  # "Copy instruction"
    "frmSearch": {"Edit1": SEARCH},  # "Search instruction"
    "frmRD": {  # Receive
        "Edit20": RECEIVE_LOCAL.every,  # Local; every code's banks, as no v2/v3 was probed
        "Edit6": STATUS_BIT,  # Receiving
        "Edit7": STATUS_BIT,  # Success
        "Edit5": STATUS_BIT,  # Error
        "Edit4": EXCEPTION_CODE,  # Exception Code
    },
    "frmSD": {  # Send
        "Edit16": SEND_LOCAL.every,  # Local; every code's banks, as no v2/v3 was probed
        "Edit4": STATUS_BIT,  # Sending
        "Edit3": STATUS_BIT,  # Success
        "Edit2": STATUS_BIT,  # Error
        "Edit1": EXCEPTION_CODE,  # Exception Code
    },
    # CLICK v4 instruction dialogs (#32770, keyed by title; edits numbered as in Inst_*.dll)
    "Contact Normally Open": {"Edit1": BITS},
    "Contact Normally Closed": {"Edit1": BITS},
    "Edge Contact": {"Edit1": BITS},
    "Compare (A with B)": {"Edit1": COMPARE, "Edit2": COMPARE},
    "Out": {
        "Edit1": COILS,  # Bit Memory Address1
        "Edit2": COILS,  # Bit Memory Address2 (Out/Toggle only)
        # Delay Setting, open for Debounce, Flasher and Timed (Timed: Edit3 and Edit4 only);
        # the labels change with the output type, the banks do not
        "Edit3": ["DS"],  # On Time (or a constant)
        "Edit4": ["TD"],  # On Timer Number
        "Edit5": ["DS"],  # Off Time (or a constant)
        "Edit6": ["TD"],  # Off Timer Number
    },
    "Set": {"Edit1": COILS, "Edit2": COILS},
    "Reset": {"Edit1": COILS, "Edit2": COILS},
    "Timer": {"Edit1": ["T"], "Edit2": ["DS"]},  # Timer Number, Set Point
    "Counter": {"Edit1": ["CT"], "Edit2": ["DS", "DD"]},  # Counter Number, Set Point
    "Math": {"Edit1": MATH},  # Result; the formula is a RichEdit
    "Shift Register": {"Edit1": ["C"], "Edit2": ["C"]},
    "Copy": {"Edit1": ANY, "Edit2": ANY, "Edit3": ANY, "Edit4": ANY},  # Source and Destination
    "Search": {"Edit1": SEARCH},
    "Receive": {
        "Edit9": RECEIVE_LOCAL,  # Starting Master Address
        "Edit15": STATUS_BIT,  # Receiving
        "Edit16": STATUS_BIT,  # Success
        "Edit17": STATUS_BIT,  # Error
        "Edit18": EXCEPTION_CODE,  # Exception Response
    },
    "Send": {
        "Edit9": SEND_LOCAL,  # Starting Master Address
        "Edit15": STATUS_BIT,  # Sending
        "Edit16": STATUS_BIT,  # Success
        "Edit17": STATUS_BIT,  # Error
        "Edit18": EXCEPTION_CODE,  # Exception Response
    },
    # Every version
    "Find": {"Edit1": ANY, "Edit2": ANY, "Edit3": ANY},  # Find / Replace (#32770)
    "frmDataView": {"Edit1": ANY},  # Data View (the grid reuses one edit for every cell)
    "frmTagDB": {"Edit1": ANY},  # Address Picker
}
