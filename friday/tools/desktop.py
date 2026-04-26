"""
Desktop tools — full system access for the voice agent.
Process management, file operations, screenshots, clipboard, app control.
"""

import asyncio
import base64
import os
import shutil
import subprocess
import tempfile
from typing import Optional


def register(mcp):

    # ── Process management ────────────────────────────────────────────────────

    @mcp.tool()
    async def list_processes(filter: Optional[str] = None) -> str:
        """
        List running processes (like ps aux).
        Optionally filter by name — e.g. filter='firefox' shows only Firefox procs.
        Returns up to 3000 characters.
        """
        cmd = ["ps", "aux", "--sort=-%cpu"]
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        text = stdout.decode(errors="replace")
        if filter:
            lines = [l for l in text.splitlines() if filter.lower() in l.lower()]
            text = "\n".join(lines[:50])
        return text[:3000]

    @mcp.tool()
    async def kill_process(pid_or_name: str, signal: str = "TERM") -> str:
        """
        Kill a process by PID (integer) or name (partial match).
        signal: TERM (graceful) | KILL (force) | HUP | INT
        """
        try:
            pid = int(pid_or_name)
            proc = await asyncio.create_subprocess_exec(
                "kill", f"-{signal}", str(pid),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return f"Sent {signal} to PID {pid}"
            return f"kill error: {stderr.decode().strip()}"
        except ValueError:
            # Kill by name
            proc = await asyncio.create_subprocess_exec(
                "pkill", f"-{signal}", "-f", pid_or_name,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode == 0:
                return f"Sent {signal} to processes matching '{pid_or_name}'"
            return f"pkill: no matching processes for '{pid_or_name}'"

    # ── File system ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def list_directory(path: str = "~", show_hidden: bool = False) -> str:
        """
        List files in a directory. Returns names, sizes, and types.
        path: directory path (~ expands to home)
        show_hidden: include dotfiles
        """
        expanded = os.path.expanduser(path)
        try:
            entries = os.scandir(expanded)
            lines = []
            for e in sorted(entries, key=lambda x: (not x.is_dir(), x.name.lower())):
                if not show_hidden and e.name.startswith("."):
                    continue
                try:
                    size = e.stat().st_size
                    kind = "dir" if e.is_dir() else "file"
                    lines.append(f"[{kind}] {e.name}  ({size:,} bytes)")
                except Exception:
                    lines.append(f"[?] {e.name}")
            return f"{expanded}:\n" + "\n".join(lines[:200])
        except Exception as e:
            return f"Error listing {expanded}: {e}"

    @mcp.tool()
    async def move_file(source: str, destination: str) -> str:
        """Move or rename a file/directory. Supports ~ expansion."""
        src = os.path.expanduser(source)
        dst = os.path.expanduser(destination)
        try:
            shutil.move(src, dst)
            return f"Moved: {src} → {dst}"
        except Exception as e:
            return f"Move error: {e}"

    @mcp.tool()
    async def copy_file(source: str, destination: str) -> str:
        """Copy a file or directory. Supports ~ expansion."""
        src = os.path.expanduser(source)
        dst = os.path.expanduser(destination)
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            return f"Copied: {src} → {dst}"
        except Exception as e:
            return f"Copy error: {e}"

    @mcp.tool()
    async def delete_file(path: str, recursive: bool = False) -> str:
        """
        Delete a file or directory.
        recursive=True needed for non-empty directories.
        """
        expanded = os.path.expanduser(path)
        try:
            if os.path.isdir(expanded):
                if recursive:
                    shutil.rmtree(expanded)
                    return f"Deleted directory: {expanded}"
                else:
                    os.rmdir(expanded)
                    return f"Deleted empty directory: {expanded}"
            else:
                os.remove(expanded)
                return f"Deleted: {expanded}"
        except Exception as e:
            return f"Delete error: {e}"

    @mcp.tool()
    async def create_directory(path: str) -> str:
        """Create a directory (including parents). Supports ~ expansion."""
        expanded = os.path.expanduser(path)
        try:
            os.makedirs(expanded, exist_ok=True)
            return f"Created directory: {expanded}"
        except Exception as e:
            return f"Error: {e}"

    @mcp.tool()
    async def search_files(pattern: str, directory: str = "~", max_results: int = 50) -> str:
        """
        Search for files matching a glob pattern in a directory.
        pattern: e.g. '*.py', 'README*', '**/*.json'
        directory: root path to search (default: home)
        """
        import glob
        base = os.path.expanduser(directory)
        search_pattern = os.path.join(base, "**", pattern) if "**" not in pattern else os.path.join(base, pattern)
        try:
            matches = glob.glob(search_pattern, recursive=True)[:max_results]
            if not matches:
                return f"No files matching '{pattern}' in {base}"
            return "\n".join(matches)
        except Exception as e:
            return f"Search error: {e}"

    # ── System info ───────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_disk_usage(path: str = "/") -> str:
        """Get disk usage statistics for the given path."""
        expanded = os.path.expanduser(path)
        try:
            usage = shutil.disk_usage(expanded)
            total_gb = usage.total / 1e9
            used_gb = usage.used / 1e9
            free_gb = usage.free / 1e9
            pct = (usage.used / usage.total) * 100
            return (
                f"Path: {expanded}\n"
                f"Total: {total_gb:.1f} GB\n"
                f"Used:  {used_gb:.1f} GB ({pct:.1f}%)\n"
                f"Free:  {free_gb:.1f} GB"
            )
        except Exception as e:
            return f"Disk usage error: {e}"

    @mcp.tool()
    async def get_memory_usage() -> str:
        """Get current RAM and swap usage."""
        try:
            proc = await asyncio.create_subprocess_exec(
                "free", "-h",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            return stdout.decode(errors="replace").strip()
        except Exception as e:
            return f"Memory error: {e}"

    # ── Desktop integration ───────────────────────────────────────────────────

    @mcp.tool()
    async def take_screenshot(save_path: Optional[str] = None) -> str:
        """
        Take a screenshot of the desktop.
        save_path: optional file path to save PNG (default: temp file).
        Returns base64-encoded PNG if no save_path, otherwise the saved path.
        Uses ImageMagick's `import` command.
        """
        if save_path:
            path = os.path.expanduser(save_path)
        else:
            fd, path = tempfile.mkstemp(suffix=".png")
            os.close(fd)
        try:
            proc = await asyncio.create_subprocess_exec(
                "import", "-window", "root", path,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ},
            )
            _, stderr = await asyncio.wait_for(proc.communicate(), timeout=10)
            if proc.returncode != 0:
                return f"Screenshot error: {stderr.decode().strip()}"
            if save_path:
                return f"Screenshot saved to: {path}"
            with open(path, "rb") as f:
                data = base64.b64encode(f.read()).decode()
            os.unlink(path)
            return f"data:image/png;base64,{data}"
        except asyncio.TimeoutError:
            return "Screenshot timed out"
        except Exception as e:
            return f"Screenshot error: {e}"

    @mcp.tool()
    def open_application(name_or_path: str, args: Optional[str] = None) -> str:
        """
        Launch a desktop application (e.g. 'firefox', 'nautilus', 'gedit ~/notes.txt').
        name_or_path: executable name or full path
        args: optional space-separated arguments string
        """
        try:
            cmd = [name_or_path]
            if args:
                cmd += args.split()
            subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            return f"Launched: {' '.join(cmd)}"
        except Exception as e:
            return f"Launch error: {e}"

    @mcp.tool()
    def open_file_with_app(path: str) -> str:
        """
        Open a file with its default application (xdg-open).
        Works for PDFs, images, audio files, URLs, etc.
        """
        expanded = os.path.expanduser(path)
        try:
            subprocess.Popen(
                ["xdg-open", expanded],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Opened: {expanded}"
        except Exception as e:
            return f"Open error: {e}"

    # ── Clipboard ─────────────────────────────────────────────────────────────

    @mcp.tool()
    async def get_clipboard() -> str:
        """Read the current clipboard text content (requires xclip or xsel)."""
        for tool, args in [
            ("xclip", ["-selection", "clipboard", "-out"]),
            ("xsel", ["--clipboard", "--output"]),
        ]:
            if shutil.which(tool):
                proc = await asyncio.create_subprocess_exec(
                    tool, *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await proc.communicate()
                return stdout.decode(errors="replace")[:2000]
        return "No clipboard tool found (install xclip or xsel)"

    @mcp.tool()
    async def set_clipboard(text: str) -> str:
        """Write text to the clipboard (requires xclip or xsel)."""
        for tool, args in [
            ("xclip", ["-selection", "clipboard"]),
            ("xsel", ["--clipboard", "--input"]),
        ]:
            if shutil.which(tool):
                proc = await asyncio.create_subprocess_exec(
                    tool, *args,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await proc.communicate(input=text.encode())
                return f"Clipboard set ({len(text)} chars)"
        return "No clipboard tool found (install xclip or xsel)"

    # ── Notifications ─────────────────────────────────────────────────────────

    @mcp.tool()
    def send_desktop_notification(title: str, message: str, urgency: str = "normal") -> str:
        """
        Send a desktop notification via libnotify (notify-send).
        urgency: low | normal | critical
        """
        if not shutil.which("notify-send"):
            return "notify-send not found (install libnotify-bin)"
        try:
            subprocess.Popen(
                ["notify-send", "-u", urgency, title, message],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return f"Notification sent: {title}"
        except Exception as e:
            return f"Notification error: {e}"
