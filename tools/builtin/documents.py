"""Document tools — search, read and file documents/vouchers.

Search and read mirror the wiki tools so the agent already knows how to use
them. Filing is **read-only by default**: it returns a paste-ready beancount
snippet. Opt in to appending it to a dedicated file with
``tools.allow_ledger_writes``.
"""

from __future__ import annotations

import json
from pathlib import Path

from fava_ai.tools.base import BaseTool, ToolResult


def _rel_posix(path: str, base: str | None) -> str:
    """Path relative to the ledger dir when possible, always forward slashes."""
    target = Path(path)
    if base:
        try:
            return target.resolve().relative_to(Path(base).resolve()).as_posix()
        except ValueError:
            pass
    return target.as_posix()


class SearchDocumentsTool(BaseTool):
    def __init__(self, store, default_limit: int = 5):
        self._store = store
        self._default_limit = default_limit

    @property
    def name(self) -> str:
        return "search_documents"

    @property
    def description(self) -> str:
        return (
            "Full-text search over the user's documents and vouchers (receipts, "
            "statements, contracts, payslips) that were indexed from their "
            "document folders or uploaded in chat. Returns matching documents "
            "with a highlighted snippet, page number and document_id. Use "
            "`read_document` to read more of a hit."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "limit": {
                    "type": "integer",
                    "description": f"Maximum results (default {self._default_limit})",
                },
            },
            "required": ["query"],
        }

    def execute(self, query: str, limit: int = 0) -> ToolResult:
        limit = limit or self._default_limit
        try:
            results = self._store.search(query, limit=max(1, int(limit)))
        except Exception as e:  # noqa: BLE001
            return ToolResult(
                content=f"Document search failed: {e}",
                metadata={"error": str(e)},
            )
        return ToolResult(
            content=json.dumps({"results": results, "count": len(results)},
                               indent=2, ensure_ascii=False),
            metadata={"count": len(results)},
        )


class ReadDocumentTool(BaseTool):
    def __init__(self, store, max_chars: int = 20_000):
        self._store = store
        self._max_chars = max_chars

    @property
    def name(self) -> str:
        return "read_document"

    @property
    def description(self) -> str:
        return (
            "Read a document by its document_id (from search_documents or a chat "
            "upload). Returns the extracted text, truncated to fit the context "
            "budget. Pass `chunk` to read a single chunk by its index."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "chunk": {
                    "type": "integer",
                    "description": "Optional chunk index for a targeted read",
                },
            },
            "required": ["document_id"],
        }

    def execute(self, document_id: str, chunk: int | None = None) -> ToolResult:
        if chunk is not None:
            try:
                chunk = int(chunk)  # models often send "0" as a string
            except (TypeError, ValueError):
                chunk = None
        doc = self._store.read(document_id, chunk=chunk, max_chars=self._max_chars)
        if doc is None:
            message = f"Document not found: {document_id}"
            return ToolResult(
                content=json.dumps({"error": message}),
                metadata={"error": message},
            )
        return ToolResult(
            content=json.dumps(doc, indent=2, ensure_ascii=False),
            metadata={"document_id": document_id, "name": doc.get("name", "")},
        )


class FileDocumentTool(BaseTool):
    """Compose a beancount entry that links a document to a transaction."""

    def __init__(self, store, ledger_dir: str | None = None,
                 allow_writes: bool = False, writes_file: str = "documents.beancount",
                 main_ledger_path: str | None = None):
        self._store = store
        self._ledger_dir = ledger_dir
        self._allow_writes = allow_writes
        # Only a plain filename inside the ledger directory is accepted, so a
        # stray path cannot escape or point at the main journal.
        self._writes_file = Path(writes_file or "documents.beancount").name
        self._main_ledger_path = main_ledger_path

    @property
    def name(self) -> str:
        return "file_document"

    @property
    def description(self) -> str:
        return (
            "Produce a beancount entry that books a transaction and links the "
            "given document to it (transaction with `attachment:` metadata plus "
            "a `Document` entry). Returns a paste-ready snippet for the user to "
            "review; nothing is written to the ledger unless ledger writes are "
            "explicitly enabled in the config."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "document_id": {"type": "string"},
                "date": {"type": "string", "description": "YYYY-MM-DD"},
                "payee": {"type": "string"},
                "narration": {"type": "string"},
                "postings": {
                    "type": "array",
                    "description": "Postings, e.g. [{\"account\": \"Expenses:Food\", \"amount\": \"13.50 CAD\"}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "account": {"type": "string"},
                            "amount": {"type": "string"},
                        },
                        "required": ["account"],
                    },
                },
                "link_account": {
                    "type": "string",
                    "description": "Account for the Document entry (defaults to the first posting account)",
                },
            },
            "required": ["document_id", "date", "postings"],
        }

    @property
    def permission(self) -> str:
        return "write" if self._allow_writes else "readonly"

    def execute(self, document_id: str, date: str, postings: list,
                payee: str = "", narration: str = "",
                link_account: str = "") -> ToolResult:
        doc = self._store.get(document_id)
        if doc is None:
            message = f"Document not found: {document_id}"
            return ToolResult(
                content=json.dumps({"error": message}),
                metadata={"error": message},
            )
        if not postings:
            message = "At least one posting is required"
            return ToolResult(
                content=json.dumps({"error": message}),
                metadata={"error": message},
            )

        path = _rel_posix(doc["source_path"], self._ledger_dir)
        account = link_account or postings[0].get("account", "")
        snippet = self._render_snippet(date, payee, narration, postings, path, account)

        wrote, write_error = None, None
        if self._allow_writes and self._ledger_dir:
            wrote, write_error = self._append_to_file(snippet)

        payload = {"snippet": snippet, "document_id": document_id,
                   "document_path": path}
        if wrote:
            payload["written_to"] = wrote
        if write_error:
            # The model must never report a successful filing that did not
            # actually land in the ledger.
            payload["write_error"] = write_error
        return ToolResult(
            content=json.dumps(payload, indent=2, ensure_ascii=False),
            metadata={"document_id": document_id, "written_to": wrote,
                      "write_error": write_error},
        )

    @staticmethod
    def _render_snippet(date: str, payee: str, narration: str, postings: list,
                        path: str, account: str) -> str:
        flags = f' "{payee}"' if payee else ""
        narr = f' "{narration}"' if narration else ""
        lines = [f"{date} *{flags}{narr}", f'  attachment: "{path}"']
        width = max((len(p.get("account", "")) for p in postings), default=0)
        for posting in postings:
            acct = posting.get("account", "")
            amount = posting.get("amount")
            lines.append(f"  {acct.ljust(width)}  {amount}" if amount
                         else f"  {acct.ljust(width)}")
        lines.append("")
        lines.append(f'{date} document {account} "{path}"')
        return "\n".join(lines)

    def _append_to_file(self, snippet: str) -> tuple[str | None, str | None]:
        """Append the snippet. Returns (path, error); error is set on failure."""
        ledger_dir = self._ledger_dir
        if not ledger_dir:
            return None, "no ledger directory"
        target = Path(ledger_dir) / self._writes_file
        # Never touch the main journal: the guarantee is "never modifies your
        # beancount files", and only a dedicated included file may be written.
        if self._main_ledger_path and (
            target.resolve() == Path(self._main_ledger_path).resolve()
        ):
            return None, (
                f"refusing to write to the main ledger file; "
                f"set tools.ledger_writes_file to a dedicated file "
                f"(currently {self._writes_file!r})"
            )
        try:
            with open(target, "a", encoding="utf-8") as handle:
                handle.write("\n" + snippet + "\n")
            return str(target), None
        except OSError as e:
            return None, str(e)


def register_document_tools(registry, store, ledger=None, tools_config=None):
    tools_config = tools_config or {}
    ledger_dir = None
    if ledger is not None:
        ledger_dir = str(Path(getattr(ledger, "beancount_file_path", "")).parent)
    registry.register(SearchDocumentsTool(store))
    registry.register(ReadDocumentTool(store))
    registry.register(FileDocumentTool(
        store,
        ledger_dir=ledger_dir,
        allow_writes=bool(tools_config.get("allow_ledger_writes", False)),
        writes_file=tools_config.get("ledger_writes_file", "documents.beancount"),
        main_ledger_path=getattr(ledger, "beancount_file_path", None),
    ))
