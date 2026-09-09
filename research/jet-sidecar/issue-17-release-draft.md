Publish when the release containing the Jet fallback is available.

Title: Database connection help

---

ClickNick normally connects without a separate database driver on Windows x64. It uses an installed Access ODBC driver when available, or Windows' built-in Jet engine.

Update ClickNick:

```powershell
uv tool upgrade clicknick
```

If connecting fails:

1. Open your project in CLICK and save it.
2. In ClickNick, open **Help > About ClickNick > Test Connection**.
3. Use **Copy System Info** and include the result when reporting the problem.

"MS Access ODBC: Not installed" is fine if Jet connects successfully. On managed computers, PowerShell restrictions may prevent that connection.

See [connection help](https://pyrung.com/clicknick/help/#database-connection) for troubleshooting, backend selection, and CSV mode.
