"""
Data resources — expose static content or dynamic data via MCP resources.
"""


def register(mcp, *, skill_store=None):

    @mcp.resource("friday://info")
    def server_info() -> str:
        """Returns basic info about this MCP server."""
        return (
            "Friday MCP Server\n"
            "A Tony Stark-inspired AI assistant.\n"
            "Built with FastMCP."
        )

    if skill_store is not None:
        @mcp.resource("skills://catalog")
        def skills_catalog() -> str:
            """Return the installed skill catalog."""
            return skill_store.render_skill_catalog()

        @mcp.resource("skills://active")
        def active_skills() -> str:
            """Return the instructions for all active skills."""
            return skill_store.render_active_skill_instructions()
