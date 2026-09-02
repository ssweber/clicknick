# Keep the useful engineering stuff with the machine

**Tour 5 of 6**

A PLC project rarely lives alone. The useful record includes startup notes, test cases, known-good tag states, fault reproductions, and the explanation somebody will need during the next shutdown. Usually it's scattered across a Downloads folder and one person's memory.

A persistent workspace gives all of it one home, next to the program:

![A CLICK project connected by PLC name to its workspace folder: ClickNick refreshes the ladder text, CLICK snapshot, and nicknames; your tests, notes, and fixtures stay](../assets/clicknick-workspace.svg)

ClickNick owns the generated part — the ladder as text, the accepted CLICK snapshot, nickname data — and refreshes it on every save. Everything you add around it stays.

The workspace carries the CLICK PLC name, so reopening that project reconnects to the same folder instead of starting another temporary one. Put it under source control if you want reviewed history and off-machine backups. It's useful without.

---

[Next: AI in the workspace →](ai-in-the-workspace.md)
