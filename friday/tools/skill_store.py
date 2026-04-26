"""Skill storage, validation, provenance tracking, and rollback support."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

SERVER_VERSION = "0.2.0"

SKILL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")


class SkillError(ValueError):
    """Base exception for skill validation and installation failures."""


@dataclass(slots=True)
class SkillDocument:
    skill_id: str
    name: str
    version: str
    description: str
    instructions: str
    capabilities: list[str]
    min_server_version: str


class SkillStore:
    """Persist and manage installable markdown-based skills."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.installed_dir = self.root / "installed"
        self.backups_dir = self.root / "backups"
        self.registry_path = self.root / "registry.json"

        self.installed_dir.mkdir(parents=True, exist_ok=True)
        self.backups_dir.mkdir(parents=True, exist_ok=True)
        if not self.registry_path.exists():
            self._save_registry({})

        self._sync_registry_with_disk()

    def list_skills(self, active_only: bool = False) -> list[dict[str, Any]]:
        registry = self._load_registry()
        records = sorted(registry.values(), key=lambda item: item["id"])
        if active_only:
            records = [item for item in records if item["active"]]
        return records

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        registry = self._load_registry()
        record = registry.get(skill_id)
        if record is None:
            raise SkillError(f"Unknown skill '{skill_id}'.")

        content = Path(record["path"]).read_text(encoding="utf-8")
        return {
            **record,
            "content": content,
        }

    def validate_skill_markdown(self, markdown: str) -> dict[str, Any]:
        document = self._parse_skill(markdown)
        self._ensure_compatible(document.min_server_version)
        return asdict(document)

    def install_skill_from_markdown(
        self,
        markdown: str,
        *,
        source: str,
        source_type: str,
        activate: bool = True,
    ) -> dict[str, Any]:
        document = self._parse_skill(markdown)
        self._ensure_compatible(document.min_server_version)

        registry = self._load_registry()
        target_path = self.installed_dir / f"{document.skill_id}.md"
        backup_path = None

        if target_path.exists():
            timestamp = self._timestamp_slug()
            backup_path = self.backups_dir / f"{document.skill_id}-{timestamp}.md"
            shutil.copy2(target_path, backup_path)

        target_path.write_text(self._serialize_skill(document), encoding="utf-8")

        record = {
            "id": document.skill_id,
            "name": document.name,
            "version": document.version,
            "description": document.description,
            "capabilities": document.capabilities,
            "min_server_version": document.min_server_version,
            "active": activate,
            "source": source,
            "source_type": source_type,
            "installed_at": self._timestamp(),
            "checksum": self._checksum(target_path.read_text(encoding="utf-8")),
            "path": str(target_path),
            "backup_path": str(backup_path) if backup_path else None,
        }
        registry[document.skill_id] = record
        self._save_registry(registry)
        return record

    def activate_skill(self, skill_id: str) -> dict[str, Any]:
        return self._set_active_state(skill_id, True)

    def deactivate_skill(self, skill_id: str) -> dict[str, Any]:
        return self._set_active_state(skill_id, False)

    def remove_skill(self, skill_id: str) -> dict[str, Any]:
        registry = self._load_registry()
        record = registry.get(skill_id)
        if record is None:
            raise SkillError(f"Unknown skill '{skill_id}'.")

        skill_path = Path(record["path"])
        removed = skill_path.exists()
        if removed:
            timestamp = self._timestamp_slug()
            backup_path = self.backups_dir / f"{skill_id}-{timestamp}.md"
            shutil.move(str(skill_path), backup_path)
            record["backup_path"] = str(backup_path)

        registry.pop(skill_id)
        self._save_registry(registry)
        return {
            "removed": removed,
            "skill_id": skill_id,
            "backup_path": record.get("backup_path"),
        }

    def rollback_skill(self, skill_id: str, backup_file: str | None = None) -> dict[str, Any]:
        candidates = sorted(self.backups_dir.glob(f"{skill_id}-*.md"))
        if backup_file is not None:
            candidate = (self.backups_dir / backup_file).resolve()
            if candidate not in [path.resolve() for path in candidates]:
                raise SkillError(f"Unknown backup '{backup_file}' for skill '{skill_id}'.")
        else:
            if not candidates:
                raise SkillError(f"No backups available for skill '{skill_id}'.")
            candidate = candidates[-1].resolve()

        markdown = candidate.read_text(encoding="utf-8")
        record = self.install_skill_from_markdown(
            markdown,
            source=str(candidate),
            source_type="rollback",
            activate=True,
        )
        record["restored_from"] = str(candidate)
        return record

    def render_skill_catalog(self) -> str:
        skills = self.list_skills()
        if not skills:
            return "No skills are installed."

        lines = ["# Installed Skills", ""]
        for skill in skills:
            status = "active" if skill["active"] else "inactive"
            capabilities = ", ".join(skill.get("capabilities") or []) or "none"
            lines.extend(
                [
                    f"## {skill['name']} (`{skill['id']}`)",
                    f"- Version: {skill['version']}",
                    f"- Status: {status}",
                    f"- Source: {skill['source_type']} ({skill['source']})",
                    f"- Capabilities: {capabilities}",
                    f"- Description: {skill['description']}",
                    "",
                ]
            )
        return "\n".join(lines).rstrip()

    def render_active_skill_instructions(self) -> str:
        active_skills = self.list_skills(active_only=True)
        if not active_skills:
            return "No active skills are installed."

        sections = ["# Active Skills", ""]
        for skill in active_skills:
            content = Path(skill["path"]).read_text(encoding="utf-8")
            document = self._parse_skill(content)
            sections.extend(
                [
                    f"## {document.name} (`{document.skill_id}`)",
                    document.instructions.strip(),
                    "",
                ]
            )
        return "\n".join(sections).rstrip()

    def _set_active_state(self, skill_id: str, active: bool) -> dict[str, Any]:
        registry = self._load_registry()
        record = registry.get(skill_id)
        if record is None:
            raise SkillError(f"Unknown skill '{skill_id}'.")
        record["active"] = active
        registry[skill_id] = record
        self._save_registry(registry)
        return record

    def _sync_registry_with_disk(self) -> None:
        registry = self._load_registry()
        changed = False

        for markdown_file in sorted(self.installed_dir.glob("*.md")):
            content = markdown_file.read_text(encoding="utf-8")
            document = self._parse_skill(content)
            existing = registry.get(document.skill_id)
            checksum = self._checksum(content)
            if existing is None or existing.get("checksum") != checksum:
                registry[document.skill_id] = {
                    "id": document.skill_id,
                    "name": document.name,
                    "version": document.version,
                    "description": document.description,
                    "capabilities": document.capabilities,
                    "min_server_version": document.min_server_version,
                    "active": existing["active"] if existing is not None else True,
                    "source": existing["source"] if existing is not None else "bundled",
                    "source_type": existing["source_type"] if existing is not None else "bundled",
                    "installed_at": existing["installed_at"] if existing is not None else self._timestamp(),
                    "checksum": checksum,
                    "path": str(markdown_file),
                    "backup_path": existing["backup_path"] if existing is not None else None,
                }
                changed = True

        missing = [skill_id for skill_id, record in registry.items() if not Path(record["path"]).exists()]
        for skill_id in missing:
            registry.pop(skill_id)
            changed = True

        if changed:
            self._save_registry(registry)

    def _parse_skill(self, markdown: str) -> SkillDocument:
        lines = markdown.splitlines()
        if not lines or lines[0].strip() != "---":
            raise SkillError("Skill markdown must start with YAML front matter.")

        closing_index = None
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                closing_index = index
                break
        if closing_index is None:
            raise SkillError("Skill front matter is missing a closing '---' line.")

        front_matter = "\n".join(lines[1:closing_index])
        body = "\n".join(lines[closing_index + 1:]).strip()
        if not body:
            raise SkillError("Skill instructions cannot be empty.")

        metadata = yaml.safe_load(front_matter) or {}
        skill_id = str(metadata.get("id", "")).strip()
        if not SKILL_ID_RE.match(skill_id):
            raise SkillError(
                "Skill id is required and must match ^[a-z0-9][a-z0-9-]{1,63}$."
            )

        name = str(metadata.get("name", "")).strip()
        version = str(metadata.get("version", "")).strip()
        description = str(metadata.get("description", "")).strip()
        min_server_version = str(metadata.get("min_server_version", SERVER_VERSION)).strip()
        capabilities = metadata.get("capabilities") or []
        if not name or not version or not description:
            raise SkillError("Skill front matter requires name, version, and description.")
        if not isinstance(capabilities, list) or not all(
            isinstance(item, str) and item.strip() for item in capabilities
        ):
            raise SkillError("Skill capabilities must be a list of non-empty strings.")

        return SkillDocument(
            skill_id=skill_id,
            name=name,
            version=version,
            description=description,
            instructions=body,
            capabilities=[item.strip() for item in capabilities],
            min_server_version=min_server_version,
        )

    def _serialize_skill(self, document: SkillDocument) -> str:
        metadata = {
            "id": document.skill_id,
            "name": document.name,
            "version": document.version,
            "description": document.description,
            "capabilities": document.capabilities,
            "min_server_version": document.min_server_version,
        }
        front_matter = yaml.safe_dump(metadata, sort_keys=False).strip()
        return f"---\n{front_matter}\n---\n{document.instructions.strip()}\n"

    def _ensure_compatible(self, min_server_version: str) -> None:
        if self._version_tuple(min_server_version) > self._version_tuple(SERVER_VERSION):
            raise SkillError(
                f"Skill requires server version {min_server_version} or newer."
            )

    def _version_tuple(self, version: str) -> tuple[int, int, int]:
        parts = version.split(".")
        if len(parts) != 3 or any(not part.isdigit() for part in parts):
            raise SkillError(
                f"Version '{version}' must use simple semantic versioning like 0.1.0."
            )
        return tuple(int(part) for part in parts)

    def _load_registry(self) -> dict[str, dict[str, Any]]:
        return json.loads(self.registry_path.read_text(encoding="utf-8"))

    def _save_registry(self, registry: dict[str, dict[str, Any]]) -> None:
        self.registry_path.write_text(
            json.dumps(registry, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def _checksum(self, content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def _timestamp(self) -> str:
        return datetime.now(UTC).isoformat()

    def _timestamp_slug(self) -> str:
        return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
