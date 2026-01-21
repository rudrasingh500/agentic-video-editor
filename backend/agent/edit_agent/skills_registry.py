from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SkillSubskill:
    id: str
    title: str
    summary: str
    schema: dict[str, Any]


@dataclass
class SkillSpec:
    id: str
    title: str
    summary: str
    subskills: list[SkillSubskill]


SKILLS_DIR = Path(__file__).resolve().parent / "skills"


def list_skills() -> list[SkillSpec]:
    return list(_load_skills().values())


def read_skill(skill_id: str) -> SkillSpec | None:
    return _load_skills().get(skill_id)


def _load_skills() -> dict[str, SkillSpec]:
    skills: dict[str, SkillSpec] = {}
    if not SKILLS_DIR.exists():
        return skills

    for path in sorted(SKILLS_DIR.glob("*.md")):
        spec = _parse_skill_file(path)
        if spec:
            skills[spec.id] = spec
    return skills


def _parse_skill_file(path: Path) -> SkillSpec | None:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()

    front_matter: dict[str, str] = {}
    idx = 0
    if lines and lines[0].strip() == "---":
        idx = 1
        while idx < len(lines):
            line = lines[idx].strip()
            idx += 1
            if line == "---":
                break
            if not line or line.startswith("#") or ":" not in line:
                continue
            key, value = line.split(":", 1)
            front_matter[key.strip()] = value.strip()

    skill_id = front_matter.get("id", path.stem)
    title = front_matter.get("title", skill_id.title())
    summary = front_matter.get("summary", "")

    subskills: list[SkillSubskill] = []
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("## "):
            heading = line[3:].strip()
            if " - " in heading:
                sub_id, sub_title = heading.split(" - ", 1)
            elif ":" in heading:
                sub_id, sub_title = heading.split(":", 1)
            else:
                sub_id, sub_title = heading, heading.title()
            sub_id = sub_id.strip()
            sub_title = sub_title.strip()

            idx += 1
            sub_summary = ""
            schema: dict[str, Any] = {}

            while idx < len(lines) and not lines[idx].startswith("## "):
                current = lines[idx].strip()
                if current.lower().startswith("summary:"):
                    sub_summary = current.split(":", 1)[1].strip()
                if current.startswith("```json"):
                    idx += 1
                    json_lines: list[str] = []
                    while idx < len(lines) and not lines[idx].startswith("```"):
                        json_lines.append(lines[idx])
                        idx += 1
                    try:
                        schema = json.loads("\n".join(json_lines))
                    except json.JSONDecodeError:
                        schema = {}
                idx += 1

            subskills.append(
                SkillSubskill(
                    id=f"{skill_id}.{sub_id}",
                    title=sub_title,
                    summary=sub_summary,
                    schema=schema,
                )
            )
            continue
        idx += 1

    return SkillSpec(id=skill_id, title=title, summary=summary, subskills=subskills)
