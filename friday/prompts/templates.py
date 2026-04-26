"""
Reusable prompt templates registered with the MCP server.
"""


def register(mcp):

    @mcp.prompt()
    def summarize(text: str) -> str:
        """Prompt to summarize a block of text."""
        return f"Summarize the following text concisely:\n\n{text}"

    @mcp.prompt()
    def explain_code(code: str, language: str = "Python") -> str:
        """Prompt to explain a block of code."""
        return (
            f"Explain the following {language} code in plain English, "
            f"step by step:\n\n```{language.lower()}\n{code}\n```"
        )

    @mcp.prompt()
    def research_missing_capability(task: str, constraints: str = "") -> str:
        """Prompt to research a missing capability before authoring a skill."""
        parts = [
            f"You need to accomplish the following task but lack a skill for it:\n\n{task}",
        ]
        if constraints:
            parts.append(f"\nConstraints:\n{constraints}")
        parts.append(
            "\nResearch what tools, APIs, or approaches are available to solve this. "
            "Summarise your findings and recommend the best approach before authoring a skill."
        )
        return "\n".join(parts)

    @mcp.prompt()
    def author_skill(skill_name: str, capability_gap: str, available_tools: str = "") -> str:
        """Prompt to author a new skill document in the required markdown format."""
        parts = [
            f"Author a new skill named '{skill_name}' that addresses the following capability gap:\n\n{capability_gap}",
        ]
        if available_tools:
            parts.append(f"\nAvailable tools you may reference:\n{available_tools}")
        parts.append(
            "\nThe skill must be a markdown document with YAML front matter containing: "
            "id, name, version, description, capabilities (list), and min_server_version. "
            "The body must contain clear instructions for using this skill. "
            "Use id format: lowercase alphanumeric with hyphens (e.g. my-skill-01)."
        )
        return "\n".join(parts)

    @mcp.prompt()
    def review_skill_candidate(markdown: str) -> str:
        """Prompt to review a candidate skill document for correctness and quality."""
        return (
            "Review the following skill document for correctness, completeness, and quality. "
            "Check that the YAML front matter is valid, the id matches the required format, "
            "and the instructions are clear and actionable. Suggest improvements if needed.\n\n"
            f"```markdown\n{markdown}\n```"
        )
