"""
MCP Resources — expose static or dynamic data to the client.
"""

from friday.resources import data


def register_all_resources(mcp, *, skill_store=None):
    data.register(mcp, skill_store=skill_store)
