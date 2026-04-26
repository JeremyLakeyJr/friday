"""
Friday MCP Server — Entry Point
Run with: python server.py
"""

from pathlib import Path

from mcp.server.fastmcp import FastMCP

from friday.config import config
from friday.prompts import register_all_prompts
from friday.resources import register_all_resources
from friday.tools import register_all_tools
from friday.tools.skill_store import SkillStore

skill_store = SkillStore(Path(config.FRIDAY_MCP_SKILLS_ROOT).expanduser().resolve())

# Create the MCP server instance
mcp = FastMCP(
    name=config.SERVER_NAME,
    instructions=(
        "You are Friday, a Tony Stark-style AI assistant. "
        "You have access to a set of tools to help the user. "
        "Be concise, accurate, and a little witty."
    ),
)

# Register tools, prompts, and resources
register_all_tools(mcp, skill_store=skill_store)
register_all_prompts(mcp)
register_all_resources(mcp, skill_store=skill_store)


def main():
    mcp.run(transport=config.FRIDAY_MCP_TRANSPORT)


if __name__ == "__main__":
    main()
