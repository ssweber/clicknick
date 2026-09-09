# Keep the engineering work with the CLICK project

**Tour 5 of 6**

A workspace is a folder that links up with your open project. ClickNick fills it with your ladder (as Python) after every save. Everything else in it is yours: startup notes, test cases, known-good tag states, fault reproductions, the explanation somebody will need during the next shutdown. Today that's scattered across a Downloads folder and one person's memory.

<div class="workspace" role="group" aria-label="What lives in a workspace folder">
  <p class="workspace__head"><code>CasePacker.ckp</code> <span class="workspace__link">linked by PLC name to</span> <code>CasePacker Workspace/</code></p>
  <div class="workspace__cols">
    <div class="workspace__col workspace__col--managed">
      <strong class="workspace__title">ClickNick refreshes</strong>
      <dl class="workspace__rows">
        <dt>src/plc/</dt><dd>the ladder as text</dd>
        <dt>csv/</dt><dd>the snapshot CLICK accepted</dd>
        <dt>nicknames.csv</dt><dd>addresses and nicknames</dd>
      </dl>
      <p>Edit it and Preview Changes shows the diff.</p>
    </div>
    <div class="workspace__col workspace__col--yours">
      <strong class="workspace__title">Yours stays</strong>
      <dl class="workspace__rows">
        <dt>tests/</dt><dd>machine behavior, pinned</dd>
        <dt>notes/</dt><dd>startup notes, the why</dd>
        <dt>fixtures/</dt><dd>known-good tag states</dd>
      </dl>
      <p>A smoke test and README are seeded once, then left alone.</p>
    </div>
  </div>
  <p class="workspace__foot">Add anything else you want kept with the machine. It survives every refresh.</p>
</div>

The folder carries the CLICK PLC name, so reopening that project reconnects to the same folder. Put it under Git if you want reviewed history and off-machine backups. It's useful either way.

---

**[Next: AI in the workspace →](ai-in-the-workspace.md)**
