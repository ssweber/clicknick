def sub(p, old, new):
    s=open(p,encoding="utf-8",newline="").read()
    assert old in s,(p,old)
    open(p,"w",encoding="utf-8",newline="").write(s.replace(old,new,1))
a="src/clicknick/data/address_store.py"
sub(a,'''        flagged = not is_valid
    if row.loaded_with_error''','''        flagged = not is_valid
    if flagged and cp1252_problems([row]):
        # A character that CLICK cannot hold is an error to fix, never one to hide
        flagged = False
    if row.loaded_with_error''')
sub(a,"    TRIMMED_FIELDS,\n","    TRIMMED_FIELDS,\n    cp1252_error,\n    cp1252_problems,\n")
sub(a,'''            if self.is_duplicate_nickname(row.nickname, addr_key):
                nickname_valid, nickname_error = False, "Duplicate"''','''            if error := cp1252_error(row.nickname):
                nickname_valid, nickname_error = False, error
            elif self.is_duplicate_nickname(row.nickname, addr_key):
                nickname_valid, nickname_error = False, "Duplicate"''')
d="src/clicknick/views/dialogs.py"
sub(d,'''            except Exception as e:
                # Show error message
                tk.messagebox.showerror(
                    "Save Address CSV Copy",
                    f"Could not save the copy to {dest_path}:\n{e}\n\n"
                    "If the message names a character, change it in CLICK, save, and try again.",
                    parent=self.window,
                )''','''            except ValueError as e:  # A character that CLICK cannot hold
                tk.messagebox.showerror(
                    "Save Address CSV Copy",
                    f"Could not save the copy to {dest_path}:\n{e}\n\n"
                    "Change it in CLICK, save, and try again.",
                    parent=self.window,
                )
            except Exception as e:
                tk.messagebox.showerror(
                    "Save Address CSV Copy",
                    f"Could not save the copy to {dest_path}:\n{e}",
                    parent=self.window,
                )''')
