---
id: auto-browser
name: Auto Browser (Persistent Sessions)
version: 1.0.0
description: Full headless Chromium browser with persistent named sessions via the auto-browser service. Supports navigation, clicking, typing, scrolling, and screenshots across multiple independent sessions.
capabilities:
  - browser
  - web-automation
  - screenshots
min_server_version: 0.2.0
---

# Auto Browser

A persistent, multi-session headless browser backed by the auto-browser service. Unlike the built-in `browser_*` tools (which are per-chat), auto-browser sessions are named, shareable, and survive across conversations.

Use `auto_browser_*` when you need:
- A persistent session (e.g. stay logged in across messages)
- Multiple browser windows open at once
- Full visual control via noVNC at `http://127.0.0.1:6080`

---

## auto_browser_list_sessions()
List all active sessions and their IDs.

```
auto_browser_list_sessions()
```

---

## auto_browser_create_session(name, start_url?)
Open a new browser session with a given name. Returns the `session_id` needed for all other calls.

```
auto_browser_create_session("research", "https://google.com")
auto_browser_create_session("login-session")
```

---

## auto_browser_observe(session_id)
Get the current state of a session: URL, page title, DOM summary, and screenshot URL.
**Always call this after navigation or interaction to understand what the page looks like.**

```
auto_browser_observe("abc123")
```

---

## auto_browser_navigate(session_id, url)
Navigate the session to a URL. Wait for it to settle, then call `observe`.

```
auto_browser_navigate("abc123", "https://github.com")
```

---

## auto_browser_click(session_id, selector)
Click an element by CSS selector.

```
auto_browser_click("abc123", "button[type=submit]")
auto_browser_click("abc123", ".accept-cookies")
auto_browser_click("abc123", "a[href='/login']")
```

---

## auto_browser_type(session_id, selector, text)
Type text into an input field.

```
auto_browser_type("abc123", "#search", "OpenAI news")
auto_browser_type("abc123", "input[name=email]", "user@example.com")
```

---

## auto_browser_scroll(session_id, delta_x?, delta_y?)
Scroll the page. Default scrolls down 300px.

```
auto_browser_scroll("abc123")                        # scroll down
auto_browser_scroll("abc123", delta_y=600)           # scroll down more
auto_browser_scroll("abc123", delta_y=-300)          # scroll up
```

---

## auto_browser_screenshot(session_id)
Capture a screenshot of the current browser state. Returns image data you can show the user.

```
auto_browser_screenshot("abc123")
```

---

## auto_browser_close_session(session_id)
Close and clean up a session when done.

```
auto_browser_close_session("abc123")
```

---

## auto_browser_call_mcp_tool(tool_name, arguments_json?)
Call any of the auto-browser service's native MCP tools directly by name.

```
auto_browser_call_mcp_tool("browser_snapshot", "{}")
auto_browser_call_mcp_tool("browser_navigate", "{\"url\": \"https://example.com\"}")
```

---

## Typical workflow

1. `auto_browser_create_session("task", "https://example.com")` — open a session
2. `auto_browser_observe(session_id)` — see what loaded
3. `auto_browser_click` / `auto_browser_type` — interact
4. `auto_browser_observe(session_id)` again — confirm the result
5. `auto_browser_screenshot(session_id)` — show the user
6. `auto_browser_close_session(session_id)` — clean up when done

**Tip:** Sessions persist between messages. You can create a session in one message and continue using it in the next.
