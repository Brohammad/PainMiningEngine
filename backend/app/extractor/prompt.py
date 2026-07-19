"""Loading and rendering for the versioned extraction prompt contract."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast


class PromptContractError(ValueError):
    """Raised when the versioned prompt file is malformed."""


@dataclass(frozen=True, slots=True)
class ExtractionPrompt:
    """Prompt content and templates loaded from one versioned Markdown file."""

    system_prompt: str
    version: str
    user_template: str
    comment_template: str

    @classmethod
    def load(cls, path: Path) -> "ExtractionPrompt":
        """Load prompt instructions and both text templates from disk."""

        content = path.read_text(encoding="utf-8")
        version_match = re.search(
            r"\*\*prompt_version:\*\*\s*`([^`]+)`",
            content,
        )
        if version_match is None:
            raise PromptContractError("prompt_version is missing")

        try:
            template_section = content.split("## User message template", 1)[1]
        except IndexError as exc:
            raise PromptContractError(
                "user message template section is missing"
            ) from exc

        text_blocks = re.findall(
            r"```text\s*\n(.*?)```",
            template_section,
            flags=re.DOTALL,
        )
        if len(text_blocks) < 2:
            raise PromptContractError("user and comment text templates are required")

        return cls(
            system_prompt=content,
            version=version_match.group(1),
            user_template=text_blocks[0].strip(),
            comment_template=text_blocks[1].strip(),
        )

    def render_user(self, normalized: dict[str, Any]) -> str:
        """Render the file-defined user and comment templates."""

        raw_comments = cast(list[dict[str, Any]], normalized["comments"])
        comments = sorted(
            raw_comments,
            key=lambda comment: int(comment["score"]),
            reverse=True,
        )
        comment_blocks = [
            self._substitute(
                self.comment_template,
                {
                    "id": str(comment["id"]),
                    "author": self._optional_value(comment["author"]),
                    "score": str(comment["score"]),
                    "depth": str(comment.get("depth", 0)),
                    "body": str(comment["body"]),
                },
            )
            for comment in comments
        ]
        return self._substitute(
            self.user_template,
            {
                "title": str(normalized["title"]),
                "content": str(normalized["content"]),
                "comments_block": "\n\n".join(comment_blocks),
            },
        )

    @staticmethod
    def _substitute(template: str, values: dict[str, str]) -> str:
        rendered = template
        for name, value in values.items():
            rendered = rendered.replace(f"{{{{{name}}}}}", value)
        if re.search(r"\{\{[^{}]+\}\}", rendered):
            raise PromptContractError("prompt template contains unresolved fields")
        return rendered

    @staticmethod
    def _optional_value(value: object | None) -> str:
        return "null" if value is None else str(value)
