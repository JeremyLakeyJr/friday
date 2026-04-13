"""
Bash tool — execute shell commands on the host machine.
"""

import asyncio
import os


def register(mcp):

    @mcp.tool()
    async def run_bash(command: str, timeout: int = 30, working_dir: str = None) -> dict:
        """
        Execute a bash command on the host machine.
        Returns stdout, stderr, exit_code, and working_dir.
        Use for file operations, running scripts, checking system state, etc.
        """
        cwd = working_dir or os.path.expanduser("~")
        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
                executable="/bin/bash",
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                proc.kill()
                return {
                    "stdout": "",
                    "stderr": f"Command timed out after {timeout}s",
                    "exit_code": -1,
                    "working_dir": cwd,
                }
            return {
                "stdout": stdout.decode(errors="replace").strip(),
                "stderr": stderr.decode(errors="replace").strip(),
                "exit_code": proc.returncode,
                "working_dir": cwd,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "working_dir": cwd,
            }

    @mcp.tool()
    async def read_file(path: str) -> str:
        """Read the contents of a file at the given path."""
        try:
            expanded = os.path.expanduser(path)
            with open(expanded, "r", errors="replace") as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"

    @mcp.tool()
    async def write_file(path: str, content: str) -> str:
        """Write content to a file at the given path (creates or overwrites)."""
        try:
            expanded = os.path.expanduser(path)
            os.makedirs(os.path.dirname(expanded) or ".", exist_ok=True)
            with open(expanded, "w") as f:
                f.write(content)
            return f"Written {len(content)} bytes to {expanded}"
        except Exception as e:
            return f"Error writing file: {e}"
