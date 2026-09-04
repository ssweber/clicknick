# Run your CLICK program without the PLC

**Tour 3 of 6**

The rung isn't firing and the machine is two hours away. Load a tag snapshot from the PLC into the Console and step the saved ladder from exactly that state, on your laptop.

![ClickNick Console showing simplified, why, and how queries](https://github.com/user-attachments/assets/1727f54b-7f5d-4181-923e-4fbf7628d2a6)

The Console runs the saved program on your computer, using pyrung's model of the CLICK scan cycle. Start with `why`: it traces what's holding a tag on, off, or blocked, which is usually the first troubleshooting question anyway.

Force inputs to set up a condition, advance scan by scan, inspect tags or fill a Data View. Nothing you do here touches the machine.

`how` is the experimental one. It searches for a way to reach a state you name. When it finds one, you get a recording you can replay. On real programs it sometimes stops without one, and it can take a minute.

This is a model of the program, not the PLC. It doesn't know about wiring, sensor timing, or network behavior, and analog values are whatever you feed it. What it tells you about the ladder is real. Confirm it on the machine.

---

**[Next: Still saving `Machine_FINAL_FINAL.ckp`? →](readable-history.md)**
