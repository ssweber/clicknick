# Check your ladder before the machine does

**Tour 2 of 6**

"Why isn't this working?"

```text
|--[ Mode < 1 ]--[ Mode > 3 ]--------( InvalidMode )--|
```

That's an AND. Mode can't be below 1 and above 3 at the same time, so `InvalidMode` never turns on. It was meant to be an OR. CLICK's syntax check is fine with it, because it compiles. Check Program flags it: this rung can never be true.

![ClickNick Check Program report](https://github.com/user-attachments/assets/38cb2f44-482a-4e60-9f56-4da95074a971)

ClickNick reads the last saved ladder and checks it for logic problems. Each finding has a severity, the rung it points at, and a fix hint where there is one. The findings are the mistakes you make once or twice a year when you program a new CLICK project, then spend an hour finding:

- an AND drawn where you meant an OR, so the rung can never be true;
- `Setpoint > Timer_Acc` when you meant `Timer_Acc > Setpoint`;
- a bit that gets latched and never reset, or reset and never latched;
- a subroutine nothing calls.

A finding is a reason to look at the rung. The checker doesn't know your process; you do. It makes suspicious logic easy to see before commissioning finds it the hard way. If a rule is too noisy on your programs, [say so](https://github.com/ssweber/clicknick/issues); that's how the rules get tuned.

---

**[Next: Run the CLICK program without the PLC →](offline-console.md)**
