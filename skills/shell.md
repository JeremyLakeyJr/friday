# Skill: Shell & Files

Use these tools to run commands and manage files on the host machine.

## run_bash(command, timeout?, working_dir?)
Execute any bash command. Returns exit_code, cwd, stdout, stderr.
- `timeout` defaults to 30s. Increase for long operations.
- `working_dir` defaults to home directory.

**When to use:** Install packages, run scripts, git ops, system config, inspect processes, anything CLI.

Examples:
```
run_bash("ls -la ~/projects")
run_bash("git status", working_dir="/home/user/myapp")
run_bash("pip install requests", timeout=60)
run_bash("python script.py && echo done")
```

Always check `exit_code` in the result — 0 = success, non-zero = error. Read `stderr` for error details.

---

## read_file(path)
Read a file from the local filesystem. Returns full text content.
Supports `~` expansion.

Examples:
```
read_file("~/.bashrc")
read_file("/etc/hosts")
read_file("/home/user/project/main.py")
```

---

## write_file(path, content)
Create or overwrite a file with the given content. Creates parent directories automatically.

Examples:
```
write_file("/tmp/hello.py", "print('hello')")
write_file("~/notes.txt", "Remember to update deps")
```
