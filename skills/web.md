# Skill: Web Search & News

## search_web(query)
DuckDuckGo search — no API key needed. Returns top 5 results with title, snippet, and URL.

Use this to find URLs before navigating, or to get quick info without a full browser session.

```
search_web("best Python async libraries 2024")
search_web("how to install docker on ubuntu")
search_web("OpenAI GPT-4o release notes")
```

**Tip:** Use `search_web` first to find the right URL, then `browser_navigate` to visit it.

---

## fetch_url(url)
Fetch raw text content of any URL directly — no browser, fast. Good for APIs, plain text pages, documentation, JSON endpoints.

```
fetch_url("https://api.github.com/repos/openai/openai-python")
fetch_url("https://raw.githubusercontent.com/user/repo/main/README.md")
```

Use `browser_navigate` instead when you need JavaScript rendering or need to interact with the page.

---

## get_world_news()
Fetch latest global headlines from major news RSS feeds simultaneously. No query needed — just call it.

```
get_world_news()
```
