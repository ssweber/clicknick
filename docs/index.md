# Better tools for AutomationDirect CLICK PLCs

CLICK Programming Software has no simulator, so ClickNick adds one: run your saved program without the PLC.

Also nickname autocomplete, program checks, and your ladder (as Python) after every save.

**CLICK stays CLICK. ClickNick gives you better tools around it.**

[Take the tour](tour/autocomplete.md){ .md-button .md-button--primary } [Install ClickNick](install.md){ .md-button }

> **ClickNick never edits your `.ckp`.** Nothing becomes part of the project until you save in CLICK Programming Software. [Where ClickNick writes.](help/index.md#where-clicknick-writes)

> **Not official, not affiliated.** ClickNick is an independent project, not endorsed by AutomationDirect. The simulator and checks don't replace testing. Test on the real machine, with proper safeguards, before anything interacts with people.

![ClickNick connected to a CLICK project](https://github.com/user-attachments/assets/de4148a2-cbc5-4b11-95e5-f884c59d70e0)

## Why

CLICK is inexpensive, approachable, and easy to troubleshoot. That simplicity is a feature. What's missing is around the editor: you type `C123` because you can't type nicknames, nothing checks the program before the machine runs it, there's no simulator to try it on, and last month's logic lives in `Machine_FINAL_FINAL.ckp`. ClickNick fixes those without replacing CLICK Programming Software.

## Who it's for

Anyone who programs CLICK PLCs, from the one-person shop to the integrator with fifty projects on the shelf. You don't need Git, Python, or an AI to get something out of it: start with autocomplete, open the Address Editor when it helps, run Check Program when you want another set of eyes. If you do want tests and history for a machine, they're one workspace away.

Built on [pyrung](https://pyrung.com/pyrung/), the engine that runs your ladder as Python. [How it fits.](https://pyrung.com/overview/)

## Get started

Two steps: install `uv`, then `uv tool install clicknick`. [Install](install.md) · [Take the tour](tour/autocomplete.md)
