# Check your ladder before the machine does

**Tour 2 of 6**

**Program checks? For CLICK? Yep.**

![ClickNick Check Program report](https://github.com/user-attachments/assets/38cb2f44-482a-4e60-9f56-4da95074a971)

ClickNick converts the saved ladder into readable pyrung source and runs static checks against it. Each finding has a severity, the source it points at, and a fix hint where there is one.

The findings are controls problems, not style complaints:

- a rung whose conditions contradict each other and can never be true;
- a comparison that is already true at its reset value and pulses on every restart;
- a state-machine step that waits for outside feedback and has no way out on its own.

A finding is a reason to look at the rung. The checker doesn't know your process; you do. It makes suspicious logic easy to see before commissioning finds it the hard way.

Save in CLICK before running Check Program.

---

[Next: Run the CLICK program without the PLC →](offline-console.md)
