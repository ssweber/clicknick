# "These Aren't the Rungs You're Looking For"

### How I reverse-engineered a PLC editor's clipboard format so my bytes could paste without any problems

---
For years I haven't been able to test my CLICK PLC programs. I've got dozens of machines whose logic is stuck in an editor with no simulator, no scripting API, and no documented file format. So I built [pyrung](https://ssweber.github.io/pyrung/), a Python DSL where `with Rung(condition): instruction` maps directly to a ladder rung, meaning you can write logic in Python and test it with pytest.

But I don't want to transpose after testing. The missing piece was getting rungs from Python into the CLICK editor without retyping them. There's no documented import format, but I found it does put ctrl-c rungs onto the clipboard in some binary format. Maybe I could figure it out. With an AI that could hold context across hex dumps and structural hypotheses, I decided to give it a go.
---

Things started quickly and I thought it'd be a matter of days to figure out. Place bytes on the private clipboard, spoof the window handle so CLICK thought the paste came from itself, and write addresses to the project database so contacts wouldn't draw as blank placeholders. Done.

The workflow that emerged was simple: a CSV file describing each rung's layout on CLICK's grid, a CLI tool that loaded them to the clipboard one by one and asked me whether it worked or crashed or came out wrong. We stored `.bin` files for each shape that captured the known-good bytes so we could diff against them later. Each new rung shape started as a native copy from CLICK and graduated when our synthetic bytes could paste without noticeable problems.

## The Problem

The first few shapes worked. CLICK accepted simple contacts & basic wires.

Then we added instructions and that broke the rung. What should paste as one rung came back as multiple rungs with phantom `NOP` instructions jammed between them.

The approach that had gotten us this far stopped working. Early on, byte diffing was all we could do. We didn't know the format so we captured native bytes, diffed against synthetic, and patched the differences one by one. Instructions introduced variable-length data and suddenly every new shape produced new differences. The AI built elaborate theories about each one, generated patch variants, ranked candidate bytes, and wrote handoff notes that read like desert island scribbles. The explanations were internally consistent and often wrong. I was learning hex as I went and the answer had to be simpler.

I almost gave up, not because the problem was hard but because the approach didn't generalize. You can't diff your way to understanding a format.

We needed a coherent model, so we went back to the basics. Stripped out contacts and instructions entirely and just got empty rungs working, then rungs with wires, then multi-row rungs. Byte 'close-enough' matches against native captures.

## Stop Hex Diffing

LLMs are *magnetically attracted* to hex diffs. Give an AI two binary files and it will compare them byte by byte, build elaborate theories about every difference, and confidently explain which offset controls what. The explanations sound great and they're often wrong.

The cell grid has rigid structure: 0x40 bytes per cell when empty and 32 cells per row. But once we added content, the AI got confused. "The comment data is spilling over into column A." No it wasn't.

It had built a complex model entirely from hex diffs: a 32-entry seed table, a continuation stream for overflow, shape-dependent seeding rules. We had a huge if/else chain encoder for some cases; elaborate, internally consistent, and mostly hallucination. The wrong model generated correct bytes for simple cases, so there was no reason to question it until extending it to multi-rung comments became impossible. I was about to remove comment support entirely.

### More Like a GUI Memory Dump Than a Spec

As an example, byte `+0x19` in each cell was originally called "left wire." It got renamed to "segment flag" once we realized it recorded row-level branching boundaries. Row 0 is always exempt; lower rows compute their boundary from the T-junctions, vertical wires, and contacts above them. We have a formula that works for rungs built top-down, but the source code comment still reads: *"Click's native seg flags depend on editor creation order."* If a user inserts a row above in the GUI, the original row stays exempt instead of row 0. The format encodes how the user built it.

If we just write `0x00` it breaks, so it matters, but it made it hard to decide what is GUI session noise and which bytes mattered.

## Push, Push, Push

The question that cracked it was simple: "Are we sure the comments aren't just an overlay that inserts and pushes things at known safe spots?" The AI initially argued no because the wire flag offsets were different between the two regions. I pushed back. The AI ran the math and every wire flag, every NOP byte, every linkage byte across all 63 flag positions mapped perfectly once you accounted for the displacement. The "mysterious offset shift" was a fixed constant. We didn't need the if/else chain. The cell grid had just been pushed forward by the comment payload.

All that complexity simplified away. Each insight cascaded into the next because the AI could run the address math fast enough to keep up. The 32-entry header table turned out to be one entry plus a payload region. The "separator" between rungs turned out to be the next rung's preamble. The instruction "seed bytes" were just payload content at those addresses. The whole format collapsed to: ramp, dword, payload, grid. Repeat per rung.

We'd been documenting what we saw in the hex rather than what produced it. Once we asked "what if there's only one structure that got displaced," everything fell into place.

In code, it's two lines:

```python
struct.pack_into('<I', out, 0x0294, len(payload))
out[0x0298:0x0298] = payload
```

Write the payload length as a dword, then slice-insert the payload at the boundary between the rung preamble and the cell grid:

- Everything from 0x0298 onward shifts right by `len(payload)`
- The cell grid, normally starting at 0x0A60, lands at 0x0A60 + payload length instead
- No pointers to update, no offsets to rewrite, just insert and push

## The Mind Trick

We place our bytes on the clipboard under the private format. CLICK reads them back, checks whatever it checks, and renders a rung. A rung we wrote in Python, from a CSV, that never touched the editor until this moment.

*These are perfectly normal rungs I copied myself.*

---

*The work described here lives in two repos: [clicknick](https://github.com/ssweber/clicknick) (clipboard glue, live verification) and [laddercodec](https://github.com/ssweber/laddercodec) (the binary codec). The reverse engineering ran from March 2–24, 2026, across roughly 200 commits, with a human doing the pasting and an AI doing the byte analysis. The format remains undocumented by its creator. Our encoder doesn't mind.*