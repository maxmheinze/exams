"""DataMatrix barcode generation via zint, without a shell.

The original CLI built a `zint ... --data={code}` string and ran it through
`shell=True`, which is an injection vector. Codes here are always numeric and
fixed-width, but we validate that invariant and invoke zint with an argument
list (shell=False) so even a malformed code can never reach a shell.
"""

import re
import subprocess

_CODE_RE = re.compile(r"^[0-9]{1,16}$")


def generate_barcode(code: str, output_file: str) -> None:
    """Render `code` as a square DataMatrix PNG at `output_file`.

    Mirrors the original: `zint --barcode=71 --data=CODE -square -quietzones -o OUT`
    (barcode type 71 = DataMatrix), but list-form and with the code validated as
    digits only.
    """
    if not _CODE_RE.match(code):
        raise ValueError(f"barcode payload must be 1-16 digits, got {code!r}")
    subprocess.run(
        ["zint", "--barcode=71", f"--data={code}",
         "-square", "-quietzones", "-o", output_file],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
