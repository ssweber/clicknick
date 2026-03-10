"""Check the RTF prefix used in native captures and what prefix
our encoder uses, to understand the payload length discrepancy."""

from pathlib import Path
from clicknick.ladder.encode import _PREFIX, _SUFFIX, PAYLOAD_BYTES_OFFSET, PAYLOAD_LENGTH_OFFSET

# Native captures
for name in [
    "native-comment-helloworld",
    "native-comment-fullwire",
    "native-comment-nop",
    "native-comment-partial-wire-v2",
    "native-comment-nop-only",
]:
    path = Path(f"scratchpad/captures/{name}.bin")
    if not path.exists():
        path = Path(f"tests/fixtures/ladder_captures/{name}.bin")
    if not path.exists():
        print(f"{name}: NOT FOUND")
        continue

    data = path.read_bytes()
    plen = int.from_bytes(data[PAYLOAD_LENGTH_OFFSET:PAYLOAD_BYTES_OFFSET], 'little')
    payload = data[PAYLOAD_BYTES_OFFSET:PAYLOAD_BYTES_OFFSET + plen]

    # Find the RTF prefix (everything before the comment text)
    # RTF body ends with \fs20 followed by a space
    fs20_pos = payload.find(b'\\fs20 ')
    if fs20_pos >= 0:
        prefix = payload[:fs20_pos + 6]  # include \fs20 and the space
    else:
        prefix = b"???"

    # Find suffix
    par_pos = payload.rfind(b'\\par ')
    if par_pos >= 0:
        suffix = payload[par_pos:]
    else:
        suffix = b"???"

    print(f"{name}:")
    print(f"  Payload length: {plen}")
    print(f"  Prefix ({len(prefix)} bytes): {prefix}")
    print(f"  Suffix ({len(suffix)} bytes): {suffix!r}")
    print(f"  Flag: 0x{data[0x0254 + 0x17]:02X}")
    print()

print(f"Our _PREFIX ({len(_PREFIX)} bytes): {_PREFIX}")
print(f"Our _SUFFIX ({len(_SUFFIX)} bytes): {_SUFFIX!r}")
