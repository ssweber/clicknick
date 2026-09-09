# Curious about AI? Give it a workspace you can check.

**Tour 6 of 6**

AI is optional. If you use a coding agent, point it at the workspace, not the `.ckp`.

<div class="agent-flow" role="group" aria-labelledby="agent-flow-title">
  <p class="agent-flow__head"><strong id="agent-flow-title">What the agent works with</strong> The same workspace you have. Nothing it runs touches the PLC.</p>
  <ol class="agent-flow__steps">
    <li class="agent-flow__step agent-flow__step--reads">
      <strong>Reads the workspace</strong>
      <dl class="workspace__rows">
        <dt>src/plc/</dt><dd>the ladder as text</dd>
        <dt>tests/ · notes/</dt><dd>what you know about the machine</dd>
      </dl>
      <p>The ladder text refreshes on every CLICK save.</p>
    </li>
    <li class="agent-flow__step agent-flow__step--model">
      <strong>Works in the offline model</strong>
      <dl class="workspace__rows">
        <dt>why · how · step · force</dt><dd>trace, search, and step the scan</dd>
        <dt>pytest · check</dt><dd>the same tests and checks you run</dd>
      </dl>
      <p>pyrung's model of the scan. No connection to the PLC.</p>
    </li>
    <li class="agent-flow__step agent-flow__step--proposes">
      <strong>Proposes files</strong>
      <span>Edits to the ladder text, new tests, comments. All of it sits in the workspace for you to read.</span>
      <p>Preview Changes shows the rung diff.</p>
    </li>
    <li class="agent-flow__step agent-flow__step--accept">
      <strong>You accept</strong>
      <span>Select the rungs you want. Guided Paste puts them into CLICK.</span>
      <p>Nothing changes until you save in CLICK.</p>
    </li>
  </ol>
</div>

The agent gets the same program, the same tests, and the same command-line checks you have. Start with work that's easy to inspect:

1. Explain a rung or trace a tag.
2. Suggest clearer comments and nicknames.
3. Write a test that pins down existing behavior.
4. Review a proposed change and run the checks.
5. Then, if it has earned it, propose ladder changes.

Everything it runs is the same offline model. It has no connection to the PLC, and its ladder changes come back the way yours do: Preview Changes, your selection, then Guided Paste through CLICK.

[Install ClickNick](../install.md){ .md-button .md-button--primary } [Help](../help/index.md){ .md-button } [GitHub](https://github.com/ssweber/clicknick){ .md-button }

> **ClickNick never edits your `.ckp`.** Nothing becomes part of the project until you save in CLICK Programming Software. [Where ClickNick writes.](../help/index.md#where-clicknick-writes)
