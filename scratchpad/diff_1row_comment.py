"""Diff native 1-row comment capture against current encoder output."""

from pathlib import Path
from clicknick.ladder.encode import encode_rung

# Native capture: "Hello world" comment, empty 1-row rung
native_path = Path("scratchpad/captures/native-comment-helloworld.bin")
native = native_path.read_bytes()

# Generate synthetic with current encoder
synthetic = encode_rung(
    logical_rows=1,
    condition_rows=[[""] * 31],
    af_tokens=[""],
    comment="Hello world",
)

print(f"Native size:    {len(native)}")
print(f"Synthetic size: {len(synthetic)}")
print()

# Find all byte differences
diffs = []
for i in range(min(len(native), len(synthetic))):
    if native[i] != synthetic[i]:
        diffs.append((i, native[i], synthetic[i]))

print(f"Total byte differences: {len(diffs)}")
print()

if diffs:
    # Show first 60 differences with context
    for offset, nat_byte, syn_byte in diffs[:60]:
        print(f"  0x{offset:04X}  native=0x{nat_byte:02X}  synth=0x{syn_byte:02X}")
    if len(diffs) > 60:
        print(f"  ... and {len(diffs) - 60} more")

# Also check key structural offsets
print()
print("=== Key structural offsets ===")
print(f"0x0254+0x17 (comment flag):  native=0x{native[0x0254+0x17]:02X}  synth=0x{synthetic[0x0254+0x17]:02X}")
print(f"0x0294 (payload len):        native={int.from_bytes(native[0x0294:0x0298], 'little')}  synth={int.from_bytes(synthetic[0x0294:0x0298], 'little')}")
print(f"0x0A59 (trailer):            native=0x{native[0x0A59]:02X}  synth=0x{synthetic[0x0A59]:02X}")

# Check row count word in header entry 0
row_count_word = int.from_bytes(native[0x0254:0x0256], 'little')
print(f"Header entry0 row count:     native=0x{row_count_word:04X}  synth=0x{int.from_bytes(synthetic[0x0254:0x0256], 'little'):04X}")
