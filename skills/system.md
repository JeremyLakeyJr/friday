# Skill: System & Utilities

## get_system_info()
Returns OS name, CPU model, RAM, disk usage, hostname, and uptime.
Use when the user asks about the machine, or before running system-specific commands.

---

## get_current_time()
Returns current date and time in ISO 8601 format.

---

## format_json(data)
Pretty-print a JSON string. Use before displaying JSON data to the user.

```
format_json('{"name":"Friday","version":"1.0"}')
```

---

## word_count(text)
Count words, characters, and lines in a block of text.
