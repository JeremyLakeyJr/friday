# Skill: Desktop System Access

Full access to the user's desktop and filesystem. Use these tools to manage files, processes, take screenshots, and control applications.

## list_processes(filter?)
List running processes (like `ps aux`). Optional filter by name.

```
list_processes()               # all processes
list_processes("firefox")      # just Firefox processes
list_processes("python")       # Python processes
```

---

## kill_process(pid_or_name, signal?)
Kill a process by PID number or name. signal: TERM (default/graceful) | KILL (force)

```
kill_process("1234")           # kill by PID
kill_process("firefox")        # kill all Firefox
kill_process("1234", "KILL")   # force kill
```

---

## list_directory(path?, show_hidden?)
List files in a directory with sizes and types.

```
list_directory("~")
list_directory("~/Documents")
list_directory("~", show_hidden=True)
```

---

## move_file(source, destination)
Move or rename a file or directory.

---

## copy_file(source, destination)
Copy a file or directory.

---

## delete_file(path, recursive?)
Delete a file or directory. `recursive=True` for non-empty directories.

---

## create_directory(path)
Create a directory (and parents) if it doesn't exist.

---

## search_files(pattern, directory?, max_results?)
Search for files matching a glob pattern.

```
search_files("*.py", "~/Documents")
search_files("README*", "~")
```

---

## get_disk_usage(path?)
Get disk usage stats (total / used / free).

---

## get_memory_usage()
Get current RAM and swap usage.

---

## take_screenshot(save_path?)
Take a screenshot of the entire desktop. Returns base64 PNG or saves to a file.

```
take_screenshot()                  # return as base64
take_screenshot("~/screen.png")   # save to disk
```

---

## open_application(name_or_path, args?)
Launch a desktop application.

```
open_application("firefox")
open_application("gedit", "~/notes.txt")
open_application("nautilus", "~/Documents")
```

---

## open_file_with_app(path)
Open a file with its default application (xdg-open).

```
open_file_with_app("~/report.pdf")
open_file_with_app("~/photo.jpg")
```

---

## get_clipboard() / set_clipboard(text)
Read or write the clipboard (requires xclip or xsel).

---

## send_desktop_notification(title, message, urgency?)
Send a desktop notification popup. urgency: low | normal | critical
