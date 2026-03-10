"""Analyze the pre-header region (0x0000-0x0253) across native, synthetic,
and the scaffold template to understand what's different and whether any
pre-header bytes could be critical for comment recognition.
"""

from pathlib import Path
from clicknick.ladder.encode import encode_rung

# Load scaffold template
scaffold = Path("src/clicknick/ladder/resources/empty_multirow_rule_minimal.scaffold.bin").read_bytes()

# Native captures
nat_empty = Path("scratchpad/captures/native-comment-helloworld.bin").read_bytes()
nat_fw = Path("scratchpad/captures/native-comment-fullwire.bin").read_bytes()
nat_nop = Path("scratchpad/captures/native-comment-nop.bin").read_bytes()

# Synthetic
syn_empty = encode_rung(1, [[""] * 31], [""], comment="Hello world")
syn_fw = encode_rung(1, [["-"] * 31], [""], comment="Partial wires")

# 2-row native (passing)
nat_2r = Path("tests/fixtures/ladder_captures/verify-comment-2row-empty.bin").read_bytes()
syn_2r = encode_rung(2, [[""] * 31, [""] * 31], ["", ""], comment="Two row test")

# Non-comment synthetic for comparison
syn_plain = encode_rung(1, [[""] * 31], [""])


print("=== Pre-header region analysis ===")
print(f"Scaffold template size: {len(scaffold)} bytes")
print()

# Check scaffold pre-header (0x0000-0x0253)
print("Scaffold pre-header non-zero bytes:")
for i in range(min(0x0254, len(scaffold))):
    if scaffold[i] != 0:
        print(f"  0x{i:04X} = 0x{scaffold[i]:02X}", end="")
        if i < 8:
            print(f"  ('{chr(scaffold[i])}')", end="")
        print()

print()
print("=== Key offsets across all samples ===")
key_offsets = [
    (0x0008, "clipboard format / version?"),
    (0x000C, "unknown"),
    (0x0010, "unknown"),
    (0x0014, "unknown"),
    (0x0018, "unknown"),
    (0x001C, "unknown"),
    (0x0020, "unknown"),
    (0x0024, "unknown"),
    (0x0028, "unknown"),
    (0x002C, "unknown"),
    (0x0030, "unknown"),
    (0x0040, "unknown"),
    (0x0044, "unknown"),
    (0x0048, "unknown"),
    (0x004C, "unknown"),
    (0x0050, "unknown"),
    (0x0054, "unknown"),
]

# Check which pre-header bytes are consistent across ALL native comment captures
print("\nNative captures - shared non-zero pre-header bytes:")
shared_nonzero = {}
for i in range(0x0054):
    vals = [nat_empty[i], nat_fw[i], nat_nop[i]]
    if all(v != 0 for v in vals):
        if len(set(vals)) == 1:
            shared_nonzero[i] = vals[0]
            print(f"  0x{i:04X} = 0x{vals[0]:02X} (same across all 3 native)")
        else:
            print(f"  0x{i:04X} = {[f'0x{v:02X}' for v in vals]} (varies)")

# Compare scaffold vs native at shared bytes
print("\nScaffold has these values at shared native positions:")
for off, val in shared_nonzero.items():
    sval = scaffold[off] if off < len(scaffold) else 0
    match = "MATCH" if sval == val else f"DIFF (scaffold=0x{sval:02X})"
    print(f"  0x{off:04X}: native=0x{val:02X}  scaffold=0x{sval:02X}  {match}")

# Check what 2-row native has at these positions
print("\n2-row native (passing) at shared 1-row native positions:")
for off, val in shared_nonzero.items():
    n2val = nat_2r[off]
    print(f"  0x{off:04X}: 1row-native=0x{val:02X}  2row-native=0x{n2val:02X}")

# Critical check: the first 0x58 bytes (before the divergence)
print("\n=== First 0x58 bytes comparison ===")
print("Scaffold:")
for i in range(0, 0x58, 16):
    chunk = scaffold[i:i+16] if i+16 <= len(scaffold) else scaffold[i:]
    print(f"  0x{i:04X}: {chunk.hex(' ')}")
print("\nNative fullwire:")
for i in range(0, 0x58, 16):
    chunk = nat_fw[i:i+16]
    print(f"  0x{i:04X}: {chunk.hex(' ')}")
print("\nSynthetic fullwire:")
for i in range(0, 0x58, 16):
    chunk = syn_fw[i:i+16]
    print(f"  0x{i:04X}: {chunk.hex(' ')}")
print("\nNative 2-row (passing):")
for i in range(0, 0x58, 16):
    chunk = nat_2r[i:i+16]
    print(f"  0x{i:04X}: {chunk.hex(' ')}")
print("\nSynthetic 2-row (passing):")
for i in range(0, 0x58, 16):
    chunk = syn_2r[i:i+16]
    print(f"  0x{i:04X}: {chunk.hex(' ')}")
