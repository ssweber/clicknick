# "These Aren't the Rungs You're Looking For"

### How I reverse-engineered a PLC editor's clipboard format so my bytes could paste without any problems

---

CLICK Programming Software does not have a simulator, a scripting API, or a documented clipboard format. What it *does* have is a paste function that accepts raw bytes from the Windows clipboard, and a very particular opinion about what those bytes should look like.

This is the story of how I taught it to accept mine.

---

## The Setup

The CLICK PLC editor stores ladder logic — contacts and coils on horizontal rails like rungs of a ladder. Copy a rung, and the editor serializes it to a binary blob under a private clipboard format name. Paste, and it reconstructs the rung from those bytes.

I wanted to write ladder logic in Python using [pyrung](https://ssweber.github.io/pyrung/) — a DSL where `with Rung()` maps to a ladder rung — test it with pytest, and then get it into the CLICK editor. Going the other direction, decode a rung from CLICK back into CSV, and codegen it back to pyrung source. A full round-trip between Python and the editor.

But first we needed a way to describe rungs as data. There's no standard for representing ladder logic in a text format. So we invented one: a CSV where each row is a grid row, each column is a cell position (A through AE for conditions, AF for the output), and the values are tokens — contact addresses, wires, junctions, instructions:

```
marker, A,   B, C, ..., AF
#,      Two contacts in series
R,      C20, C21, -, ..., out(C19)
```

An OR topology with a branch? Add a row. `T` marks the junction-down, `|` continues the vertical wire:

```
R, -, T:X001,    T, -, ..., latch(Y001)
,  -, T:rise(X002), |, -, ...,
,  -, fall(X003),    -, ...,
```

The wire routing was the part that almost broke the CSV format. In the binary, a T-junction can connect either to the right edge of the diagonally-down cell or to the left edge of the cell directly below — and which one depends on the topology. I almost thought we'd have to scrap the whole CSV idea and go back to some structured format. But the `T:` prefix solved it cleanly: `T:X001` means "this cell has both a junction-down wire *and* a contact." The wire and instruction coexist in one cell, just like they do in the binary (where wire flags and instruction blobs share the same cell structure). The CSV survived.

It mirrors the cell grid 1:1. Each cell in the CSV maps to a 0x40-byte cell in the binary. And pyrung's pin rows mapped naturally. A timer in pyrung has two pins — enable and reset — each with its own condition. In the CSV, that's just two rows:

```
R, C70, -, ..., on_delay(T2,TD2,preset=5000,unit=Tms)
,  C71, -, ..., .reset()
```

Row 0 is the enable condition and the timer instruction. Row 1 is the reset condition with `.reset()` on the AF column. That's exactly how CLICK lays it out in the cell grid — two rows, two conditions, one multi-row instruction. Pyrung's pin row abstraction wasn't designed for this CSV format, but a careful grid model in one project became the obvious serialization for another.

The CSV became the contract between all three layers: pyrung generates it, laddercodec encodes it, and during the RE work it gave us a shared language — "column B, row 1" instead of hex offsets.

No import function exists in CLICK. The only door in is the clipboard.

The mission: figure out what bytes CLICK expects, produce them synthetically, and wave our hand at the editor. *These aren't the rungs you're looking for. Move along.*

## Can We Even Get In?

Before any reverse engineering: can we put bytes on the clipboard and have CLICK look at them at all?

CLICK uses a private clipboard format — format 522. I went back and forth with Claude, trying different clipboard mechanisms, getting silent rejections. Maybe there's a checksum. Maybe CLICK validates the source process. Nothing. Nothing. Nothing.

And then the rung appeared.

Fist-pumping-the-air, alone-in-my-office, shouting-at-the-monitor appeared. Our bytes had become a rung.

The trick was ownership. Call `OpenClipboard(0)` and you're an anonymous process. Call `OpenClipboard(click_hwnd)` — passing the handle of CLICK's own window — and Windows marks the clipboard as owned by CLICK. The editor reads back, sees its own window as the source. Our Python process is invisible.

That's the actual Jedi mind trick. Not in the bytes. In the ownership spoof.

One early gotcha: CLICK refused to paste rungs whose addresses didn't exist in the project database. I'd paste a rung referencing `X001` and the contact would appear, but the nickname wouldn't resolve. The fix was obvious — `clicknick` already had ODBC access to the `.mdb`. Insert the address first, then paste the rung.

## "Working 2 series with immediate"

March 3. The commit message is perfect: `Working 2 series with immediate`. Not "implement two-series support." Just: *working*.

First time the encoder produces a rung with two contacts in series — one an immediate value — and CLICK accepts it. The bytes round-trip. It feels like picking a lock and hearing the first pin click.

Ninety seconds later, a cleanup commit reorganizes header byte variants. The pattern that will repeat for the next week: win first, understand second.

## The Nightmare

Then came the rung that broke everything.

`X001,X002.immediate,->,:,out(Y001)` — straightforward two-contact topology. Should paste as one rung. Instead, it came back as multiple rungs with phantom `NOP` instructions jammed between them. Pasteback payloads were wrong sizes: 20480, 12288, 73728. The correct answer was 8192.

Something was telling CLICK to split the rung, and I couldn't figure out what.

I almost gave up. Not because the problem was hard, but because the *variants* seemed infinite. Each cell has 64 bytes. The grid has 32 columns and up to 32 rows. The pre-grid region is another two kilobytes. And I was working with an AI that desperately wanted to hex-diff everything.

## Stop Hex Diffing

LLMs are *magnetically attracted* to hex diffs. Give an AI two binary files and it will compare them byte by byte, build elaborate theories about every difference, and confidently explain which offset controls what. The explanations sound great. They're often wrong.

The cell grid has rigid structure — 0x40 bytes per cell, 32 cells per row. But the AI kept constructing narrative explanations for each byte difference. "The instruction data is spilling over from column A into column B and C." No it wasn't.

The mysterious "Phase A" was the peak. The AI had built an entire mental model — a pre-grid phase with a 32-entry seed table, a continuation stream for overflow, shape-dependent seeding rules. It produced working encoders for some cases. Elaborate, internally consistent, and mostly hallucination.

I literally had to type **STOP HEX DIFFING** in all caps.

The breakthrough came from talking with a *different* LLM — deliberately *without* hex access. No binary files attached, just the structural question: "If you had a fixed-size cell grid and needed to add variable-length data, how would you do it?" The bytes were a tar pit. Every AI that could see them sank in. The one that couldn't gave the right answer immediately.

You wouldn't rewrite the grid. You'd insert the payload before it and push the whole thing forward.

## Push, Push, Push

If the story has a one-word theme, it's *push*.

March 12. One commit. Everything simplifies.

**Payload first, grid second, and the grid gets pushed forward by the payload length.**

In code, it's a single line:

```python
out[0x0298:0x0298] = payload
```

A Python slice-insert. Everything at 0x0298 and beyond shifts right by `len(payload)`. The cell grid, built assuming it starts at 0x0A60, now starts at 0x0A60 + payload length. No pointer adjustment. Just insert and push.

The supposed 32-entry header table wasn't metadata at all. We'd been reading through the pushed payload with the wrong frame, seeing structure in displaced content. Like reading a book that's been cut in half and shelved in two places — the words look like different stories until you realize someone moved the bookmark.

The push insight kept paying dividends. When instruction cells arrived, the same confusion came back: "the instruction data is overwriting adjacent cells!" No. A cell without an instruction is a clean 0x40 block — header, padding, tail. A cell *with* an instruction is header, blob, tail — the blob carries the instruction's class name in UTF-16LE, a type marker, and tagged fields. The cell isn't overwriting neighbors. It's just *bigger*, and the row is wider because the variable-length cell pushed everything after it forward. Same principle, different scale. I had to have a non-bytes-connected LLM walk through it structurally before it clicked.

GPT Codex was especially byte-happy — it wanted to map every offset change to a corruption theory. Claude was better when directed: "Stop. Look at the two sets of pastes that are working. There's probably a simpler way to produce those bytes than our complicated rule set." Asking the AI to find patterns in *successes* instead of theorizing from *diffs* was the most reliable way to get unstuck.

The old model was wrong. But it was useful-wrong — it produced working encoders for the cases we tested, which gave us the captures we needed, which eventually revealed the real structure. Get something working, then revisit "what structure is it really?" The answer was almost always simpler than what we had. *It's probably easier than we're making it.*

## The Workflow

The other half of this project wasn't about bytes. It was about the feedback loop between human and machine.

CLICK is a Windows desktop application. No COM API, no accessibility tree worth using, no headless mode. Someone has to physically Ctrl+V into the editor and Ctrl+C back out. That someone was me.

Early on, each verification cycle meant: generate payload, copy to clipboard, switch to CLICK, paste, take a screenshot, switch back, show the screenshot to Claude, discuss. Slow and error-prone.

So I tightened the loop. The guided verify workflow evolved into a CLI that queued fixtures and prompted me after each paste: `[w]orked`, `[c]rashed`, `[n]ot as expected`, `[s]kip`. If I hit `w`, it told me to copy the rung back, read the clipboard, saved the bytes, and compared them automatically. My job was reduced to: paste, copy, press `w`. Repeat.

Then decoding started working. Once the decoder could read CLICK's clipboard output back into structured CSV, I didn't have to *look at* the pasted rungs anymore. No more screenshots. The agent could read the pasteback as data: contacts, coils, topology. Match or mismatch.

The human became a pair of hands. The machine became the eyes.

## 19 Out of 20

March 9. 19 of 20 encoder shapes pass Click round-trip. Empty rungs, wire-only, wire plus NOP, plain comments across various lengths, edge cases.

Comment encoding had its own twist: the mechanism that saved instruction rungs — header seeding — would *clobber* comment rungs. The format wasn't following one rule. It was following shape-dependent rules.

The `STATUS.md` snapshot was honest:

> **Supported:** Empty rungs, wire-only, wire+NOP, single-line comments (1–1400 bytes)
>
> **Not supported:** Multi-row comments, contacts, comparisons, AF coils, general instruction placement

The next day, 25 golden regression tests froze the victories as byte-exact fixtures. Any future encoder change has to keep these passing.

## The Split

March 11. In `clicknick`: the local ladder codec gets replaced with an import from `../laddercodec`. Sixteen thousand lines of capture-and-RE infrastructure get deleted.

In `laddercodec`: the standalone package arrives with everything intact. Same encoder, same decoder, same 25 golden fixtures.

The messy lab gets a clean room. `laddercodec` owns the codec truth, `clicknick` owns the clipboard glue.

## Tightening

The next two weeks are less dramatic but more precise. The decode pipeline matures. Wire classification simplifies: wires get classified by `(right, down)` behavior instead of three independent flags.

And then there was the segment flag.

Byte `+0x19` in each cell. Originally called "left wire." Renamed to "segment flag" once we realized it wasn't about wires at all. We wrote the computation logic — a boundary rule based on where T-junctions and contacts sit. Ripped it out. Rewrote it. Ripped it out again. The source code comment still reads: *"Click's native seg flags depend on editor creation order."* Not structural position. Not topology. The *sequence in which the user placed elements in the GUI*. That's the kind of detail that makes you question whether you're reverse-engineering a format or a mood.

The golden fixtures saved us here. Every time the segment logic changed, we knew exactly which shapes broke. Without that regression suite, we'd have been fixing one case while silently breaking three others. The fixtures didn't make the problem less maddening, but they made the maddening *visible*. When you finally got all 36 green, you could trust it.

Instruction-bearing rungs got their own pass: cell markers, instruction index ordering, AF coil tail bytes, multi-row headers. By March 18, multi-row instruction rungs with branch topologies pasted correctly.

March 20: the public API stabilizes at 10 exports. `encode()`, `decode()`, `read_csv()`, `write_csv()`, `Rung`, and the instruction types. The model has stopped being a moving target and started being a library.

By late March, the encoder covers contacts, coils, timers, comparisons, copy instructions, counters, shift registers, math blocks, drum sequencers, subroutines, and more. Each one discovered the same way: capture a native rung from CLICK, decode it, find the pattern, write the encoder, verify the round-trip. The source code still has comments like: *"Fields present in native captures but confirmed cosmetic (not written) — kept for fidelity."* We found these bytes in CLICK's output, our tests pass without them, and we write them anyway because we're not entirely sure.

## The Mind Trick

There is no spec. Every byte was learned by experiment — form hypothesis, generate payload, paste, recapture, inspect, adjust. The protocol never changed. Just the understanding behind it.

And every time the paste succeeds, it's the same trick. We place our bytes on the clipboard under format 522. CLICK reads them back, checks whatever it checks, and renders a rung. A rung we wrote in Python, from a CSV, that never touched the editor until this moment.

*These aren't the rungs you're looking for.*

*These are perfectly normal rungs I copied myself.*

*Move along.*

---

*The work described here lives in two repos: [clicknick](https://github.com/ssweber/clicknick) (clipboard glue, live verification) and [laddercodec](https://github.com/ssweber/laddercodec) (the binary codec). The reverse engineering ran from March 2–24, 2026, across roughly 200 commits, with a human doing the pasting and an AI doing the byte analysis. The format remains undocumented by its creator. Our encoder doesn't mind.*
