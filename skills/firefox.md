# Skill: Firefox Browser (Playwright)

AI-controlled Firefox browser with a visible window — the user can watch what you're doing in real time.
Use for tasks that need Firefox specifically, or when you want the user to see the AI browsing.

## firefox_navigate(url)
Open a URL in the AI-controlled Firefox window. Returns page title + HTTP status.

```
firefox_navigate("https://github.com")
firefox_navigate("https://youtube.com")
```

---

## firefox_open_in_system(url)
Open a URL in the user's **real running Firefox** (not the AI instance).
Use this when the user asks to "open in Firefox" or wants to browse themselves.

```
firefox_open_in_system("https://reddit.com")
```

---

## firefox_screenshot()
Take a screenshot of the Firefox page. Returned as base64 PNG.

---

## firefox_get_text(selector?)
Extract visible text from the Firefox page (up to 4000 chars). Optional CSS selector.

---

## firefox_click(selector)
Click an element by CSS selector.

---

## firefox_type(selector, text, clear_first?)
Type into an input field.

---

## firefox_execute_js(script)
Execute JavaScript in the Firefox page and return the result.

```
firefox_execute_js("document.title")
firefox_execute_js("window.scrollTo(0, document.body.scrollHeight)")
```

---

## firefox_new_tab(url?)
Open a new Firefox tab, optionally navigating to a URL.

---

## firefox_current_url()
Return the current URL of the Firefox page.

---

## firefox_close()
Close the AI-controlled Firefox instance entirely.

---

## Typical Firefox workflow
1. `firefox_navigate(url)` — open a page
2. `firefox_screenshot()` — see it
3. `firefox_get_text()` — read content
4. `firefox_click()` / `firefox_type()` — interact
5. `firefox_screenshot()` — confirm result
