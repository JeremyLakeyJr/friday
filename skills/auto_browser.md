# Skill: Auto Browser (Persistent Sessions)

A persistent, multi-session headless browser backed by the auto-browser Docker service running at `http://127.0.0.1:8000`.

Unlike `browser_*` tools (per-chat Playwright), auto-browser sessions are **named and persistent** — they survive across messages and support multiple concurrent windows.

## auto_browser_create_session(name, start_url?)
Open a new session. Returns a `session_id` used in all other calls.

```
auto_browser_create_session("research", "https://google.com")
auto_browser_create_session("login-session")
```

---

## auto_browser_observe(session_id)
Get current state: URL, title, DOM summary. Call after every navigation or click to understand the page.

---

## auto_browser_navigate(session_id, url)
Navigate to a URL.

```
auto_browser_navigate("abc123", "https://github.com")
```

---

## auto_browser_click(session_id, selector)
Click an element by CSS selector.

```
auto_browser_click("abc123", "button[type=submit]")
```

---

## auto_browser_type(session_id, selector, text)
Type into an input field.

```
auto_browser_type("abc123", "#search", "query here")
```

---

## auto_browser_scroll(session_id, delta_x?, delta_y?)
Scroll the page. Default: 300px down.

---

## auto_browser_screenshot(session_id)
Take a screenshot. Show it to the user.

---

## auto_browser_close_session(session_id)
Close a session when done.

---

## auto_browser_list_sessions()
List all active sessions.

---

## auto_browser_call_mcp_tool(tool_name, arguments_json?)
Call a native MCP tool on the auto-browser service directly.

---

## Typical workflow
1. `auto_browser_create_session("task", url)` → get `session_id`
2. `auto_browser_observe(session_id)` → see what loaded
3. Interact: click / type / scroll
4. `auto_browser_observe` again → confirm
5. `auto_browser_screenshot` → show user
6. `auto_browser_close_session` → clean up

Sessions persist between messages — create once, reuse across the conversation.
