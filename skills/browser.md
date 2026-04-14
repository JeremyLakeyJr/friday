# Skill: Web Browser (Playwright)

A full headless Chromium browser. Each Telegram chat gets its own isolated browser session — pages don't bleed between users.

## browser_navigate(url)
Go to a URL. Returns page title + HTTP status.

```
browser_navigate("https://github.com")
browser_navigate("https://news.ycombinator.com")
```

---

## browser_screenshot()
Take a screenshot of the current page. The image is automatically sent to the user as a photo in Telegram — just describe what you see.
Use after navigation or interactions to show the user the result.

---

## browser_get_text(selector?)
Extract visible text (up to 4000 chars). Optionally scope to a CSS selector.

```
browser_get_text()              # full page
browser_get_text("article")     # just the article
browser_get_text("main")        # main content area
browser_get_text("#results")    # by ID
```

---

## browser_get_html(selector?)
Get raw HTML source (up to 6000 chars). Useful for scraping or understanding page structure.

---

## browser_click(selector)
Click an element by CSS selector. Waits for page to settle after click.

```
browser_click("button[type=submit]")
browser_click(".accept-cookies")
browser_click("a[href='/login']")
```

---

## browser_type(selector, text, clear_first?)
Type into an input field. `clear_first=True` (default) replaces existing value.

```
browser_type("#search", "OpenAI news")
browser_type("input[name=email]", "user@example.com")
```

---

## browser_current_url()
Return the current URL of the browser page.

---

## Typical browser workflow
1. `browser_navigate(url)` — go to the page
2. `browser_screenshot()` — show the user what you see
3. `browser_get_text()` or `browser_get_html()` — extract content
4. `browser_click()` / `browser_type()` — interact
5. `browser_screenshot()` again — confirm result
