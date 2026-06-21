"""PromptRegistry — discover, load, search prompts."""

import yaml
from pathlib import Path


class PromptRegistry:
    def __init__(self, config_dir: Path | None = None):
        self._prompts: dict[str, dict] = {}
        self._config_dir = Path(config_dir) if config_dir else None

        self._load_builtin_prompts()
        if self._config_dir:
            self._load_user_prompts()

    def _load_builtin_prompts(self):
        from fava_ai.prompts.builtin.default import DEFAULT_PROMPT
        from fava_ai.prompts.builtin.monthly_review import MONTHLY_REVIEW_PROMPT
        from fava_ai.prompts.builtin.investment_review import INVESTMENT_REVIEW_PROMPT

        self._prompts["default"] = {
            "id": "default",
            "name": "Default Assistant",
            "version": "1.0",
            "description": "General ledger analysis and Q&A",
            "category": "general",
            "content": DEFAULT_PROMPT,
            "enabled": True,
        }
        self._prompts["monthly_review"] = {
            "id": "monthly_review",
            "name": "Monthly Review",
            "version": "1.0",
            "description": "Monthly spending review and budget analysis",
            "category": "review",
            "content": MONTHLY_REVIEW_PROMPT,
            "enabled": True,
        }
        self._prompts["investment_review"] = {
            "id": "investment_review",
            "name": "Investment Review",
            "version": "1.0",
            "description": "Portfolio performance and allocation analysis",
            "category": "review",
            "content": INVESTMENT_REVIEW_PROMPT,
            "enabled": True,
        }

    def _load_user_prompts(self):
        prompts_dir = self._config_dir / "prompts"
        if not prompts_dir.exists():
            return
        for yaml_file in prompts_dir.glob("*.yaml"):
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f) or {}
                if not data.get("name"):
                    data["name"] = yaml_file.stem
                data["id"] = yaml_file.stem
                data["file_path"] = str(yaml_file)
                data["enabled"] = data.get("enabled", True)
                data["category"] = data.get("category", "user")
                self._prompts[data["id"]] = data
            except Exception:
                continue

    def get(self, name: str) -> dict | None:
        return self._prompts.get(name)

    def list_prompts(self) -> list[dict]:
        result = []
        for p in self._prompts.values():
            result.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "version": p.get("version"),
                "description": p.get("description"),
                "category": p.get("category"),
                "enabled": p.get("enabled", True),
            })
        return result

    def search(self, query: str) -> list[dict]:
        q = query.lower()
        results = []
        for p in self._prompts.values():
            content = p.get("content", "")
            if (q in p.get("name", "").lower() or
                q in p.get("description", "").lower() or
                q in content.lower()[:500]):
                results.append(p.get("id"))
        return [self._prompts[r] for r in results]

    def get_system_prompt(self, prompt_id: str = "default") -> str:
        prompt = self._prompts.get(prompt_id, self._prompts.get("default", {}))
        return prompt.get("content", "")
