# Changelog

<!-- Style guide: Entries follow the section "The CHANGELOG" in the bob plugin's `writing` skill.
     ClickNick has users, so an entry says what the user will see and what they must do.

     Review and condense before release — entries accumulate during development and
     should be edited into shape before moving from Unreleased to a version heading. -->

## Unreleased

### Changed

- The Simulator now keeps a saved switch position on an input that no installed module has and no rung uses. 0.25.0 removed it when it loaded your saved settings, and the notice said that no installed input had the address.

### Fixed

- ClickNick now builds the workspace when it cannot read the hardware in CLICK's Project.ini. This happens for a module that ClickNick does not know yet. Check Program, Review Changes, `clicknick-cli` and the Simulator then work. 0.25.0 stopped with **Could not build the workspace**, and the Simulator's hardware panel said that no CPU was configured. The panel now shows the read error. A message box in the main window tells you that ClickNick does not know which addresses are analog inputs. If you turn on the check Comparison Operand Has No Ladder Writer, Check Program then reports an analog input that a comparison reads as a value that nothing writes. For a project with no CPU, the panel now says that the Simulator still runs the program, that the dashed cards show the X and Y addresses that the program uses, and how to see your hardware.
- ClickNick now builds the workspace for a CLICK PLUS project with an empty option slot, and the Simulator shows the project's hardware. CLICK 4.00 saves an empty option slot as the slot cover C2-FILL. ClickNick now reads C2-FILL through pyclickplc 0.11.2, and the Simulator shows it as a card with no I/O. For such a project, 0.25.0 showed **Could not build the workspace**, and the Simulator showed no hardware.
- The Simulator no longer shows an error when you link an address that no rung in the simulation names. The simulation can link only an address that a rung names. A slot that a rung reaches only through a range, such as X005 in `pack_bits(X003..X010, DS1)`, does not count. The bench link now waits. The **Wiring** menu shows it as `bench, waiting`, and the input's tooltip says what it waits for. While the link waits, the simulation runs the program's own wiring on that input. To apply it, name the address in a rung, in CLICK or in the workspace's `src/plc`, and write the program to the simulation. 0.25.0 showed an error, such as `Linking X001 failed: cannot link X001: unknown tag: X001` in an empty project, and did not keep the link.
- The Simulator now keeps a bench link that you saved on an address that no rung in the simulation names. The link waits, and the Simulator applies it after you write a program in which a rung names the address. 0.25.0 showed an error when the simulation started, and removed the link.
- The Simulator now keeps a bench link or a force on an address when you write a program in which no rung names that address. This holds for either end of a bench link. The link waits until a rung names both ends again. 0.25.0 removed the link and the force.

## v0.26.0 - 2026-11-20

Every ClickNick user should upgrade for the fixes from pyrung 0.18.0 and laddercodec 0.5.0. The Simulator now runs a `copy()` of a number into TXT in your `src/plc` code the same as a CLICK PLC. Review Changes now pastes some code from `src/plc` correctly. 0.25.0 pasted that code wrongly.

A nickname, comment or initial value with a character such as `é` or `°` now arrives unchanged when you move it between ClickNick and CLICK in a nickname CSV. ClickNick now writes nickname CSVs in cp1252, the encoding that CLICK uses, and loads the ones that CLICK exports.

Read Breaking changes before you upgrade if a script of yours reads a nickname CSV that ClickNick writes, if a nickname, comment or initial value holds a character that CLICK cannot hold, such as `→` or an emoji, or if you write code in `src/plc`. If you pasted rungs from `src/plc` with 0.25.0's Review Changes, read the entry under Fixed about the code that it pasted wrongly.

### Breaking changes

- ClickNick now writes every nickname CSV in cp1252, the encoding of CLICK's own nickname export. 0.25.0 wrote UTF-8. This covers **File > Export to CSV** in the Address Editor, **Sync** in CSV mode, **Save Copy and Load** for CLICK's Address.csv, and the `nicknames.csv` files at the top of the workspace folder and in its `csv/` folder. Nothing changes for a file whose nicknames and comments are plain ASCII. If a script of yours opens one of these files as UTF-8, a character such as `°` or `é` fails to decode or reads as the wrong character. Open the file as cp1252, or read it with pyclickplc's `read_csv`. `read_csv` reads either encoding.
- A character that cp1252 does not have, such as `→` or an emoji, is now an error in a nickname, comment or initial value. CLICK cannot hold such a character. It turns an emoji that you type into a comment into `??`.
  - The Address Editor shows the error on the row, and the error names the character. Sync and **Export to CSV** write nothing while a row has this error. Replace the character. 0.25.0 accepted such a character in a nickname or a comment. It refused one in an initial value.
  - The workspace no longer builds for a project that holds such a character. The Simulator, Check Program and **Workspace > Review Changes** then do not run, unless an earlier workspace exists. The Workspace group says **Could not build the workspace**, and its message lists the addresses and fields to change. 0.25.0 built that workspace. Change the character in the Address Editor and Sync.
  - `clicknick-cli tag apply` stops, and lists the addresses and fields the same way. For a character that you put in `src/plc/tags.py`, it names only the first one. Change that character in `src/plc/tags.py`.
  - **Save Copy and Load** for CLICK's Address.csv writes no copy. Its message tells you to change the character in CLICK, save, and try again.
  - **Ladder > Compare with > Other CLICK window** compares without the other project's nicknames, and the status line says why.
- The workspace now holds an empty rung in place of each rung in CLICK's last save that ClickNick cannot copy into the workspace unchanged. The **Paste Again** notice names each of these rungs and says why. The Simulator does not start until you fix them. 0.25.0 did this only for a rung with an instruction that ClickNick cannot read. The rungs are:
  - A rung that ClickNick cannot read at all. If it cannot read the rest of the program either, the notice says that those rungs are missing from the workspace too.
  - A rung with a text compare that a ladder CSV can show in two ways, such as `"A"=="B"` compared with `"C"`.
  - A rung that CLICK's Syntax Check splits into more than one rung, such as a NOP fed from the left rail beside outputs. CLICK keeps such a rung whole after a paste until you run Syntax Check. Run Syntax Check in CLICK, then save the project.

  For a rung of the first two kinds, paste the rung again from your own copy of the program, or fix it in CLICK.
- Code that you write in the workspace's `src/plc` now runs on pyrung 0.18.0, and pyrung refuses more code. The Simulator, Check Program, **Workspace > Review Changes** and `clicknick-cli rung apply` refuse code that cannot run, such as `fill()` into one register. 0.25.0 built such code, and it failed at the first scan or only set an error flag. Review Changes and `rung apply` also refuse code that CLICK's editor rejects, such as a range that skips addresses. 0.25.0 exported such code, and CLICK could not load it. Each message says what to write instead. [pyrung 0.18.0's changelog](https://github.com/ssweber/pyrung/blob/v0.18.0/CHANGELOG.md) lists each case.

### Changed

- When ClickNick writes a row to CLICK's database and the row has no initial value, it now stores `0`, except for a TXT row. CLICK stores the same for a row that it creates. 0.25.0 stored an empty value. CLICK reads both forms the same way. After a Sync or a save to a nickname CSV, the Address Editor shows `0` as the initial value of such a row, the same as a row that CLICK made.
- Workspace setup now asks whether to create or use the workspace as soon as you pick a folder with **Choose Location...** or **Find Existing...**. Yes does the same as **Create Workspace** or **Use Workspace**, and No leaves the folder in the form. A workspace that you pick from the list still waits for the button. 0.25.0 only filled in the form, and made the workspace only when you clicked **Create Workspace** or **Use Workspace**.
- **Save Clipboard to CSV**, and `clicknick-rung save` to a .csv file, now refuse to write a CSV when the clipboard holds one of these rungs. The message names the rung. Fix the rung in CLICK and copy it again.
  - A rung that ClickNick cannot read.
  - A rung with a text compare that a ladder CSV can show in two ways.
  - A rung that CLICK's Syntax Check splits into more than one rung.
  - A rung whose comment ClickNick cannot read.

  0.25.0 refused only a rung that ClickNick cannot read.
- A rung in CLICK's last save with a value that CLICK's editor refuses, such as the compare `DH70 == DS39`, now makes the **Paste Again** notice ask you to paste the whole program again. For a compare such as this one, 0.25.0 put an empty rung in the workspace in its place. The Simulator now runs the program as CLICK saved it.
- Review Changes, **Load Ladder CSV to Clipboard** and `clicknick-rung load` now refuse a CSV that holds an `UNDECODED` marker, or a comment that starts with `UNDECODED comment:`, and name the rung. Other programs that read CLICK's ladder can write the marker in place of a rung that they cannot read, and the line in place of a comment that they cannot read. CLICK cannot hold the marker. Put the rung's logic in place of the marker, or remove the marker. Delete the `UNDECODED comment:` line, or put back the comment. 0.25.0 refused the marker as an unknown instruction, and did not name the rung. It pasted the `UNDECODED comment:` line into CLICK as part of the rung's comment.
- ClickNick now reads a Modbus TCP address with leading zeros in a ladder CSV, such as `192.168.001.010`, as CLICK's dialog saves it, `192.168.1.10`. Review Changes no longer lists such a rung as changed, and a paste writes the address without the zeros. This comes from laddercodec 0.5.0.

### Fixed

- ClickNick now loads a nickname CSV in cp1252, such as one that CLICK exported with a non-ASCII nickname, comment or initial value. 0.25.0 refused the file. ClickNick still loads a nickname CSV in UTF-8.
- A project that has a comment or a non-default setting on SD132, SD133, SD134 or SD135, but no nickname there, now builds its workspace. **Tools > Repairs > System Nicknames** no longer offers to fill in a nickname at those four addresses. 0.25.0 stopped the build for such a project. The fix comes from pyclickplc 0.11.1.
- If the CLICK window closes or shows another project while Workspace setup shows a location that you have not applied, ClickNick now shows a warning that the location was not applied. Open Workspace setup and choose the location again. 0.25.0 closed Workspace setup without a message, so you might not notice that no workspace was made.
- **Workspace > Review Changes** and `clicknick-cli rung apply` now show the source of a rung that you added to `src/plc` without a `# Rn` comment. 0.25.0 could show another rung's source in its place, so the rung looked duplicated.
- Check Program now runs, and Choose Checks now opens, when the saved check selection names a check that pyrung does not have, such as a check that pyrung renames in a later release. ClickNick removes that name from the selection and keeps the other checks. It tells you once which names it removed, and from which file. If no check is left in the selection, the message says so, and Check Program runs no checks until you choose some in Choose Checks. `clicknick-cli check` prints the same note. 0.25.0 showed an error and ran no checks.
- **Workspace > Review Changes** and `clicknick-cli rung apply` pasted the `src/plc` code in this list wrongly in 0.25.0. If you pasted one of these rungs with 0.25.0, check it in CLICK. The fix comes from pyrung 0.18.0.
  - `copy()` of a constant into DH or YD, or `fill()` of one into DH, when the constant's hex form holds an E, such as `copy(14, dh[1])`. 0.25.0 pasted `copy(Eh,DH1)`, and a CLICK PLC stores 0 for that. ClickNick now pastes `copy(14,DH1)`.
  - Text with a double quote in it, in a `copy()`, a `search()` or a compare, such as `copy('a"b', txt[1])`. 0.25.0 pasted `"a""b"`, and CLICK reads it as `a""b`. ClickNick now pastes the text as you typed it.
  - A Copy between TXT and a number register, such as `copy(txt[1], ds[1])`. 0.25.0 pasted it with no conversion. CLICK's Copy dialog never saves that form. ClickNick now pastes the conversion that the Simulator runs, such as `convert=to_value`.
  - `.sum()`, `.max()`, `.min()`, `.median()` or `.mean()` over tags whose addresses skip, such as X001 and X003. 0.25.0 pasted the range X001 to X003, and CLICK also read X002. Review Changes and `rung apply` now refuse this code.
- The Simulator now runs two kinds of Copy between TXT and numbers in `src/plc` the same as a CLICK PLC. The fix comes from pyrung 0.18.0.
  - `copy()` of a number into TXT, such as `copy(25, txt[1])`, stores `2` in TXT1 and `5` in TXT2. 0.25.0 stored the number 25 in TXT1. A Copy of a number into TXT that you made in CLICK's Copy dialog already ran correctly in 0.25.0.
  - `blockcopy()` from TXT into number registers, with no `convert=`, reads each TXT as a digit. In 0.25.0 the scan failed with an error when one of those TXT addresses was blank or held a letter.

## v0.25.0 - 2026-11-18

After a Sync, CLICK's ladder now shows the new nicknames. You no longer need CLICK's Address Picker or a reopened project to see them. Every ClickNick user should upgrade.

Read Breaking changes before you upgrade. ClickNick now requires Python 3.13 or 3.14.

### Breaking changes

- ClickNick now requires Python 3.13 or 3.14. 0.24.1 also ran on Python 3.11 and 3.12. If you install with `uv tool install clicknick`, uv downloads a suitable Python for you. Python 3.15 is not supported yet because pywin32 has no build for it.
- The Address Editor now shows an error for the nicknames, initial values and comments in this list. 0.24.1 accepted them. Sync writes nothing while a row has an error. Rename the nickname, or fix the value or the comment.
  - A nickname that is `max`, `min`, `mdn`, `avg`, `rand` or `abs` in any letter case. CLICK 4.00 reserves these words.
  - A nickname that holds a comma.
  - An initial value of any type but Text that holds an underscore (`1_000`) or a character outside ASCII.
  - A HEX initial value that starts with `0x`.
  - A comment that starts or ends with a line break or another control character.
- The workspace no longer builds when a nickname inside a `:block` range is `max`, `min`, `mdn`, `avg`, `rand` or `abs`, holds a comma, or starts or ends with a tab. 0.24.1 built the workspace from these nicknames. The Simulator, Check Program and Review Changes then do not run for that project, and the Workspace group says **Could not build the workspace**. The build reads the nicknames from the project as CLICK last saved it. Rename or trim the nickname in the Address Editor, Sync, and save the project in CLICK.
- ClickNick no longer loads a nickname CSV that has the wrong Data Type for an address, or a row with more cells than the header. `TXT` now counts as a wrong Data Type, because CLICK writes `TEXT`. The error message gives the line number. Fix that line in the file. Review Changes names the line too when the nicknames.csv in a folder has one of these problems or a bad Address. 0.24.1 offered to stage the nicknames.
- The Simulator's Console no longer has the `prove`, `log`, `note`, `candidates`, `accept`, `deny`, `suppress` and `spec` commands, because pyrung 0.17.0 removed them. Typing one gives an unknown-command error. To check a property that `prove` or `spec` checked, write a pytest test in the workspace with `force()` and `run_for()`. To read past scans, use `cause` and `effect`.
- The Data View Editor no longer accepts a New Value on SC50 (`_PLC_Mode_Change_to_STOP`) or SC51 (`_Watchdog_Timer_Reset`). 0.24.1 accepted one, and then showed an error when you wrote it. Set these bits from the ladder program instead. A .cdv file that holds a New Value on them still opens, and **Verify MDB & CDV** reports the value.
- The Address Editor no longer has **File > Refresh**. It only discarded your unsaved edits. It did not read CLICK's database or the CSV file again. To discard your edits, use **File > Discard Changes**.
- Review Changes no longer has a **Skip** button. The button only moved to the next program that you had not pasted yet. It did not leave anything out of the paste. To go to another program, click its row in the list.
- The tag annotation dialog no longer has a **lock** check box. `clicknick-cli tag set-flag` and `tag clear-flag` now reject `lock` as an unknown flag.
- The messages of ClickNick, `clicknick-cli` and `clicknick-rung` now say what failed and what to do. Many tooltips and help texts are reworded too. If a script of yours matches on ClickNick's message text or on a `clicknick-cli` reply, check it.

### Added

- ClickNick now redraws CLICK's ladder after a Sync. The ladder then shows the new nicknames. To do this, ClickNick opens CLICK's **File > Import > Nickname** and cancels it. CLICK then reads the names again. CLICK's Open dialog shows for a moment, and the window that you were in stays in front. CLICK also counts the project as changed. When you close CLICK, it asks you to save the project with the new nicknames. If a CLICK dialog is in the way, close it and choose **Tools > Redraw Nicknames in CLICK**. To redraw only when you choose that command, turn off **Tools > Redraw Ladder on Sync**. ClickNick remembers the setting. The first time CLICK redraws after a Sync, ClickNick shows a notice. The notice says what ClickNick did and how to turn the redraw off.
- The Simulator's Console has two new commands. `assert Tag == value` checks the value of one tag. `run until <condition> within <scans or time>` runs scans until the condition holds, and fails if the limit comes first.
- The Simulator's Modbus server now accepts a write to an X, T or CT bit, or to a coil between X or Y slots, the same as a CLICK PLC. An HMI or another Modbus client can now change a simulated input. 0.24.1 refused the write with exception 02.
- The Data View Editor now writes T and CT bits. 0.24.1 reported an error for them. The Data View Editor still does not write X.

### Changed

- `upstream:` now stops at a rung that calls a subroutine, and `downstream:` now goes on into the subroutine. This applies to the Address Editor's filter box and to the Console's `upstream`, `downstream` and `dataview upstream:` commands. For a tag that a subroutine writes, `upstream:` shows the tags that feed it inside the subroutine and the conditions of the rungs that call the subroutine. It no longer shows the tags that feed those conditions. For a tag in such a condition, `downstream:` now shows the tags that the subroutine writes, and the tags that they feed. 0.24.1 left them out.
- ClickNick now trims spaces and tabs from the start and end of nicknames, and of initial values of any type but Text. CLICK does the same. This applies to what you type, paste, fill or replace, to **File > Import from CSV**, and to the data that ClickNick loads. A comment keeps its spaces and tabs, because CLICK stores a comment with the spaces that you type at its ends. If your project already has a nickname or an initial value with a space or a tab at either end, it opens with an unsaved **Trim spaces** edit. Sync to write it to CLICK. Until you Sync, closing ClickNick asks whether to save the edit. If you undo the edit, the spaces and tabs show as errors and Sync refuses them.
- ClickNick now rejects an address with a stray `u`, such as `DS1u`, or with a digit character other than 0-9. CLICK rejects them too. 0.24.1 read these as `DS1`.
- The Address Editor no longer shows a box when a Sync or a Save succeeds. Its status line says how many rows it wrote, such as "Synced 3 rows".
- The Dataview Editor is now called the **Data View Editor**, and every title, menu and message writes **Data View** the way CLICK does.
- The Tag Browser now shows a bit's Retentive setting after a comma, as in `BIT, Retentive`. 0.24.1 showed `BIT = Retentive`. That read as the bit's value. An initial value still follows `=`, as in `BIT = ON, Non-retentive`.
- The Workspace setup window now closes when you close the CLICK window it belongs to. It already closed when that CLICK window opened another project.

### Fixed

- The Simulator now reads a PLC data file the way CLICK writes it. A Text value of a space or a comma loads as written. 0.24.1 loaded a space as `$20`. The Simulator now starts from a file with a DF value that CLICK shows as `Err-Format`, and an analog input on that DF keeps the value it had. When a comma is next to an empty Text address, the Simulator cannot tell what some Text addresses hold. It starts those addresses at their power-on values, loads the rest of the file and names them, such as TXT13-TXT20. To load them too, replace the comma in their Text values in CLICK and save the data file again. 0.24.1 left the comma's address blank and moved each Text value after it to the next address.
- The Simulator now runs two more instructions the same as a CLICK PLC. A Copy of a NaN from DF into DD stores -2147483648. 0.24.1 stored 0. A Copy Pack of text such as `1E39` into DF stores +Inf or -Inf and leaves SC43 (`_Out_of_Range`) off. 0.24.1 left the DF as it was and turned SC43 on.
- The Simulator's Modbus server now handles these cases correctly.
  - When a client sends several requests at once, the server answers each one with the transaction id of its request. 0.24.1 answered only some of them, and some replies had the wrong transaction id.
  - A NaN that a client writes to a float address reads back with the same bits. 0.24.1 read back FFFF FFFF for any NaN.
  - The register after XD8 and the one after YD8 read 0, as on a CLICK. 0.24.1 answered exception 02.
  - On Windows, the server keeps accepting clients after a client drops its connection before the server has accepted it. 0.24.1 stopped accepting clients.
  - On Windows, when another program already listens on the Modbus port, the Simulator says that its Modbus server could not start, and it offers **Change port...**. 0.24.1 showed no error.
- The Simulator window now shows each failure, each refused Restart and each failed program write in one banner. 0.24.1 showed the same message in two banners, one above the other.
- If the Simulator writes a program but cannot put the switch position back, its message now starts "The program was written". 0.24.1 said "Restoring simulator settings failed", although no saved settings were being restored.
- The Simulator's tooltips now say what a bench link is and when it applies. A bench link is wiring that you add in the Simulator and that the program does not declare. The **Wiring** button's tooltip now says so. The tooltip of a linked input no longer ends with empty brackets when the link has no delay or response. After **Save link to project**, the tooltip and the note say the same thing. Both say that the program's link replaces the bench link when the simulation loads the program from your next Sync.
- Check Program reports fewer findings that are not real. It sees the writes of every instruction, writes through a pointer and writes inside a For loop. It no longer calls a comparison always false when the Math that writes the tag wraps past the end of its type, when a Copy clamps the value that it stores, or when a float tag has whole-number `min` and `max`. It no longer reports a missing writer or a preset that stays 0 on a linked feedback (a tag with `link=`), or on a system point that the PLC sets, such as the RTC hour. Check Program, `upstream:` and `downstream:` also see every Text address that a Copy to text can write. 0.24.1 saw only the first one.
- Autocomplete in CLICK 4's Receive and Send now appears in Starting Master Address, the status flags and Exception Response. On a Modbus TCP port, 0.24.1 showed it in the IP address field. Starting Master Address now offers only the memory types that the selected Function Code accepts. In CLICK 2 and 3, the local address field of Receive and Send now offers the memory types that any of its Function Codes accepts. In CLICK 4, autocomplete now offers DS and TD nicknames in Out's Delay Setting. In every version, it no longer offers X, T or CT in Out, Set and Reset, because CLICK rejects them there.
- ClickNick now handles the PLC name correctly in these cases.
  - In CLICK 4, the name that you enter at Workspace setup's **Name PLC** prompt now shows in CLICK's System Configuration once you save the project. In a new CLICK 4 project, 0.24.1 wrote the name to a `[PLCName]` section of Project.ini. CLICK 4 ignores that section. 0.24.1 still said that CLICK now identified the PLC by that name. If ClickNick named a CLICK 4 project before, open Workspace setup for that project once. ClickNick then writes the name where CLICK 4 reads it. Save the project in CLICK.
  - When a CLICK 4 project has one name in an old `[PLCName]` section and another where CLICK shows it, ClickNick uses the name that CLICK shows. It opens the workspace and the Simulator settings that belong to that name.
  - ClickNick reads the name when a section or key in Project.ini differs from CLICK's in letter case. It reads the first of a repeated section, the same as CLICK.
  - If you cancel the **Name PLC** prompt, ClickNick no longer shows a message.
- ClickNick now loads a nickname CSV that CLICK exported with a Text initial value of a comma or a double quote. 0.24.1 lost the value or misread the rows after it. A save now writes such a value so that it reads back as written.
- Review Changes now gives the right message in these cases.
  - When pyrung cannot convert a folder, the diff says why. 0.24.1 showed the rungs without their source.
  - When ClickNick fails to type the name into CLICK's New Subroutine window, Review Changes no longer says that the window has no name box.
  - When you try to take a skipped difference of a program that is marked done, the status line says that the program is marked done. 0.24.1 said that the difference was already pasted into CLICK.
  - When the workspace's CSVs are gone, the notice no longer says that CLICK was saved. It says that ClickNick rebuilt the workspace from CLICK's last save, and that the save does not hold every change that Review Changes was pasting. The notice also shows after **Reload from CLICK**.
- `clicknick-rung` now handles these cases correctly.
  - It refuses a `--mdb-path` that names no file, before `load`, `guided` or `program load` copies anything. 0.24.1 ignored the option without a word and added none of the rungs' addresses.
  - When the addresses cannot be added to the SC_.mdb that `--mdb-path` names, `load` stops with an error. 0.24.1 printed the failure and copied the rungs anyway. In `guided` and `program load`, a skip or a quit after that error counts as an error, and the run exits 1.
  - Without `--mdb-path`, it warns when the CLICK window has no SC_.mdb. Its messages about SC_.mdb go to stderr.
  - `guided` says that it compares the rung you copy back with the .bin file saved before. 0.24.1 said that the bytes differ from the encoder's output, but it never compared them with that output.
- `clicknick-cli` now gives the right message in these cases.
  - It tells you to Save the unsaved edits when a CSV file is loaded, and to Sync them when CLICK's database is loaded. 0.24.1 said Sync in both cases. This holds for `prompt-save`, for the replies of `tag apply`, `tag repair-system-nicknames` and `tag upgrade-project`, and for the status line.
  - When a row has an error, `prompt-save` says that nothing is written while any row has one. 0.24.1 blamed the unsaved edits, even when the errors were in rows that you had not changed.
  - `list` no longer says that a workspace is building when there is none.
  - `tag set-range` names a value that is not a number.
- `clicknick-cli` and the Simulator now use the program's name, such as `Fill3`, for an address inside a `:block` range that has no nickname. `clicknick-cli` still accepts the address too.
- Commands that need CLICK's database or the workspace now give the real reason when they cannot run. They no longer tell you to connect to a CLICK window when one is already connected. This applies to the Workspace menu, the Simulator, **Tools > Address Editor**, **Data View Editor**, **Check Program** and **Repairs**, to **Choose Checks**, and to the `clicknick-cli` commands that need the addresses or the workspace.
  - While ClickNick reads CLICK's database, they ask you to try again when it has finished.
  - If ClickNick did not load the database, they tell you to select the window in the CLICK Windows list.
  - With `--db-backend none` (CSV mode), they say that database access is off.
  - Where the nicknames are enough, they also offer **File > Load Nicknames from CSV**.
  - A command that needs the workspace says whether its build failed, is still running or has not started. If the build failed, it gives the reason. So does `clicknick-cli ping`.
- The Workspace group now says **Could not build the workspace** when ClickNick cannot build the workspace, and **Help > About CLICK Project** shows the reason. 0.24.1 said "Analysis failed" or "Build failed", and the choice depended only on whether an older workspace folder existed.
- When ClickNick cannot read CLICK's database and offers a copy of CLICK's address CSV file, the dialog no longer says that you must save a copy to continue. **Cancel** goes on without nicknames.
- **Tools > Repairs > Clean MDB** and **Verify MDB & CDV** now work only on CLICK's database. When the nicknames come from a CSV file, they tell you to load the database from the CLICK window. In 0.24.1, Clean MDB reported an error loading the CSV file as an MDB, and Verify counted the CSV rows as database addresses.
- The Address Editor's footer now counts the errors only in the rows that the filter shows, the same as its other counts. The status bar below it counts the changed rows and the errors in all rows.
- The Address Editor's Replace All no longer adds "No matches found" after it has said that the search text is not a valid regular expression.
- The Address Editor's export option is now called **Export all rows**. It used to say "entire database", but it exports the rows that the editor holds. Those rows can come from a CSV file and include unsaved edits.
- The tooltip of **start** in the Add Block dialog no longer says that the start is 0-based. pyrung starts a block at 1, or at 0 when the block's first address is numbered 0, and the tooltip now says so.

## v0.24.1 - 2026-11-15

### Fixed

- The Simulator's link dialog opens again on Python 3.11 and 3.12, where it failed with a TypeError.

## v0.24.0 - 2026-11-14

### Added

#### Simulate

- **Simulate** runs CLICK's last save on a picture of your CLICK hardware from System Configuration, with input switches, output LEDs, analog values, forces (double-click an output), STOP / STEP / RUN with speed control, and a Modbus server on 127.0.0.1 (port 502 by default) that the Data View editor joins with a Force column.
- X and Y addresses the program uses but no module provides get switches and LEDs on a dashed card at the position they belong to (X2xx on "Expansion 2 - unassigned"), between the real modules.
- Feedback links let an output drive an input, like a contactor's aux contact or a limit switch: drag between an output's label and an input's to add one (a bench link; the Simulator keeps it between runs), cut it to simulate a failed sensor, or save it to the input's comment for the program.
- When you save in CLICK or edit the workspace's ladder source, the Simulator offers to write the new program as CLICK does for a running PLC: in RUN, **RUN Time Edit** keeps every value, timer and force, and **Stop and Write** goes through STOP, keeping retentive values and forces; in STOP or while stepping, **Write** keeps values and the mode. A save that does not convert leaves the old program running, and the Simulator says why.
- Before a write the Simulator lists the forces it will release and the bench links it will drop or move, and afterwards says what was kept and why anything was not: forces on inputs and outputs stay on their addresses, a force on internal memory is released when its nickname moves to another address, and bench links follow their nicknames.
- **Restart** on the Simulator's toolbar starts the simulation over on what the workspace holds now, from power-on values or your PLC data file, with your mode, switches, forces and bench links. It is also offered when a write fails.

#### Console

- Right-click a Simulator point to ask **Why** in the Console, and on an output also **Show simplified logic** or **How (experimental)** to turn it ON or OFF.
- What you do on the Simulator shows in the Console as the matching command.
- The Console refuses `record` and `replay` for now, because they would not capture or show what you do on the Simulator.

#### Review Changes

- Review Changes marks which programs differ from CLICK's last save and shows each one's rung diff, highlighting only the lines and words that changed, with one unchanged rung on each side and separators whose arrows show more.
- It steps through only the rungs that differ, saying which rung to paste over or delete in CLICK, or copies whole programs when you switch **Copy** to **Whole program**.
- You can take or skip each difference: untick **Take this difference** or click its +/- gutter and CLICK keeps its rungs there, the steps are numbered around it, and ◀ ▶ (Alt+Up/Down or F7/Shift+F7) go through every difference across programs.
- **Ladder > Compare with > Folder** compares CLICK's program with any folder of ladder CSVs, such as a copy of another PLC, so you can take only some of its differences; the title and the diff say which folder the changes come from.
- **Ladder > Compare with > Other CLICK window** compares CLICK's program with what another open CLICK window last saved, such as a sister PLC's project: its nicknames start out skipped, the programs only this CLICK has start out kept, and **Refresh from** takes its latest save.
- Review Changes remembers what you pasted until CLICK saves it, also when you switch **Copy**, Sync or open it again, and **Restart** asks before forgetting it.
- It closes once a CLICK save holds everything it was pasting; after a save made before you finished pasting, it stays open, says so, and can keep pasting.
- A program CLICK has that the folder doesn't is a step: delete it in CLICK and click **Next**, or untick **Delete it in CLICK** to keep it.
- **New Subroutine** opens CLICK's New Subroutine Program window with the name filled in, and subroutines come before `main.csv`, so they exist in CLICK before main's Call instructions are pasted.
- Under **Copy: Changed rungs**, a program that would take 6 or more steps is copied whole, unless it has 100 rungs or more or CLICK holds some of its rungs in an old encoding; **Step Through** steps through it anyway.
- ClickNick warns when CLICK holds rungs an older ClickNick pasted in a form CLICK runs differently: Review Changes shows those programs in red until you paste them again, and `clicknick-rung program save` lists them.

#### Other

- CLICK v4.00 is supported: autocomplete fits its instruction dialogs, and Simulate and the workspace read its hardware and PLC name.
- Copying rungs that use CLICK v4 instructions is refused when the CLICK window is an older version, instead of letting CLICK silently change them on paste.
- ClickNick names each rung it cannot read from CLICK, such as a compare CLICK's own dialog refuses, and asks you to paste it again instead of stopping the build (the workspace holds an empty rung in its place, and **Save Clipboard to CSV** names the rung); until then the Simulator won't start, and Review Changes shows that program in red, and won't copy a folder's program while it holds such an empty rung.
- **Tools > Repairs > Upgrade Project** and `clicknick-cli tag upgrade-project` rewrite comments in pyrung's old `profile=` form into the current keys and stage them on the Changed tab for you to review and Sync; when the build stops on such a comment, the Workspace status says to run it.
- A CLICK save or `clicknick-cli backup` keeps the last 5 backups of edited workspace source, the newest in `backup/src/plc` and the others in `backup/older/<time>/src/plc` (it kept one); `clicknick-cli restore list` lists them, `restore <time>` puts one back, and `restore` first backs up edits in `src/plc` that no backup holds.

### Behaviour changes

- Guided Paste and the workspace's **Preview Changes** are now one window, **Review Changes**, showing the whole proposed ladder (Preview Changes opened one window per changed file).
  - Open it with the workspace's **Review Changes** (button or Workspace menu) or `clicknick-cli rung apply`, and any other folder with **Ladder > Compare with > Folder** (it was **Ladder > Open in Guided Paste**).
- A folder's `nicknames.csv` is no longer written straight into CLICK's database: **Stage nicknames** stages it on the Address Editor's Changed tab.
  - Review the staged rows there and click **Sync and Close**.
- The **Console** button and **Tools > Console** are now **Simulate**; the Console is a pane in the Simulator (<kbd>Ctrl</kbd>+<kbd>`</kbd> toggles it, **Pop out** gives it a window).
  - Open the Console from **Simulate**.
- The simulation keeps running after the Simulator closes.
  - Stop it with **Stop** beside the main window's Test legend.
- A CLICK save or an edit to the workspace's `src/plc` no longer reloads the running simulation, and the Console's `autoreload` is refused.
  - Answer the Simulator's offer to write the new program, or type `reload`.
- While a simulation serves Modbus, the Data View editor drops its PLC connection and connects to the simulation (its title says Simulator); when the simulation stops, it disconnects and puts back the host and port it had.
  - To reach a real PLC, stop the simulation and press **Connect**.
- A workspace's `AGENTS.md` and `README.md` are now yours; pyrung's guidance is in `AGENTS.pyrung.md` and `README.pyrung.md`, and an older generated file is moved to `*.previous.md`.
  - Copy anything you had added from the `*.previous.md` file back into yours.
- Physical responses in comments take one key per value (`flasher_on=8ms, flasher_off=8ms`, `ramp_on=`, `approach_to=`) in place of `profile=`, and the build stops on a comment in the old form.
  - Run **Tools > Repairs > Upgrade Project**, review the rewritten comments on the Changed tab, and Sync.
- `clicknick-cli tag set-physical` takes one option per key, such as `--flasher-on 8ms --flasher-off 8ms` or `--toggle`, in place of `--profile`.
  - Update scripts that pass `--profile`; `clicknick-cli help` lists the options.
- `clicknick-cli` refuses `-s`/`--session` after the command.
  - Put it first: `clicknick-cli -s <session> <command>`.
- Sync and Discard clear the undo history.
  - Undo what you need before you Sync or Discard.

### Changed

- `link=` also takes a CLICK address such as `Y001`, or `~Y001` to follow a bit while it is OFF; tag names still work.
- The annotation dialog and the Simulator's link dialog offer every pyrung response (on/off delay, flasher, timed, toggle, ramp and approach), each with its own fields, and a response no longer needs a physical name: left empty, it is named after the tag.
- The status bar names the edit Undo and Redo acted on, and a paste that changes nothing is no longer an undo step.

### Fixed

#### Autocomplete and Tag Browser

- The overlay sends nothing to CLICK when you press Esc or click away, so an empty or half-typed name no longer lands in CLICK's field; Enter on an empty overlay just closes it, Esc keeps it hidden for that field until you move to another field, and it comes back when you click into the same empty field again.
- Multi-word overlay searches list matches in list order instead of a random one, a one-letter search lists only names containing that letter, a nickname used twice is listed once with its first address, sorting by nickname ignores case, and the tooltip is read from a row of the types the field accepts.
- The overlay's tooltip and the Tag Browser show Retentive and the initial value against the address's own default: the initial value only when a timer or counter is not Retentive, Non-retentive for a non-retentive counter, and no "Initial Value = 0" on a retentive DS or TD.
- The Tag Browser's Outline shows a nickname with a double underscore (`Tank__Level`) as spelled, instead of with one underscore too many, keeps leading zeros (`Pump01_Run` stays apart from `Pump1_Run`), lists array indices in numeric order (Pump2 before Pump10), and lists a nickname used on two addresses once for each.
- In the Outline, Rename changes the segment you picked and only the nicknames under it (not an unrelated nickname that starts with the same letters), leaves comments as they are, accepts a new name that starts with a digit, and is off for SC/SD entries and `__` groups.
- Double-clicking a nickname in the Outline that has others under it (`Tank_Pump1` over `Tank_Pump1_Run`) filters the Address Editor to it and the ones under it instead of hiding its own row, and double-clicking an SC or SD entry no longer leaves a stale filter, with those groups staying open when the list refreshes.

#### Address Editor and Sync

- Undo and Redo wait while you are typing in a cell, and text still being typed is kept when you Sync, close the window, replace the data or close ClickNick; a cell that won't commit stops the close.
- Fill Down over a timer or counter selection numbers only the rows of the first row's type, and Fill Down and Clone no longer copy block tags into the new rows' comments (a row that already has its own keeps it); after a Sync, check those comments in CLICK.
- Add Block over a selection with both a timer's T and TD rows (or CT and CTD) tags matching pairs, and Remove Block keeps the rest of the comment as it was (`<Pumps> Fill` becomes `Fill`, not ` Fill`); after a Sync, check those comments in CLICK.
- Editing a timer or counter comment's text no longer deletes the block tag on its TD/CTD (or T/CT) row, renaming a block renames the matching tags in place without adding spaces or moving text (`</Tanks> last` stays `</Tanks> last`), a rename never overwrites a tag you set in the same edit, changing only a block's colour no longer adds a half block tag to an untagged TD/CTD row, and Discard row changes on a T or CT row no longer changes its TD/CTD row's Retentive.
- With **Hide Used** ticked, the right-click menu, Discard changes and the character-limit tooltip act on the column you clicked, not the one beside it.
- The Init Value and Ret cells of SC, SD, XD and YD rows are read-only instead of showing an edit that Sync never writes.
- Ctrl+W closes one tab, in either editor only its own, instead of closing two and then raising an error, and a cloned tab shows block colors, errors and unsaved edits on every row and opens at the saved scroll position.
- Undo, Discard and edits update duplicate marks, so a stale "Duplicate" no longer blocks Sync; a row stops showing as unsaved once CLICK saves its value; changes CLICK writes right after a Sync are picked up; an edit that fails partway changes nothing; and sort by nickname and block colors stay current after edits, CLICK saves, Sync and CSV loads.
- Answering Yes to "Save before closing?" with duplicate or invalid nicknames refuses and closes nothing, as Sync does, instead of writing them to CLICK.
- Sync keeps what CLICK changed in its database since ClickNick last read it: change a comment in CLICK, then rename that address in ClickNick and Sync, and CLICK keeps its new comment.
- A system nickname CLICK wrote (SC, SD, X) no longer turns into an error that blocks Sync after a CLICK save or a Sync.
- Sync counts only the rows it wrote, so an edit CLICK's database already held no longer adds to "N tags synced" and a Sync of edits CLICK already had says there was nothing to write; Save to a CSV file counts the rows you changed (it counted every row in the file).

#### Nickname CSVs

- Loading a CSV over unsaved changes asks to save or discard first, and a cancelled or failed load leaves the loaded data as it was.
- A file that is not a nickname CSV, such as one without Address and Nickname columns, CLICK's own Address.csv, or one with a row whose Address is not a CLICK address, fails to load and says why, naming the line, instead of loading as an empty project that Save then overwrites.
- Nickname CSVs load when Excel saved them as "CSV UTF-8" (they loaded empty), keep XD and YD nicknames (`XD0u`, `XD8`) on their own addresses, keep comments' leading and trailing spaces, read Retentive written as `1`/`0` or `True`/`False`, and end lines with CRLF, as CLICK's export does.
- In CSV mode, Save says so when the file cannot be written, such as while Excel holds it open, and keeps your edits, and refuses to overwrite a file that changed on disk into one ClickNick cannot read.
- A Text initial value holding `,`, `"` or a space is quoted when ClickNick writes a CSV, and ClickNick reads it back unchanged; whether CLICK's import shows it unchanged is not yet checked (import such a CSV into CLICK and look at the Text address).
- Import from CSV imports each row of a nested block once, under the innermost block, skips nicknames, comments or first-scan values when the file has no column for them instead of clearing them, and accepts a file with no Nickname column.
- Save Copy of CLICK's Address.csv keeps addresses that have only an initial value or Retentive set.
- ClickNick reloads its data when the database or CSV is replaced by an older copy, such as a restored backup.

#### Dataview Editor

- A **New Value** that is not valid for its address (such as `abc` for DS1) is refused with the reason, whether typed, pasted or filled, instead of silently keeping the earlier value that Write would send; a typed one stays in the cell for you to fix.
- Text still in a Dataview cell, such as one you typed before switching to CLICK, is saved, written or asked about when you save, export, click **Write** or **Write All**, close a tab, the Dataview Editor or the data, or CLICK opens another project (it was dropped, and Write sent the old value); closing any of them offers every unsaved dataview for saving, untitled ones too (you pick their folder), and a save that fails or is cancelled closes nothing, and a failed one says why.
- Saving a dataview that CLICK (or another program) changed after its rows were read asks whether to save over it, reload it, or do neither; a reload that replaces unsaved edits can be undone with Ctrl+Z.
- The Dataview Editor stores addresses added from the Nickname box or the Tag Browser as CLICK writes them (`X001`, `XD0u`), finds nicknames whatever their case, and refuses text that is neither a nickname nor an address. Dataviews saved by an earlier ClickNick may still hold `X1` or `XD0U`: open them in CLICK and check each row shows its address.
- Ctrl+Z and Ctrl+Y undo and redo row moves and edits without the table and the saved file disagreeing, undoing an address change keeps its New Value, and a folder or block added from the Tag Browser is one undo step.
- The Dataview Editor no longer opens a .cdv file it cannot read, so it can't save a nearly empty file over it, and it writes unchanged .cdv files back byte-for-byte.
- The Dataview Editor and **Verify** use the DataView folder of the CLICK window ClickNick is connected to (with a second CLICK window open, or a folder left by a crash, they could show, save and check another project's dataviews).
- After the CLICK window closes with a CSV loaded from its temp folder, Open and Save As start in the folder you used last (or Documents) instead of the deleted temp folder, and Save on a dataview from that folder asks where to save.

#### CLICK windows and projects

- Closing ClickNick (the window's X or **File > Exit**) asks to save unsaved Address Editor and Dataview edits, and Cancel keeps it open (it discarded them).
- When CLICK saves under a new name or opens another project while you have unsaved address or Dataview changes, ClickNick asks whether to keep them for the new project, where Sync and Save then write them, or discard them (it discarded them); nicknames loaded from a CSV stay loaded with their edits, the question then covers unsaved Dataview changes (a Save wrote them over the new project's dataviews), and a Dataview Editor without them reopens on the new project's dataviews.
- After the connected CLICK window closes, ClickNick lists the other windows and waits for you to pick one while nicknames are loaded (it connected to the first one and closed the loaded CSV), two CLICK windows with the same project name are listed with their PIDs, and the window list always shows the connected window.
- **Stop** in the main window turns off only autocomplete, until you click **Start** or pick a window, and ClickNick still notices CLICK closing or opening another project (it kept the old project's editors, simulation and database).
- ClickNick finds CLICK's project in the Windows temp folder when that is not under `C:\Users\<your name>`, such as on a renamed or domain account or with TEMP moved (it could not locate the CLICK database).
- **Load Ladder CSV to Clipboard** and Review Changes copy only for the connected CLICK window and ask you to connect first (they used the first CLICK window found).
- A broken `%LOCALAPPDATA%\ClickNick\project-sidecars.json` no longer stops ClickNick connecting to CLICK.

#### Workspace and builds

- A build that reads while CLICK is saving no longer takes CLICK's short-lived `Scr23.tmp~RF...TMP` copy for a second copy of that program, and a CLICK save is noticed when its files get an older timestamp (a copied-back project, a clock change) or when it only deletes a subroutine.
- Opening another project in the same CLICK window no longer leaves its workspace unbuilt until ClickNick restarts; Open Temporary Workspace and the Workspace status update as soon as a build finishes; program analysis and AI tag lookups use the same nicknames as the generated code; and switching CLICK projects no longer freezes the window.
- "N tags synced - Save in CLICK" counts each tag once and no longer drops to 0 when the workspace rebuilds, such as after a Sync with repairs or setting up a workspace.
- A build that cannot finish writing the workspace, such as when a file in it is open in Excel, still fails but leaves `csv/` and `src/plc` both from the save before.
- A workspace `AGENTS.md` or `README.md` that is not UTF-8, such as one Notepad saved as ANSI, no longer makes every build fail.
- A workspace `pyproject.toml` ClickNick cannot read no longer makes a finished build report failure; Check Program reports it.
- **Export Workspace**, Workspace setup and Review Changes after a failed build say why instead of using the workspace of an earlier save.
- Choosing an existing workspace whose `src/plc` holds edits copies them to `backup/src/plc` before the next build regenerates it, and shows it as edited instead of Clean (`clicknick-cli restore` puts them back); Workspace setup no longer switches when both the current and the chosen workspace's `src/plc` hold edits, and names both folders so you can paste or discard one first.
- Choosing a workspace while ClickNick regenerates it is refused with a note to try again, as `clicknick-cli backup` and `restore` are; a backup or switch made then could hold files from two saves.

#### clicknick-cli and clicknick-rung

- `clicknick-cli` passes each argument as you typed it, so a value can hold quotes, backslashes or `;`, such as `set DS1 comment "Don't start"` (a command given as one argument is split at spaces and at `;` outside quotes), and accepts options as separate words (`rung apply main --select r3`, `tag set-physical ... --on-delay 50ms`) instead of refusing them.
- `clicknick-cli tag apply` keeps a comment's text and block tag and changes only the annotations you changed in `tags.py` (it replaced the comment with them alone, such as `[uom=mm]`), and no longer stages `[external]` on analog input channels you did not edit. Comments that an earlier `tag apply` cut down to their annotations keep only the annotations in CLICK: put their text back by hand.
- `clicknick-cli get`/`set` find tags by the names in the workspace, also when the analysis of a CLICK save failed.
- `clicknick-cli prompt-save` answers at once while ClickNick shows the reminder, instead of holding every other command until the dialog is closed.
- `clicknick-rung load` on a ladder CSV with no rungs says so instead of crashing.

## v0.23.4 - 2026-10-11

### Fixed

- Generated workspaces remain openable, editable, and exportable when program analysis fails, while the Console reports simulation startup failures with Retry and optional diagnostic details.
- The nickname overlay's dropdown stays open when its arrow is clicked, and typing no longer raises a Tcl error, on newer Python and Tk 9 installs.
- Updated pyrung to 0.15.2 so the Console's PLC Data loads a CLICK data dump instead of failing with "no TagMap found in project", seeds plain nicknamed addresses, and rejects a file that is not a data dump; the Browse tooltip and help now say where the dump comes from.

## v0.23.3 - 2026-09-10

### Fixed

- Updated laddercodec to 0.2.2 so program imports preserve branch wiring above later rail-connected rows and parse valid populated SCR special rows without recovery.

## v0.23.2 - 2026-09-10

### Fixed

- Updated pyrung to 0.15.1 so imported CLICK CSV expressions are validated and imported names and text remain data in generated Python.
- Release trust reports use the security page as their source for behavioral disclosures.
- Build dependencies are pinned and fresh checkouts use LF line endings to support reproducible wheels.
- The security page distinguishes intentional workspace execution from imported project data and explains the PowerShell backend choice.

## v0.23.1 - 2026-09-09

### Fixed

- Fixed the missing trust report and dependency inventory downloads from 0.23.0; publishing a GitHub release now uploads the reports and refreshes the security docs automatically.

## v0.23.0 - 2026-09-09

### Features

- Releases include a trust report and CycloneDX dependency inventory with package hashes, licenses, documented purposes, source checks, and vulnerability results.

- Live database features can use Windows Jet through built-in 32-bit PowerShell when the Access ODBC driver is unavailable, with a read-only Test Connection action in Help > About ClickNick and `--db-backend jet|odbc|auto|none` to test a specific backend.

- Check Program and generated workspaces recognize analog inputs assigned in Project.ini, including built-in channels, CPU slots, and expansion modules; sampled copies no longer appear constant just because their hardware source starts at zero.

### Changed

- Runtime dependencies are pinned exactly, including pyclickplc 0.4.0, pyrung 0.15.0, tomlkit 0.15.1, and tksheet 7.6.0.

- Choose Checks saves app-wide preferences for programs without a workspace, seeds workspace check settings once, and automatically saves subsequent workspace changes to its `pyproject.toml`.

- Maintenance actions now live together under Tools > Repairs, system nickname repair no longer occupies the main window while unavailable, and the obsolete `clicknick-dev` launcher has been removed.

### Fixed

- Verify MDB & CDV now accepts ordinary X-address nicknames while continuing to validate CLICK-generated `_IO` system names.

## v0.22.1 — 2026-09-04

### Changed

- README, docs site, and package metadata point at pyrung.com/clicknick; CONTRIBUTING and issue templates added.

## v0.22.0 — 2026-09-03

### Features

- Dots in nickname autocomplete mean underscores: typing or pasting `Alm1.id` reaches `Alm1_id`, and `x.Temperature` commits as `x_Temperature`. Numeric literals such as `1.5` and quoted string literals keep their period.

## v0.21.0 — 2026-09-02

### Features

- **System nickname repair** — when analysis encounters documented CLICK SC/SD system-name problems, ClickNick offers a reviewable AddressStore repair in the GUI and through `clicknick-cli tag repair-system-nicknames`, then retries analysis after Sync.

### Fixed

- SC and SD system nicknames accept CLICK's leading-underscore naming convention while other protected address-name validation remains enforced.

## v0.20.0 — 2026-09-02

### Features

- **Persistent PLC workspaces** — create or select a durable workspace named for the PLC, keep tests, notes, and tooling across generated-program refreshes, preview edited ladder source before copying it back to CLICK, and safely reload from CLICK with a recovery snapshot of replaced source.
- **Check Program** — run pyrung's static ladder checks from Tools > Check Program or against the editable workspace with `clicknick-cli check`, inspect compiler-style diagnostics with source context and fix hints, and copy the complete report for sharing.
- **Interactive pyrung Console** — simulate the saved CLICK program with slot-aware autocomplete, live `how()` progress, CSV snapshot seeding, and automatic reloads when workspace source changes; long-running commands can be stopped without losing forces or scan position, and output can be copied directly.
- **Reviewed ladder changes** — `clicknick-cli rung apply` stages workspace edits and opens Preview Changes with semantic rung diffs, per-group Copy to CLICK actions, and repeatable whole-program copying through Guided Paste.
- **Agent CLI (`clicknick-cli`)** — inspect project status and work with tags and rungs through `info`, `tag`, and `rung` commands, apply `tags.py` edits as one staged Address Editor change, find unused addresses from one or more hints, and recover generated source with explicit backup and restore commands.
- **Program analysis filters** — the Address Editor filter box accepts `input:`, `output:`, `pivot:`, `isolated:`, `upstream:Tag`, and `downstream:Tag` prefixes, which compose with existing text filters.
- **Right-click annotation editor** — comment-field annotations (flags, choices, min/max, unit of measure, physical/link) can be edited in a structured dialog with hover tooltips instead of hand-typed bracket syntax.
- **Add Block dialog** gained an Advanced section for `:block`, `:named_array`, and `:udt` structured block kinds, with live preview and row-count display.

### Fixed

- Persistent workspaces now receive matching generated lifecycle guidance, while temporary workspaces keep their closing warning and user-authored documentation remains untouched.
- Nicknames stay synchronized across CLICK, autocomplete, and the Address Editor when edits arrive before the editor opens, after unrelated comment changes, or following a locked or failed project-database read.
- Preview Changes now compares canonical CLICK rungs, renders complete multiline source, attributes edits to the correct rung, treats displaced rungs as neutral renumbering, and copies subroutines correctly.
- Copy to CLICK now provisions every referenced address, including otherwise-unmaterialized block-copy endpoints, and the preview reliably opens focused with all Guided Paste controls visible.
- Check Program and Console now distinguish projects that are still converting, failed conversion, missing saved ladder files, and genuine launch failures, with useful progress, error details, timeouts, and retry actions instead of hanging or reporting a misleading connection error.
- Console autocomplete now follows pyrung's published command grammar, completes multi-target `how` and `avoid`/`via` clauses, handles `~`-prefixed tags, respects the selected Filter Mode, and keeps the input cursor and dropdown stable.
- Console sessions now recover when the simulation backend exits mid-command, remain independent across concurrent ClickNick instances, and stop correctly while paused at a breakpoint.
- Nickname CSV imports no longer crash, now exclude unchecked blocks, keep options separate for repeated block names, and treat blank numeric initial values like CLICK's default `0` without changing TXT semantics.
- Address rows no longer remain marked **Changed** after an unchanged value is written or an edit is returned to its original value, avoiding unnecessary database writes on save.
- Analysis-project rebuilds preserve the workspace virtual environment and lockfile without leaving stale generated files behind, and reconnecting or switching projects cleans up watchers, Modbus connections, and simulator processes.
- Copy controls and status bars remain visible at their default window sizes and use consistent plain-text labels across Console, Check Program, Preview Changes, and Guided Paste.

### Changed

- The import dialog's **Init Val** and **Retentive** columns are now a single **First Scan** column: the two are imported together, so importing a retentive setting can no longer silently shadow an initial value the program relies on.
- The main window now groups its primary actions around editing, testing, and workspace management, with dedicated action icons, menu-based settings, and an Open Temporary Workspace action before durable setup.
- About ClickNick now summarizes the editing, checking, simulation, and workspace tools, reports the installed pyrung version, and copies complete support diagnostics reliably.

## v0.19.3 — 2026-04-21

### Fixed

- Inserting rows in the Dataview Editor (including multi-row pastes) keeps the underlying data in sync with what is shown, so rows no longer land at the wrong index.

## v0.19.2 — 2026-04-21

### Fixed

- Deleting rows in the Dataview Editor keeps the underlying data in sync with what is shown, so deletes no longer leave orphaned data behind.

## v0.19.1 — 2026-04-14

### Features

- Loading a decoded `.bin` rung payload provisions any missing addresses into the project MDB, as CSV loads already did, and reports how many were inserted.

### Fixed

- Nickname edits in the Address Editor immediately refresh autocomplete and the Dataview Editor instead of leaving stale values behind.

## v0.19.0 — 2026-04-02

### Features

- **Ladder rung import/export** — a new `clicknick-rung` CLI loads and saves rungs via the clipboard and decodes a whole program to CSV, alongside a beta Ladder menu and a step-through Guided Paste panel for pasting a folder of ladder CSVs into Click with nickname import.

### Changed

- The Dataview Editor can reconnect to the PLC and uses more forgiving timeout defaults.

## v0.18.0 — 2026-02-27

### Changed
- Restored local ownership of `export_cdv`, `get_dataview_folder`, and `list_cdv_files` in `clicknick.views.dataview_editor.cdv_file`.
- Added canonical `read_mdb_csv()` in `clicknick.data.data_source` returning `dict[int, AddressRow]`.

### Compatibility
- Kept `load_addresses_from_mdb_dump()` as a backward-compatible alias to `read_mdb_csv()`.
