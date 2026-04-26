"""Skill discovery, installation, activation, and rollback tools."""

from __future__ import annotations

import httpx

from friday.tools.skill_store import SkillError


def register(mcp, *, skill_store) -> None:
    @mcp.tool()
    def list_skills(active_only: bool = False) -> list:
        """List installed skills and their activation state."""
        return skill_store.list_skills(active_only=active_only)

    @mcp.tool()
    def get_skill(skill_id: str) -> dict:
        """Get the full installed content and metadata for a skill."""
        return skill_store.get_skill(skill_id)

    @mcp.tool()
    def validate_skill_markdown(markdown: str) -> dict:
        """Validate a candidate skill document before installation."""
        return skill_store.validate_skill_markdown(markdown)

    @mcp.tool()
    def install_skill_from_markdown(
        markdown: str,
        source: str = "generated",
        activate: bool = True,
    ) -> dict:
        """Install a skill from markdown front matter and instructions."""
        return skill_store.install_skill_from_markdown(
            markdown,
            source=source,
            source_type="generated",
            activate=activate,
        )

    @mcp.tool()
    async def install_skill_from_url(url: str, activate: bool = True) -> dict:
        """Download, validate, install, and optionally activate a skill from a URL."""
        async with httpx.AsyncClient(follow_redirects=True, timeout=15.0) as client:
            response = await client.get(url)
            response.raise_for_status()
        return skill_store.install_skill_from_markdown(
            response.text,
            source=url,
            source_type="url",
            activate=activate,
        )

    @mcp.tool()
    def activate_skill(skill_id: str) -> dict:
        """Activate an installed skill."""
        return skill_store.activate_skill(skill_id)

    @mcp.tool()
    def deactivate_skill(skill_id: str) -> dict:
        """Deactivate an installed skill."""
        return skill_store.deactivate_skill(skill_id)

    @mcp.tool()
    def remove_skill(skill_id: str) -> dict:
        """Remove a skill and keep a rollback backup."""
        return skill_store.remove_skill(skill_id)

    @mcp.tool()
    def rollback_skill(skill_id: str, backup_file: str = "") -> dict:
        """Restore the latest or selected backup of a skill."""
        return skill_store.rollback_skill(skill_id, backup_file or None)

    @mcp.tool()
    def explain_skill_error(error_text: str) -> str:
        """Normalize skill validation failures for the client."""
        try:
            raise SkillError(error_text)
        except SkillError as exc:
            return str(exc)
