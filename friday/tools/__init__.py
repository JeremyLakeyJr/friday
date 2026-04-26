"""
Tool registry — imports and registers all tool modules with the MCP server.
Add new tool modules here as you build them.
"""

from friday.tools import web, system, utils, bash, browser, skills, auto_browser


def register_all_tools(mcp, *, config=None, skill_store=None):
    """Register all tool groups onto the MCP server instance."""
    web.register(mcp)
    system.register(mcp)
    utils.register(mcp)
    bash.register(mcp)
    browser.register(mcp)
    if skill_store is not None:
        skills.register(mcp, skill_store=skill_store)
    auto_browser.register(mcp)
