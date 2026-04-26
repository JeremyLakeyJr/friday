"""
Firefox tool — control a Firefox browser via Playwright.
Runs a headed Firefox instance so the user can see the AI browsing in real time.
Falls back to headless=True if no display is available.
"""

import asyncio
import base64
import os
import subprocess
from typing import Optional

_pw = None
_browser = None
_page = None
_init_lock = asyncio.Lock()


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


async def _get_page():
    global _pw, _browser, _page
    async with _init_lock:
        if _browser is None:
            from playwright.async_api import async_playwright
            _pw = await async_playwright().start()
            headless = not _has_display()
            _browser = await _pw.firefox.launch(
                headless=headless,
                args=["--no-remote"],
            )
        if _page is None or _page.is_closed():
            _page = await _browser.new_page(
                viewport={"width": 1280, "height": 800},
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64; rv:146.0) "
                    "Gecko/20100101 Firefox/146.0"
                ),
            )
    return _page


async def close_firefox():
    global _pw, _browser, _page
    if _page is not None:
        try:
            await _page.close()
        except Exception:
            pass
        _page = None
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


def open_in_real_firefox(url: str) -> str:
    """Open a URL in the user's running Firefox (not the AI-controlled instance)."""
    try:
        subprocess.Popen(
            ["firefox", "--new-tab", url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return f"Opened in Firefox: {url}"
    except Exception as e:
        return f"Error opening Firefox: {e}"


def register(mcp):

    @mcp.tool()
    async def firefox_navigate(url: str) -> str:
        """
        Navigate the AI-controlled Firefox browser to a URL.
        A headed Firefox window opens so the user can see it.
        Returns page title and status.
        """
        page = await _get_page()
        try:
            resp = await page.goto(url, wait_until="domcontentloaded", timeout=25000)
            title = await page.title()
            status = resp.status if resp else "unknown"
            return f"Navigated to: {url}\nTitle: {title}\nStatus: {status}"
        except Exception as e:
            return f"Navigation error: {e}"

    @mcp.tool()
    async def firefox_screenshot() -> str:
        """
        Take a screenshot of the current Firefox page.
        Returns base64-encoded PNG (prefix: data:image/png;base64,...).
        """
        page = await _get_page()
        try:
            data = await page.screenshot(full_page=False)
            encoded = base64.b64encode(data).decode()
            return f"data:image/png;base64,{encoded}"
        except Exception as e:
            return f"Screenshot error: {e}"

    @mcp.tool()
    async def firefox_get_text(selector: Optional[str] = None) -> str:
        """
        Get visible text from the current Firefox page.
        Optionally scope to a CSS selector (e.g. 'article', 'main', '#content').
        Returns up to 4000 characters.
        """
        page = await _get_page()
        try:
            if selector:
                el = await page.query_selector(selector)
                if not el:
                    return f"No element matching: {selector}"
                text = await el.inner_text()
            else:
                text = await page.inner_text("body")
            return text[:4000].strip()
        except Exception as e:
            return f"Error getting text: {e}"

    @mcp.tool()
    async def firefox_click(selector: str) -> str:
        """Click an element on the current Firefox page by CSS selector."""
        page = await _get_page()
        try:
            await page.click(selector, timeout=8000)
            await page.wait_for_load_state("domcontentloaded", timeout=8000)
            return f"Clicked: {selector}"
        except Exception as e:
            return f"Click error: {e}"

    @mcp.tool()
    async def firefox_type(selector: str, text: str, clear_first: bool = True) -> str:
        """Type text into an input field in Firefox by CSS selector."""
        page = await _get_page()
        try:
            if clear_first:
                await page.fill(selector, text, timeout=8000)
            else:
                await page.type(selector, text, delay=30)
            return f"Typed into {selector}"
        except Exception as e:
            return f"Type error: {e}"

    @mcp.tool()
    async def firefox_execute_js(script: str) -> str:
        """Execute JavaScript in the current Firefox page. Returns the result."""
        page = await _get_page()
        try:
            result = await page.evaluate(script)
            return str(result)[:2000]
        except Exception as e:
            return f"JS error: {e}"

    @mcp.tool()
    async def firefox_current_url() -> str:
        """Return the current URL of the Firefox page."""
        page = await _get_page()
        return page.url

    @mcp.tool()
    async def firefox_new_tab(url: str = "about:blank") -> str:
        """Open a new Firefox tab and navigate to the given URL."""
        global _page
        async with _init_lock:
            if _browser is None:
                await _get_page()  # ensure browser is initialised
        try:
            _page = await _browser.new_page(
                viewport={"width": 1280, "height": 800},
            )
            if url != "about:blank":
                resp = await _page.goto(url, wait_until="domcontentloaded", timeout=25000)
                title = await _page.title()
                return f"New tab: {url} — {title}"
            return "New blank tab opened"
        except Exception as e:
            return f"New tab error: {e}"

    @mcp.tool()
    async def firefox_close() -> str:
        """Close the AI-controlled Firefox browser."""
        await close_firefox()
        return "Firefox closed."

    @mcp.tool()
    def firefox_open_in_system(url: str) -> str:
        """
        Open a URL in the user's real running Firefox browser (not AI-controlled).
        Use this when you want the user to see a page in their normal Firefox window.
        """
        return open_in_real_firefox(url)
