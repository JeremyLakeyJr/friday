# Skill: Persistent Memory (SQLite + FTS)

Memory survives across sessions. Relevant entries are injected at the end of every prompt automatically.

## Importance levels
| Level | Meaning |
|-------|---------|
| 5 | Pinned — always shown in every prompt (user's name, core prefs) |
| 3 | Normal — shown only when FTS-relevant to the current message |
| 1 | Archived — never auto-shown, but searchable |

---

## add_memory(content, category, importance)
Save a new fact. Call this silently whenever you learn something useful — never ask permission.

Categories: `user_profile`, `brain`, `project`, or any custom label.

```
add_memory("User's name is Jeremy", "user_profile", 5)
add_memory("Prefers Python over JavaScript", "user_profile", 3)
add_memory("Working on a home automation project with MQTT", "project", 3)
add_memory("DuckDuckGo API changed in 2024 — use DDGS().text()", "brain", 3)
```

---

## update_memory(key, content, category, importance)
Upsert by named key — use to correct or replace a specific fact.

```
update_memory("user_name", "User's name is Jeremy Lakey", "user_profile", 5)
update_memory("user_os", "Runs Arch Linux", "user_profile", 3)
```

---

## search_memory(query)
Full-text search across ALL stored memories (including archived ones not auto-injected).
Use when you need older context that isn't in the current prompt.

```
search_memory("docker project")
search_memory("user email")
```

---

## list_memories(category)
Browse all memories, optionally filtered by category. Pass `""` to list all.

```
list_memories("user_profile")
list_memories("")
```

---

## forget_memory(identifier)
Delete a memory by its key name or numeric id.

```
forget_memory("user_name")
forget_memory("42")
```

---

## Rules
1. User's name, preferences, tech setup → `add_memory` immediately, importance 4-5
2. Project details, facts worth keeping → importance 3
3. To fix wrong info → `update_memory` with the same key
4. Old context not visible → `search_memory`
5. Never ask the user before saving — just do it quietly
