# todo.md

## For each TODO:

1. Clarify if needed
2. Implement + add tests if helpful
3. Ask user to test

### Todo

#### Edit copy

Read Readme.md. Also read our _show_dataview_editor_popup in views/dataview_editor/window.py and _show_address_editor_popup in views/address_editor/window.py


Here is some clarifications I made to an user the other day, is any of it helpful to update our Readme and popups? Should we add a helpful tip for the Fill down, or Clone?


```
To summarize the key takeaways from our conversation:

    Compatibility: ClickNick works with existing .ckp projects. It reads the temporary data files the Click software generates when you open a project, so you don't need to create new projects to use it.
    Safety & Non-Destructive Use:
        The Outline view is purely a visual aid. It builds a tree by splitting nicknames at underscores to help you see structure, but it doesn't store anything and doesn't change your tags.
        The Nickname Autocomplete in the ladder editor is read-only.
        Any edits made in the Address Editor are sent to the Click software, but you still must click "Save" in Click to commit them to your project file. ClickNick itself doesn't modify your .ckp file.
    "Blocks" for Organization: The colored Blocks you can create (like <Machine1> ... </Machine1> are simply stored in the "Comment" column of your address table. They're a powerful way to visually group sections in the Block Navigator without touching your logic.
    Performance: I've used it on larger projects without issue, but I'm always interested in feedback if anyone experiences otherwise.
    Privacy & Installation: The app is entirely local (no internet calls), has no telemetry, and uses only mainstream, minimal Python dependencies. It's just a tool that sits on top of your Click software.

 

I hope that clears things up! If anyone tries it with an existing project, I'd love to hear what worked, what was surprising, or what you couldn't figure out. That feedback is incredibly helpful.

 

P.S. For your IT department: It's a lightweight, local Python script with no external services or data collection. The GitHub repo has the full code to audit.