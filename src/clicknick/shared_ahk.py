from pathlib import Path

from ahkunwrapped import Script

here = Path(__file__).parent
fname = here / "shared.ahk"

AHK = Script.from_file(fname)
