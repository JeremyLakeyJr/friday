"""
Browser tool — control a headless Chromium browser via Playwright.
Screenshots are returned as base64-encoded PNG data.
"""

import asyncio
import base64
from typing import Optional

_browser = None
_page = None
_lock = asyncio.Lock()


async def _get_page():
    """Lazily initialise the Playwright browser and return the active page."""
    global _browser, _page
    async with _lock:
        if _browser is None:
            from playwright.async_api import async_playwright
            pw = await async_playwright().start()
            _browser = await pw.chromium.launch(headless=True)
            context = await _browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
            )
            _page = await context.new_page()
        return _page


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
