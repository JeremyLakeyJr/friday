"""Auto-browser HTTP client tools wrapping the LvcidPsyche/auto-browser REST API."""

from __future__ import annotations

import json

import httpx


def register(mcp, *, config=None) -> None:
    if config is None:
        from friday.config import config as _config
        config = _config

    if not config.AUTO_BROWSER_URL:
        return

    base_url = config.AUTO_BROWSER_URL.rstrip("/")

    def _headers() -> dict[str, str]:
        headers: dict[str, str] = {}
        if config.AUTO_BROWSER_TOKEN:
            headers["Authorization"] = f"Bearer {config.AUTO_BROWSER_TOKEN}"
        return headers

    @mcp.tool()
    async def auto_browser_list_sessions() -> list:
        """List all active browser sessions in the auto-browser service."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{base_url}/sessions", headers=_headers())
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_create_session(name: str, start_url: str = "about:blank") -> dict:
        """Create a new browser session. Returns session info including session_id.
        If a session already exists (409), it is reused and navigated to start_url."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/sessions",
                json={"name": name, "start_url": start_url},
                headers=_headers(),
            )
            if response.status_code == 409:
                # A session already exists — list and reuse the first one
                list_resp = await client.get(f"{base_url}/sessions", headers=_headers())
                list_resp.raise_for_status()
                sessions = list_resp.json()
                if sessions:
                    session = sessions[0]
                    if start_url and start_url != "about:blank":
                        await client.post(
                            f"{base_url}/sessions/{session['id']}/actions/navigate",
                            json={"url": start_url},
                            headers=_headers(),
                        )
                    return {**session, "reused": True}
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_observe(session_id: str) -> dict:
        """Get the current state of a browser session (screenshot URL, URL, title, DOM summary)."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                f"{base_url}/sessions/{session_id}/observe",
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_navigate(session_id: str, url: str) -> dict:
        """Navigate the browser session to a URL."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/sessions/{session_id}/actions/navigate",
                json={"url": url},
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_click(session_id: str, selector: str) -> dict:
        """Click an element in the browser session using a CSS selector."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/sessions/{session_id}/actions/click",
                json={"selector": selector},
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_type(session_id: str, selector: str, text: str) -> dict:
        """Type text into an element in the browser session using a CSS selector."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/sessions/{session_id}/actions/type",
                json={"selector": selector, "text": text},
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_scroll(
        session_id: str,
        delta_x: int = 0,
        delta_y: int = 300,
    ) -> dict:
        """Scroll the page in the browser session."""
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.post(
                f"{base_url}/sessions/{session_id}/actions/scroll",
                json={"x": 0, "y": 0, "delta_x": delta_x, "delta_y": delta_y},
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_screenshot(session_id: str) -> dict:
        """Take a screenshot of the current browser session state."""
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(
                f"{base_url}/sessions/{session_id}/screenshot",
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_close_session(session_id: str) -> dict:
        """Close and remove a browser session."""
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.delete(
                f"{base_url}/sessions/{session_id}",
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()

    @mcp.tool()
    async def auto_browser_call_mcp_tool(tool_name: str, arguments_json: str = "{}") -> dict:
        """Call one of the auto-browser service's own MCP tools by name with a JSON arguments string."""
        arguments = json.loads(arguments_json)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{base_url}/mcp/tools/call",
                json={"name": tool_name, "arguments": arguments},
                headers=_headers(),
            )
            response.raise_for_status()
            return response.json()
