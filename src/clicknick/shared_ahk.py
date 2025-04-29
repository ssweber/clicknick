import os
from pathlib import Path
from typing import Dict

from ahkunwrapped import Script

here = Path(__file__).parent
fname = here / "shared.ahk"

# Get the current Python Process ID
python_pid = str(os.getpid())

format_dict: Dict[str, str] = {
    "PYTHON_PID": python_pid,
}

AHK = Script.from_file(fname, format_dict=format_dict)
