"""Wiki tools — search, read, list wiki pages for the AI agent."""

import json

from fava_ai.tools.base import BaseTool, ToolResult
from fava_ai.knowledge.wiki import WikiManager


class WikiSearchTool(BaseTool):
    def __init__(self, wiki: WikiManager):
        self._wiki = wiki

    @property
    def name(self) -> str:
        return "wiki_search"

    @property
    def description(self) -> str:
        return "Search the knowledge base wiki pages by keyword. Returns matching page paths with titles and snippets."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query string",
                },
            },
            "required": ["query"],
        }

    def execute(self, query: str) -> ToolResult:
        results = self._wiki.search(query)
        return ToolResult(
            content=json.dumps(results, indent=2, ensure_ascii=False),
            metadata={"query": query, "count": len(results)},
        )


class WikiReadTool(BaseTool):
    def __init__(self, wiki: WikiManager):
        self._wiki = wiki

    @property
    def name(self) -> str:
        return "wiki_read"

    @property
    def description(self) -> str:
        return "Read a specific wiki page by its relative path (e.g. 'accounts/Expenses-Food.md' or 'overview.md')."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the wiki page",
                },
            },
            "required": ["path"],
        }

    def execute(self, path: str) -> ToolResult:
        if not self._wiki.exists(path):
            return ToolResult(
                content=json.dumps({"error": f"Page not found: {path}"}),
                metadata={"path": path, "found": False},
            )
        page = self._wiki.read(path)
        return ToolResult(
            content=page.to_text(),
            metadata={"path": path, "title": page.metadata.get("title", ""), "type": page.metadata.get("type", "")},
        )


class WikiListTool(BaseTool):
    def __init__(self, wiki: WikiManager):
        self._wiki = wiki

    @property
    def name(self) -> str:
        return "wiki_list"

    @property
    def description(self) -> str:
        return "List wiki pages, optionally filtered by type prefix (e.g. 'accounts', 'merchants', 'recurring')."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "prefix": {
                    "type": "string",
                    "description": "Optional directory prefix to filter (e.g. 'accounts', 'merchants')",
                },
            },
        }

    def execute(self, prefix: str = "") -> ToolResult:
        pages = self._wiki.list_pages(prefix)
        return ToolResult(
            content=json.dumps(pages, indent=2, ensure_ascii=False),
            metadata={"prefix": prefix, "count": len(pages)},
        )


def register_wiki_tools(registry, wiki: WikiManager):
    registry.register(WikiSearchTool(wiki))
    registry.register(WikiReadTool(wiki))
    registry.register(WikiListTool(wiki))
