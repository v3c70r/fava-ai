"""Fava AI Agent Platform — AI assistant for Beancount/Fava."""
# mypy: disable-error-code="arg-type"

import json
import logging
from pathlib import Path
from typing import Any

from fava.ext import FavaExtensionBase, extension_endpoint
from fava_ai._version import __version__
from fava_ai.agent.errors import AgentError
from flask import Response, jsonify, request, stream_with_context

__all__ = ["FavaAI", "__version__"]

logger = logging.getLogger(__name__)


class FavaAI(FavaExtensionBase):
    """Main Fava extension class for the AI Agent Platform."""

    report_title = "AI Assistant"
    has_js_module = True

    def __init__(self, ledger, config):
        super().__init__(ledger, config)
        self.ledger_dir = Path(ledger.beancount_file_path).parent
        self.config_dir = self.ledger_dir / (self.config.get("config_dir", ".fava-ai") if self.config else ".fava-ai")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._config_manager: Any = None
        self._db: Any = None
        self._provider_registry: Any = None
        self._tool_registry: Any = None
        self._wiki_manager: Any = None
        self._knowledge_engine: Any = None
        self._prompt_registry: Any = None
        self._agent_runtime: Any = None

        self._init_components()

    def _init_components(self):
        from fava_ai.config import ConfigManager
        from fava_ai.knowledge.engine import KnowledgeEngine
        from fava_ai.knowledge.wiki import WikiManager
        from fava_ai.models.registry import ProviderRegistry
        from fava_ai.storage.database import Database
        from fava_ai.tools.builtin.ledger import register_ledger_tools
        from fava_ai.tools.builtin.wiki import register_wiki_tools
        from fava_ai.tools.registry import ToolRegistry

        self._config_manager = ConfigManager(
            self.ledger, self.config or {}, self.config_dir
        )

        db_path = self.config_dir / "conversations.db"
        self._db = Database(db_path)
        self._db.initialize()

        self._provider_registry = ProviderRegistry(self._config_manager)

        wiki_dir = self.config_dir / "wiki"
        self._wiki_manager = WikiManager(wiki_dir)

        knowledge_config = self._config_manager.get_knowledge_config()
        self._knowledge_engine = KnowledgeEngine(
            self._wiki_manager, knowledge_config
        )

        self._tool_registry = ToolRegistry()
        register_ledger_tools(self._tool_registry, self.ledger)
        register_wiki_tools(self._tool_registry, self._wiki_manager)

        from fava_ai.tools.builtin.dashboard import register_dashboard_tools
        register_dashboard_tools(self._tool_registry, self.ledger)

        from fava_ai.documents.embeddings import EmbeddingClient
        from fava_ai.documents.store import DocumentStore
        from fava_ai.tools.builtin.documents import register_document_tools

        documents_config = self._config_manager.get_documents_config()
        self._document_store = DocumentStore(
            self.config_dir / "documents.db",
            self.config_dir / "documents",
            embedder=EmbeddingClient.from_config(documents_config.get("embedding")),
        )
        self._document_store.initialize()
        # Registered regardless of folder indexing so chat uploads work.
        register_document_tools(
            self._tool_registry, self._document_store, self.ledger,
            self._config_manager.get_tools_config(),
        )

        from fava_ai.tools.loader import load_external_tools
        tools_config = self._config_manager.get_tools_config()
        if tools_config.get("external_enabled", False):
            external_tools_dir = self.config_dir / "tools"
            for ext_tool in load_external_tools(external_tools_dir):
                self._tool_registry.register(ext_tool)

        from fava_ai.prompts.registry import PromptRegistry
        self._prompt_registry = PromptRegistry(self.config_dir)

        from fava_ai.agent.context import ContextBuilder
        from fava_ai.agent.runtime import AgentRuntime

        context_builder = ContextBuilder(
            self.ledger, self._tool_registry, self._wiki_manager,
            self._prompt_registry,
        )

        self._agent_runtime = AgentRuntime(
            provider_registry=self._provider_registry,
            tool_registry=self._tool_registry,
            context_builder=context_builder,
            config=self._config_manager.get_agent_config(),
        )

    @property
    def config_manager(self):
        return self._config_manager

    @property
    def db(self):
        return self._db

    @property
    def document_store(self):
        return self._document_store

    @property
    def provider_registry(self):
        return self._provider_registry

    @property
    def tool_registry(self):
        return self._tool_registry

    @property
    def agent_runtime(self):
        return self._agent_runtime

    # ── API Endpoints ──────────────────────────────────────────────

    def _persist_exchange(self, result, conversation_id, provider_name, user_message, model=None):
        """Persist new messages and provenance for a completed agent run.

        Returns the id of the final assistant message (or None). Shared by the
        blocking and streaming chat endpoints so both keep history and traces.
        """
        if not self._db:
            return None
        from fava_ai.storage.conversations import (
            create_conversation,
            save_message,
            update_title,
        )
        from fava_ai.storage.traces import save_trace

        conv_id = result["conversation_id"]
        if not conversation_id:
            provider = provider_name or (
                self.config.get("provider", "") if self.config else ""
            )
            try:
                create_conversation(
                    self._db, id=conv_id, title=user_message[:80],
                    provider=provider, model=model or "",
                )
            except Exception:
                # Conversation already exists (retry / duplicate id): continue.
                logger.debug("Conversation %s already exists", conv_id)

        assistant_msg_id = None
        for msg in result.get("new_messages", result["messages"]):
            if msg.role == "system":
                continue
            token_count = None
            if msg.content:
                from fava_ai.agent.tokens import count_tokens
                token_count = count_tokens([msg])
            mid = save_message(self._db, conv_id, msg, token_count=token_count)
            if msg.role == "assistant" and not msg.tool_calls:
                assistant_msg_id = mid

        if assistant_msg_id:
            steps = result.get("provenance", {}).get("steps", [])
            if steps:
                save_trace(self._db, assistant_msg_id, steps)

        title = user_message[:80] if len(user_message) > 80 else user_message
        try:
            update_title(self._db, conv_id, title)
        except Exception:
            logger.debug("Could not update title for %s", conv_id)
        return assistant_msg_id

    def _persist_aborted(self, exc):
        """Persist whatever the runtime produced before a hard error.

        Prevents an interrupted run from leaving no trace in the history.
        """
        if not self._db:
            return None
        partial = getattr(exc, "partial_messages", None)
        conv_id = getattr(exc, "conversation_id", None)
        if not partial or not conv_id:
            return None

        from fava_ai.models.base import Message
        from fava_ai.storage.conversations import create_conversation, save_message

        first_user = next(
            (m.content for m in partial if m.role == "user" and m.content), ""
        )
        try:
            create_conversation(
                self._db, id=conv_id, title=(first_user or "Conversation")[:80],
                provider="", model="",
            )
        except Exception:
            logger.debug("Conversation %s already exists", conv_id)

        for msg in partial:
            if msg.role == "system":
                continue
            save_message(self._db, conv_id, msg)
        save_message(self._db, conv_id, Message(
            role="assistant", content=f"(Interrupted before completion: {exc})",
        ))
        return conv_id

    @extension_endpoint("chat", methods=["POST"])
    def api_chat(self):
        try:
            data = request.get_json()
            if not data or "message" not in data:
                return jsonify({"error": "message is required"}), 400

            user_message = data["message"]
            conversation_id = data.get("conversation_id")

            messages = None
            if conversation_id and self._db:
                from fava_ai.storage.conversations import load_messages
                messages = load_messages(self._db, conversation_id)

            provider_name = data.get("provider")
            model = data.get("model")
            prompt_id = data.get("prompt_id")
            file_ids = data.get("file_ids") or []
            extra_context = self._attachment_context(file_ids, conversation_id)

            result = self._agent_runtime.run(
                user_message=user_message,
                conversation_id=conversation_id,
                messages=messages,
                provider_name=provider_name,
                model=model,
                prompt_id=prompt_id,
                extra_context=extra_context,
            )

            conv_id = result["conversation_id"]
            message_id = self._persist_exchange(
                result, conversation_id, provider_name, user_message, model
            )
            if file_ids and self._document_store:
                self._document_store.assign_conversation(file_ids, conv_id)

            return jsonify({
                "conversation_id": conv_id,
                "message_id": message_id,
                "content": result["content"],
                "usage": result.get("usage"),
                "provenance": result.get("provenance", {}),
                "provenance_summary": result.get("provenance_summary", ""),
                "tool_call_count": result.get("tool_call_count", 0),
                "partial": result.get("partial", False),
                "stop_reason": result.get("stop_reason"),
            })

        except AgentError as e:
            self._persist_aborted(e)
            return jsonify({
                "error": str(e), "error_type": type(e).__name__,
                "conversation_id": getattr(e, "conversation_id", None),
            }), e.http_status
        except Exception as e:
            logger.exception("chat endpoint failed")
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("chat_stream", methods=["POST"])
    def api_chat_stream(self):
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "message is required"}), 400

        def generate():
            try:
                user_message = data["message"]
                conversation_id = data.get("conversation_id")
                messages = None
                if conversation_id and self._db:
                    from fava_ai.storage.conversations import load_messages
                    messages = load_messages(self._db, conversation_id)
                provider_name = data.get("provider")
                model = data.get("model")
                prompt_id = data.get("prompt_id")
                file_ids = data.get("file_ids") or []
                extra_context = self._attachment_context(file_ids, conversation_id)

                for event in self._agent_runtime.run_stream(
                    user_message=user_message, conversation_id=conversation_id,
                    messages=messages, provider_name=provider_name,
                    model=model, prompt_id=prompt_id,
                    extra_context=extra_context,
                ):
                    if event["type"] == "done":
                        result = event["result"]
                        message_id = self._persist_exchange(
                            result, conversation_id, provider_name,
                            user_message, model,
                        )
                        if file_ids and self._document_store:
                            self._document_store.assign_conversation(
                                file_ids, result["conversation_id"]
                            )
                        payload = {
                            "type": "done",
                            "conversation_id": result["conversation_id"],
                            "message_id": message_id,
                            "content": result["content"],
                            "provenance_summary": result["provenance_summary"],
                            "partial": result.get("partial", False),
                            "stop_reason": result.get("stop_reason"),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
                    else:
                        yield f"data: {json.dumps(event)}\n\n"

            except AgentError as e:
                self._persist_aborted(e)
                yield f"data: {json.dumps({'type': 'error', 'error': str(e), 'error_type': type(e).__name__})}\n\n"
            except Exception as e:
                logger.exception("chat_stream endpoint failed")
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive"},
        )

    @extension_endpoint("conversations", methods=["GET"])
    def api_conversations(self):
        if not self._db:
            return jsonify([])
        conv_id = request.args.get("id")
        from fava_ai.storage.conversations import get_conversation, list_conversations
        if conv_id:
            limit = request.args.get("limit", type=int)
            offset = request.args.get("offset", type=int) or 0
            conv = get_conversation(
                self._db, conv_id, message_limit=limit, message_offset=offset
            )
            if not conv:
                return jsonify({"error": "Not found"}), 404
            return jsonify(conv)
        return jsonify(list_conversations(self._db))

    @extension_endpoint("conversations", methods=["PUT"])
    def api_update_conversation(self):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        data = request.get_json() or {}
        conv_id = request.args.get("id") or data.get("id")
        if not conv_id:
            return jsonify({"error": "?id= required"}), 400
        title = data.get("title")
        if title is None or not isinstance(title, str):
            return jsonify({"error": "title (string) is required"}), 400

        from fava_ai.storage.conversations import get_conversation, update_title
        if not get_conversation(self._db, conv_id):
            return jsonify({"error": "Not found"}), 404
        update_title(self._db, conv_id, title)
        return jsonify(get_conversation(self._db, conv_id))

    @extension_endpoint("conversations", methods=["POST"])
    def api_create_conversation(self):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        data = request.get_json() or {}
        from fava_ai.storage.conversations import create_conversation, get_conversation
        conv_id = data.get("id")
        if conv_id and get_conversation(self._db, conv_id):
            return jsonify({"error": f"Conversation already exists: {conv_id}"}), 409
        conv = create_conversation(
            self._db,
            title=data.get("title", ""),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
            id=conv_id,
        )
        return jsonify(conv), 201

    @extension_endpoint("conversations", methods=["DELETE"])
    def api_delete_conversation(self):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        conv_id = request.args.get("id")
        if not conv_id:
            return jsonify({"error": "?id= required"}), 400
        from fava_ai.storage.conversations import delete_conversation as delete_conv
        from fava_ai.storage.conversations import get_conversation as get_conv
        existing = get_conv(self._db, conv_id)
        if not existing:
            return jsonify({"error": "Not found"}), 404
        delete_conv(self._db, conv_id)
        return jsonify({"deleted": True})

    @extension_endpoint("tools", methods=["GET"])
    def api_tools(self):
        name = request.args.get("name")
        if name:
            tool = self._tool_registry.get(name)
            if not tool:
                return jsonify({"error": f"Tool not found: {name}"}), 404
            return jsonify({
                "name": tool.name, "description": tool.description,
                "parameters": tool.parameters, "permission": tool.permission,
            })
        tools = []
        for tool in self._tool_registry.list_tools():
            tools.append({
                "name": tool.name, "description": tool.description,
                "parameters": tool.parameters, "permission": tool.permission,
            })
        return jsonify(tools)

    @extension_endpoint("config", methods=["GET"])
    def api_get_config(self):
        try:
            provider_config = self._config_manager.get_provider_config()
            agent_config = self._config_manager.get_agent_config()
            knowledge_config = self._config_manager.get_knowledge_config()
            tools_config = self._config_manager.get_tools_config()
            documents_config = self._config_manager.get_documents_config()
            safe_documents = dict(documents_config)
            embedding = dict(safe_documents.get("embedding") or {})
            if "api_key" in embedding:
                embedding["api_key"] = "***" if embedding["api_key"] else ""
            safe_documents["embedding"] = embedding
            safe_provider_config = {}
            for name, cfg in provider_config.items():
                safe_cfg = dict(cfg)
                if "api_key" in safe_cfg:
                    safe_cfg["api_key"] = "***" if safe_cfg["api_key"] else ""
                safe_provider_config[name] = safe_cfg
            return jsonify({
                "providers": safe_provider_config, "agent": agent_config,
                "knowledge": knowledge_config, "tools": tools_config,
                "documents": safe_documents,
                "config_dir": str(self._config_manager.config_dir),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("config", methods=["PUT"])
    def api_update_config(self):
        import yaml
        data = request.get_json()
        if not isinstance(data, dict) or not data:
            return jsonify({"error": "Expected a JSON object"}), 400

        from fava_ai.config import validate_config
        errors = validate_config(data)
        if errors:
            return jsonify({"error": "Invalid config", "details": errors}), 400

        # Preserve masked secrets: a value of "***" means "leave unchanged".
        # Read from the raw on-disk config so `${ENV_VAR}` references survive.
        raw_providers = self._config_manager.raw_provider_config()
        providers = data.get("providers")
        if isinstance(providers, dict):
            for name, cfg in providers.items():
                if not isinstance(cfg, dict):
                    continue
                if cfg.get("api_key") == "***":
                    raw_key = (raw_providers.get(name) or {}).get("api_key")
                    if raw_key:
                        cfg["api_key"] = raw_key
                    else:
                        cfg.pop("api_key", None)

        # Same for the optional document-embedding key.
        documents = data.get("documents")
        if isinstance(documents, dict):
            embedding = documents.get("embedding")
            if isinstance(embedding, dict) and embedding.get("api_key") == "***":
                raw_docs = self._config_manager._raw_config.get("documents") or {}
                raw_embedding = raw_docs.get("embedding") or {} if isinstance(raw_docs, dict) else {}
                raw_key = raw_embedding.get("api_key") if isinstance(raw_embedding, dict) else None
                if raw_key:
                    embedding["api_key"] = raw_key
                else:
                    embedding.pop("api_key", None)

        config_path = self._config_manager.config_dir / "config.yaml"
        try:
            with open(config_path, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            self._config_manager._load_yaml()
            return jsonify({"saved": True, "path": str(config_path)})
        except Exception as e:
            logger.exception("failed to write config")
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("providers", methods=["GET"])
    def api_providers(self):
        return jsonify(self._provider_registry.list_providers())

    @extension_endpoint("providers_test", methods=["POST"])
    def api_test_provider(self):
        data = request.get_json() or {}
        provider_name = data.get("provider", "")
        if provider_name:
            provider = self._provider_registry.get(provider_name)
            if not provider:
                return jsonify({
                    "connected": False,
                    "error": f"Unknown provider: {provider_name}",
                }), 404
        else:
            provider = self._provider_registry.get_default()
        if not provider:
            return jsonify({"connected": False, "error": "No provider configured"})
        try:
            connected = provider.test_connection()
            # Key the cache by the configured alias (not the provider type),
            # so list_providers() sees the fresh result.
            name = (
                provider_name
                or self._provider_registry.alias_of(provider)
                or getattr(provider, "provider_name", "")
            )
            self._provider_registry.set_connection(name, connected)
            return jsonify({"connected": connected})
        except Exception as e:
            return jsonify({"connected": False, "error": str(e)})

    @extension_endpoint("providers_models", methods=["GET"])
    def api_list_models(self):
        name = request.args.get("name", "")
        provider = self._provider_registry.get(name)
        if not provider:
            return jsonify({"error": f"Provider not found: {name}"}), 404
        try:
            models = provider.list_models()
            return jsonify({"provider": name, "models": models})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("knowledge", methods=["GET"])
    def api_knowledge(self):
        if not self._wiki_manager:
            return jsonify({"enabled": False})
        action = request.args.get("action", "status")
        if action == "pages":
            prefix = request.args.get("prefix", "")
            path = request.args.get("path", "")
            if path:
                if not self._wiki_manager.exists(path):
                    return jsonify({"error": "Not found"}), 404
                page = self._wiki_manager.read(path)
                return jsonify({
                    "path": path, "title": page.metadata.get("title", ""),
                    "type": page.metadata.get("type", ""),
                    "metadata": page.metadata, "content": page.content,
                })
            return jsonify(self._wiki_manager.list_pages(prefix))
        # status
        wiki_dir = self._wiki_manager.wiki_dir
        pages = sum(1 for _ in wiki_dir.rglob("*.md")) if wiki_dir.exists() else 0
        return jsonify({
            "enabled": True, "wiki_dir": str(wiki_dir),
            "pages": pages, "has_overview": self._wiki_manager.exists("overview.md"),
        })

    @extension_endpoint("prompts", methods=["GET"])
    def api_prompts(self):
        if not self._prompt_registry:
            return jsonify([])
        name = request.args.get("name")
        if name:
            prompt = self._prompt_registry.get(name)
            if not prompt:
                return jsonify({"error": f"Prompt not found: {name}"}), 404
            return jsonify({
                "id": prompt.get("id"), "name": prompt.get("name"),
                "description": prompt.get("description"),
                "category": prompt.get("category"),
                "content": prompt.get("content"),
            })
        return jsonify(self._prompt_registry.list_prompts())

    # ── documents ─────────────────────────────────────────────────

    @property
    def _documents_config(self) -> dict:
        # Read live so config edits apply without a restart.
        return self._config_manager.get_documents_config()

    def _refresh_embedder(self):
        from fava_ai.documents.embeddings import EmbeddingClient

        if self._document_store is not None:
            self._document_store.set_embedder(
                EmbeddingClient.from_config(self._documents_config.get("embedding"))
            )

    def _configured_document_folders(self) -> list[str]:
        """User-configured folders plus Fava's documents folder (no uploads)."""
        folders = [
            str(f) for f in self._documents_config.get("folders", []) if f
        ]
        try:
            fava_documents = getattr(self.ledger.fava_options, "documents", None)
            if fava_documents:
                folders.append(str(Path(self.ledger_dir) / fava_documents))
        except Exception:
            logger.debug("Could not resolve Fava documents folder")
        return self._dedupe(folders)

    def _document_folders(self) -> list[str]:
        """Every folder to scan, including the chat-upload directory."""
        folders = list(self._configured_document_folders())
        if self._document_store and self._document_store.documents_dir:
            folders.append(str(self._document_store.documents_dir))
        return self._dedupe(folders)

    @staticmethod
    def _dedupe(folders: list[str]) -> list[str]:
        seen, unique = set(), []
        for folder in folders:
            if folder not in seen:
                seen.add(folder)
                unique.append(folder)
        return unique

    def _attachment_context(self, file_ids, conversation_id=None) -> str:
        """System-prompt note describing attached documents for this turn.

        Small documents are inlined; larger ones are referenced so the agent
        can pull them with the ``read_document`` tool.
        """
        if not self._document_store:
            return ""
        ids = list(file_ids or [])
        if not ids and conversation_id:
            ids = [
                d["id"] for d
                in self._document_store.list_documents(conversation_id=conversation_id)
            ]
        if not ids:
            return ""

        lines = [
            "## Attached documents",
            "The user attached these files to the conversation:",
        ]
        for doc_id in ids[:10]:
            doc = self._document_store.get(doc_id)
            if not doc:
                continue
            line = f"- {doc['name']} (document_id: {doc_id}, status: {doc['status']})"
            if doc["status"] == "indexed" and (doc.get("chars") or 0) <= 2000:
                text = self._document_store.read(doc_id, max_chars=2000).get("text", "")
                line += f"\n```\n{text}\n```"
            elif doc["status"] == "indexed":
                line += " — call read_document to read its contents"
            else:
                line += f" — {doc.get('error') or 'contents not readable'}"
            lines.append(line)
        lines.append("")
        lines.append(
            "Use these documents as context and cite the file name when you use one."
        )
        return "\n".join(lines)

    @extension_endpoint("documents", methods=["GET"])
    def api_documents(self):
        if not self._document_store:
            return jsonify({"enabled": False})
        doc_id = request.args.get("id")
        if doc_id:
            doc = self._document_store.read(doc_id)
            if not doc:
                return jsonify({"error": "Not found"}), 404
            return jsonify(doc)
        conversation_id = request.args.get("conversation_id")
        if conversation_id:
            return jsonify(self._document_store.list_documents(conversation_id=conversation_id))
        if request.args.get("all"):
            limit = request.args.get("limit", type=int) or 200
            return jsonify(self._document_store.list_documents(limit=limit))
        status = self._document_store.status()
        status["enabled"] = bool(self._documents_config.get("enabled", False))
        status["folders"] = self._document_folders()
        status["embedding_configured"] = bool(
            (self._documents_config.get("embedding") or {}).get("base_url")
        )
        return jsonify(status)

    @extension_endpoint("documents_upload", methods=["POST"])
    def api_documents_upload(self):
        if not self._document_store:
            return jsonify({"error": "Documents are not available"}), 500
        if "file" not in request.files:
            return jsonify({"error": "file is required"}), 400

        upload = request.files["file"]
        from werkzeug.utils import secure_filename

        raw_name = upload.filename or ""
        if isinstance(raw_name, bytes):  # some clients send a bytes filename
            raw_name = raw_name.decode("utf-8", "replace")
        name = secure_filename(raw_name)
        if not name:
            return jsonify({"error": "A filename is required"}), 400

        max_bytes = int(self._documents_config.get("max_file_mb", 25)) * 1024 * 1024
        if request.content_length and request.content_length > max_bytes + 4096:
            return jsonify({
                "error": f"File exceeds the {self._documents_config.get('max_file_mb', 25)} MB limit"
            }), 413

        conversation_id = request.form.get("conversation_id") or None
        target_dir = self._document_store.documents_dir / (
            conversation_id or "uploads"
        )
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / name
        upload.save(target)

        try:
            doc = self._document_store.import_path(
                target,
                conversation_id=conversation_id,
                max_pages=int(self._documents_config.get("max_pages", 50)),
                max_chars=int(self._documents_config.get("max_chars_per_doc", 200000)),
            )
        except Exception as e:
            logger.exception("Document upload failed")
            return jsonify({"error": str(e)}), 500

        doc["url"] = f"documents?id={doc['id']}"
        return jsonify(doc), 201

    @extension_endpoint("documents_index", methods=["POST"])
    def api_documents_index(self):
        if not self._document_store:
            return jsonify({"error": "Documents are not available"}), 500
        if not self._configured_document_folders():
            return jsonify({
                "error": "No document folders configured",
                "hint": "Set documents.folders or Fava's documents folder option",
            }), 400
        folders = self._document_folders()
        try:
            self._refresh_embedder()
            stats = self._document_store.scan_folders(
                folders,
                max_files=2000,
            )
            stats["embedding"] = self._document_store.embed_pending()
        except Exception as e:
            logger.exception("Document indexing failed")
            return jsonify({"error": str(e)}), 500
        stats["folders"] = folders
        stats["status"] = self._document_store.status()
        return jsonify(stats)

    @extension_endpoint("documents_embed", methods=["POST"])
    def api_documents_embed(self):
        """Embed any chunks that are missing vectors (and report status)."""
        if not self._document_store:
            return jsonify({"error": "Documents are not available"}), 500
        self._refresh_embedder()
        if not self._document_store:
            return jsonify({"error": "Documents are not available"}), 500
        if not self._document_store.embedder or not self._document_store.embedder.configured:
            return jsonify({
                "error": "Embedding not configured",
                "hint": "Set documents.embedding.base_url and .model",
            }), 400
        result = self._document_store.embed_pending(
            max_chunks=request.args.get("limit", type=int) or 2000
        )
        result["status"] = self._document_store.embedding_status()
        return jsonify(result)

    @extension_endpoint("documents_embed_test", methods=["POST"])
    def api_documents_embed_test(self):
        embedder = self._document_store.embedder if self._document_store else None
        if not embedder or not embedder.configured:
            return jsonify({"connected": False, "error": "Embedding not configured"})
        connected, detail = embedder.test_connection()
        return jsonify({"connected": connected, "detail": detail})

    @extension_endpoint("documents", methods=["DELETE"])
    def api_documents_delete(self):
        if not self._document_store:
            return jsonify({"error": "Documents are not available"}), 500
        doc_id = request.args.get("id")
        if not doc_id:
            return jsonify({"error": "?id= required"}), 400
        remove_file = request.args.get("remove_file") in ("1", "true", "yes")
        if not self._document_store.delete(doc_id, remove_file=remove_file):
            return jsonify({"error": "Not found"}), 404
        return jsonify({"deleted": True, "removed_file": remove_file})

    @extension_endpoint("traces", methods=["GET"])
    def api_traces(self):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        message_id = request.args.get("message_id", "")
        if not message_id:
            return jsonify({"error": "?message_id= required"}), 400
        from fava_ai.storage.traces import get_traces
        return jsonify(get_traces(self._db, message_id))

    def after_load_file(self):
        """Fires on ledger load/reload. Rebuild knowledge base if changed."""
        knowledge_config = self._config_manager.get_knowledge_config()
        if not knowledge_config.get("auto_extract", True):
            return
        if self._knowledge_engine and self._knowledge_engine.needs_rebuild(
            self.ledger.all_entries
        ):
            try:
                self._knowledge_engine.extract_all(
                    self.ledger.all_entries, self.ledger.options
                )
            except Exception:
                logger.exception(
                    "Knowledge base extraction failed; continuing without rebuild"
                )
