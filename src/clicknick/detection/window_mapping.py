DATA_TYPES = {
    "X": "BIT",
    "Y": "BIT",
    "C": "BIT",
    "T": "BIT",
    "CT": "BIT",
    "SC": "BIT",
    "DS": "INT",
    "DD": "INT2",
    "DH": "HEX",
    "DF": "FLOAT",
    "XD": "HEX",
    "YD": "HEX",
    "TD": "INT",
    "CTD": "INT2",
    "SD": "INT",
    "TXT": "TXT",
}


# Address types each edit control accepts
BITS = ["X", "Y", "C", "T", "CT", "SC"]
COMPARE = ["DS", "TD", "SD", "DD", "DH", "CTD", "DF"]
MATH = ["DS", "TD", "SD", "DD", "CTD", "DF"]
SEARCH = ["DS", "TD", "SD", "DD", "CTD", "DF", "DH", "XD", "YD", "TXT"]
ANY = [*BITS, "DS", "TD", "SD", "DD", "CTD", "DF", "DH", "XD", "YD", "TXT"]
RECEIVE_LOCAL = [*BITS, "DS", "TD", "SD"]
SEND_LOCAL = ["Y", "C", "DS", "TD", "SD", "DD", "CTD", "DF", "DH", "YD", "TXT"]
STATUS_BIT = ["C"]
EXCEPTION_CODE = ["DS", "DD"]

DIALOG_CLASS = "#32770"


def unprefixed(class_name: str) -> str:
    """A window or control class name without Delphi's leading T (TEdit1 -> Edit1)."""
    return class_name.removeprefix("T")


def window_key(window_class: str, title: str) -> str:
    """The CLICK_PLC_WINDOW_MAPPING key for a CLICK window.

    Delphi forms are keyed by class without the leading T: every instruction dialog before
    CLICK v4, and the Data View and Address Picker in every version. Standard dialogs all
    share the class #32770, so they are keyed by title: the v4 instruction dialogs, and
    Find / Replace in every version.
    """
    if window_class != DIALOG_CLASS:
        return unprefixed(window_class)
    if "Find" in title or "Replace" in title:
        return "Find"
    return title


# Each CLICK window (see window_key) -> its edit controls (AHK ClassNN without the leading T)
# -> the address types they accept
CLICK_PLC_WINDOW_MAPPING = {
    # CLICK v2/v3 instruction dialogs (Delphi forms)
    "frmContactNO": {"Edit1": BITS},  # "Contact Normally Open"
    "frmContactNC": {"Edit1": BITS},  # "Contact Normally Closed"
    "frmEdgeContact": {"Edit1": BITS},  # "Edge Contact"
    "frmContactCompare": {"Edit1": COMPARE, "Edit2": COMPARE},  # "Compare (A with B)"
    "frmOut": {"Edit2": BITS, "Edit1": BITS},  # "Out"
    "frmSet": {"Edit2": BITS, "Edit1": BITS},  # "Set"
    "frmCoilReset": {"Edit2": BITS, "Edit1": BITS},  # "Reset"
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
        "Edit20": RECEIVE_LOCAL,  # Local
        "Edit6": STATUS_BIT,  # Receiving
        "Edit7": STATUS_BIT,  # Success
        "Edit5": STATUS_BIT,  # Error
        "Edit4": EXCEPTION_CODE,  # Exception Code
    },
    "frmSD": {  # Send
        "Edit16": SEND_LOCAL,  # Local
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
    "Out": {"Edit1": BITS, "Edit2": BITS},
    "Set": {"Edit1": BITS, "Edit2": BITS},
    "Reset": {"Edit1": BITS, "Edit2": BITS},
    "Timer": {"Edit1": ["T"], "Edit2": ["DS"]},  # Timer Number, Set Point
    "Counter": {"Edit1": ["CT"], "Edit2": ["DS", "DD"]},  # Counter Number, Set Point
    "Math": {"Edit1": MATH},  # Result; the formula is a RichEdit
    "Shift Register": {"Edit1": ["C"], "Edit2": ["C"]},
    "Copy": {"Edit1": ANY, "Edit2": ANY, "Edit3": ANY, "Edit4": ANY},  # Source and Destination
    "Search": {"Edit1": SEARCH},
    "Receive": {
        "Edit5": RECEIVE_LOCAL,  # Starting Master Address
        "Edit11": STATUS_BIT,  # Receiving
        "Edit12": STATUS_BIT,  # Success
        "Edit13": STATUS_BIT,  # Error
        "Edit14": EXCEPTION_CODE,  # Exception Response
    },
    "Send": {
        "Edit5": SEND_LOCAL,  # Starting Master Address
        "Edit11": STATUS_BIT,  # Sending
        "Edit12": STATUS_BIT,  # Success
        "Edit13": STATUS_BIT,  # Error
        "Edit14": EXCEPTION_CODE,  # Exception Response
    },
    # Every version
    "Find": {"Edit1": ANY, "Edit2": ANY, "Edit3": ANY},  # Find / Replace (#32770)
    "frmDataView": {"Edit1": ANY},  # Data View (the grid reuses one edit for every cell)
    "frmTagDB": {"Edit1": ANY},  # Address Picker
}
