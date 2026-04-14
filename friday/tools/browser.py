"""
Browser tool — control a headless Chromium browser via Playwright.
Per-chat isolation: each Telegram chat gets its own browser context + page.
Screenshots are returned as base64-encoded PNG data.
"""

import asyncio
import base64
import contextvars
from typing import Optional

# Set before tool calls in agent.py to route to the correct per-chat page
current_chat_id: contextvars.ContextVar[int] = contextvars.ContextVar("current_chat_id", default=0)

_pw = None           # playwright instance (shared)
_browser = None      # browser process (shared)
_pages: dict[int, object] = {}   # chat_id → Page
_init_lock = asyncio.Lock()


async def _get_page() -> object:
    """Lazily init browser; return the page for the current chat."""
    global _pw, _browser

    async with _init_lock:
        if _browser is None:
            from playwright.async_api import async_playwright
            _pw = await async_playwright().start()
            _browser = await _pw.chromium.launch(headless=True)

    chat_id = current_chat_id.get()
    if chat_id not in _pages:
        context = await _browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent=(
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
        )
        _pages[chat_id] = await context.new_page()

    return _pages[chat_id]


async def close_browser():
    """Gracefully close all pages and the browser process."""
    global _pw, _browser, _pages
    for page in list(_pages.values()):
        try:
            await page.context.close()
        except Exception:
            pass
    _pages.clear()
    if _browser is not None:
        try:
            await _browser.close()
        except Exception:
            pass
        _browser = None
    if _pw is not None:
        try:
            await _pw.stop()
        except Exception:
            pass
        _pw = None


def register(mcp):

    @mcp.tool()
    async def browser_navigate(url: str) -> str:
        """Navigate the browser to the given URL. Returns page title."""
        page = await _get_page()
        try:
            response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            title = await page.title()
            return f"Navigated to: {url}\nTitle: {title}\nStatus: {response.status if response else 'unknown'}"
        except Exception as e:
            return f"Navigation error: {e}"

    @mcp.tool()
    async def browser_screenshot() -> str:
        """
        Take a screenshot of the current browser page.
        Returns base64-encoded PNG data (prefix: data:image/png;base64,...).
        When used via Telegram agent, this will be sent as a photo.
        """
        page = await _get_page()
        try:
            data = await page.screenshot(full_page=False)
            encoded = base64.b64encode(data).decode()
            return f"data:image/png;base64,{encoded}"
        except Exception as e:
            return f"Screenshot error: {e}"

    @mcp.tool()
    async def browser_get_text(selector: Optional[str] = None) -> str:
        """
        Extract visible text from the current page.
        Optionally scope to a CSS selector (e.g. 'article', 'main', '#content').
        Returns up to 4000 characters.
        """
        page = await _get_page()
        try:
            if selector:
                element = await page.query_selector(selector)
                if not element:
                    return f"No element matching selector: {selector}"
                text = await element.inner_text()
            else:
                text = await page.inner_text("body")
            return text[:4000].strip()
        except Exception as e:
            return f"Error getting text: {e}"

    @mcp.tool()
    async def browser_get_html(selector: Optional[str] = None) -> str:
        """
        Get the HTML source of the current page (or a scoped element).
        Returns up to 6000 characters.
        """
        page = await _get_page()
        try:
            if selector:
                element = await page.query_selector(selector)
                if not element:
                    return f"No element matching selector: {selector}"
                html = await element.inner_html()
            else:
                html = await page.content()
            return html[:6000]
        except Exception as e:
            return f"Error getting HTML: {e}"

    @mcp.tool()
    async def browser_click(selector: str) -> str:
        """Click an element on the current page identified by CSS selector."""
        page = await _get_page()
        try:
            await page.click(selector, timeout=5000)
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            return f"Clicked: {selector}"
        except Exception as e:
            return f"Click error: {e}"

    @mcp.tool()
    async def browser_type(selector: str, text: str, clear_first: bool = True) -> str:
        """Type text into an input field identified by CSS selector."""
        page = await _get_page()
        try:
            if clear_first:
                await page.fill(selector, text, timeout=5000)
            else:
                await page.type(selector, text, delay=30)
            return f"Typed into {selector}"
        except Exception as e:
            return f"Type error: {e}"

    @mcp.tool()
    async def browser_current_url() -> str:
        """Return the current URL of the browser."""
        page = await _get_page()
        return page.url
