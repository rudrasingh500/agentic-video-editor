from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class SkillSubskill:
    id: str
    title: str
    summary: str
    schema: dict[str, Any]
    complexity: str = "moderate"
    prerequisites: list[str] = field(default_factory=list)
    common_errors: list[dict[str, str]] = field(default_factory=list)
    examples: list[dict[str, Any]] = field(default_factory=list)
    tips: list[str] = field(default_factory=list)
    steps: list[str] = field(default_factory=list)


@dataclass
class SkillSpec:
    id: str
    title: str
    summary: str
    subskills: list[SkillSubskill]
    category: str = "editing"
    complexity: str = "moderate"


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
    category = front_matter.get("category", "editing")
    skill_complexity = front_matter.get("complexity", "moderate")

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
            sub_complexity = "moderate"
            prerequisites: list[str] = []
            common_errors: list[dict[str, str]] = []
            examples: list[dict[str, Any]] = []
            tips: list[str] = []
            schema: dict[str, Any] = {}
            expect_example = False
            steps: list[str] = []

            while idx < len(lines) and not lines[idx].startswith("## "):
                current = lines[idx].strip()
                lowered = current.lower()
                if lowered.startswith("summary:"):
                    sub_summary = current.split(":", 1)[1].strip()
                    idx += 1
                    continue
                if lowered.startswith("complexity:"):
                    sub_complexity = current.split(":", 1)[1].strip()
                    idx += 1
                    continue
                if lowered.startswith("prerequisites:"):
                    prereq_raw = current.split(":", 1)[1].strip()
                    if prereq_raw and prereq_raw.lower() != "none":
                        prerequisites = [p.strip() for p in prereq_raw.split(",") if p.strip()]
                    idx += 1
                    continue
                if lowered.startswith("tip:"):
                    tips.append(current.split(":", 1)[1].strip())
                    idx += 1
                    continue
                if lowered == "common errors:":
                    idx += 1
                    while idx < len(lines):
                        error_line = lines[idx].strip()
                        if not error_line.startswith("- "):
                            break
                        error_text = error_line[2:].strip()
                        if ":" in error_text:
                            error_msg, recovery = error_text.split(":", 1)
                            common_errors.append(
                                {
                                    "error": error_msg.strip(),
                                    "recovery": recovery.strip(),
                                }
                            )
                        else:
                            common_errors.append({"error": error_text, "recovery": ""})
                        idx += 1
                    continue
                if lowered == "steps:":
                    idx += 1
                    while idx < len(lines):
                        step_line = lines[idx].strip()
                        if not step_line or step_line.startswith("## "):
                            break
                        if step_line[0].isdigit() and "." in step_line:
                            steps.append(step_line.split(".", 1)[1].strip())
                        elif step_line.startswith("- "):
                            steps.append(step_line[2:].strip())
                        else:
                            break
                        idx += 1
                    continue
                if lowered == "example:":
                    expect_example = True
                    idx += 1
                    continue
                if current.startswith("```json"):
                    idx += 1
                    json_lines: list[str] = []
                    while idx < len(lines) and not lines[idx].startswith("```"):
                        json_lines.append(lines[idx])
                        idx += 1
                    if expect_example:
                        try:
                            examples.append(json.loads("\n".join(json_lines)))
                        except json.JSONDecodeError:
                            pass
                        expect_example = False
                    else:
                        try:
                            schema = json.loads("\n".join(json_lines))
                        except json.JSONDecodeError:
                            schema = {}
                    idx += 1
                    continue
                idx += 1

            subskills.append(
                SkillSubskill(
                    id=f"{skill_id}.{sub_id}",
                    title=sub_title,
                    summary=sub_summary,
                    schema=schema,
                    complexity=sub_complexity,
                    prerequisites=prerequisites,
                    common_errors=common_errors,
                    examples=examples,
                    tips=tips,
                    steps=steps,
                )
            )
            continue
        idx += 1

    return SkillSpec(
        id=skill_id,
        title=title,
        summary=summary,
        subskills=subskills,
        category=category,
        complexity=skill_complexity,
    )
