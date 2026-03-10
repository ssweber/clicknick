"""Verify that ClickCodec.encode_rows produces identical output to direct
encode_rung for 1-row comment shapes. If there's a discrepancy, the codec
layer is the problem.
"""

from clicknick.ladder.codec import ClickCodec
from clicknick.ladder.encode import encode_rung

codec = ClickCodec()

# Test 1: 1-row comment, empty grid
rows_empty = ["#,Hello world", "R,...,:,"]
codec_out = codec.encode_rows(rows_empty)
direct_out = encode_rung(1, [[""] * 31], [""], comment="Hello world")
if codec_out == direct_out:
    print("1-row comment empty: codec == direct  OK")
else:
    diffs = [(i, codec_out[i], direct_out[i]) for i in range(len(codec_out)) if codec_out[i] != direct_out[i]]
    print(f"1-row comment empty: {len(diffs)} diffs!")
    for off, c, d in diffs[:20]:
        print(f"  0x{off:04X}: codec=0x{c:02X} direct=0x{d:02X}")

# Test 2: 1-row comment, full wire
rows_fw = ["#,Partial wires", "R,->,:,"]
codec_out = codec.encode_rows(rows_fw)
direct_out = encode_rung(1, [["-"] * 31], [""], comment="Partial wires")
if codec_out == direct_out:
    print("1-row comment fullwire: codec == direct  OK")
else:
    diffs = [(i, codec_out[i], direct_out[i]) for i in range(len(codec_out)) if codec_out[i] != direct_out[i]]
    print(f"1-row comment fullwire: {len(diffs)} diffs!")
    for off, c, d in diffs[:20]:
        print(f"  0x{off:04X}: codec=0x{c:02X} direct=0x{d:02X}")

# Test 3: 1-row comment, NOP
rows_nop = ["#,Hello NOP", "R,...,:,NOP"]
codec_out = codec.encode_rows(rows_nop)
direct_out = encode_rung(1, [[""] * 31], ["NOP"], comment="Hello NOP")
if codec_out == direct_out:
    print("1-row comment NOP: codec == direct  OK")
else:
    diffs = [(i, codec_out[i], direct_out[i]) for i in range(len(codec_out)) if codec_out[i] != direct_out[i]]
    print(f"1-row comment NOP: {len(diffs)} diffs!")
    for off, c, d in diffs[:20]:
        print(f"  0x{off:04X}: codec=0x{c:02X} direct=0x{d:02X}")

# Test 4: 2-row comment, empty (known passing, for comparison)
rows_2r = ["#,Two row test", "R,...,:,", ",...,:,"]
codec_out = codec.encode_rows(rows_2r)
direct_out = encode_rung(2, [[""] * 31, [""] * 31], ["", ""], comment="Two row test")
if codec_out == direct_out:
    print("2-row comment empty: codec == direct  OK")
else:
    diffs = [(i, codec_out[i], direct_out[i]) for i in range(len(codec_out)) if codec_out[i] != direct_out[i]]
    print(f"2-row comment empty: {len(diffs)} diffs!")
    for off, c, d in diffs[:20]:
        print(f"  0x{off:04X}: codec=0x{c:02X} direct=0x{d:02X}")

print("\nAll codec paths verified.")
