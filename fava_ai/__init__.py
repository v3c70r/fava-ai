"""Fava AI Agent Platform — AI assistant for Beancount/Fava."""

import json
import traceback
from pathlib import Path

from flask import request, jsonify, Response, stream_with_context, render_template_string

from fava.ext import FavaExtensionBase, extension_endpoint
from fava_ai._version import __version__
from fava_ai.agent.limits import LimitExceeded


class FavaAI(FavaExtensionBase):
    """Main Fava extension class for the AI Agent Platform."""

    report_title = "AI Assistant"
    has_js_module = True

    def __init__(self, ledger, config):
        super().__init__(ledger, config)
        self.ledger_dir = Path(ledger.beancount_file_path).parent
        self.config_dir = self.ledger_dir / (self.config.get("config_dir", ".fava-ai") if self.config else ".fava-ai")
        self.config_dir.mkdir(parents=True, exist_ok=True)

        self._config_manager = None
        self._db = None
        self._provider_registry = None
        self._tool_registry = None
        self._wiki_manager = None
        self._knowledge_engine = None
        self._prompt_registry = None
        self._agent_runtime = None

        self._init_components()

    def _init_components(self):
        from fava_ai.config import ConfigManager
        from fava_ai.storage.database import Database
        from fava_ai.models.registry import ProviderRegistry
        from fava_ai.tools.registry import ToolRegistry
        from fava_ai.tools.builtin.ledger import register_ledger_tools
        from fava_ai.tools.builtin.wiki import register_wiki_tools
        from fava_ai.knowledge.wiki import WikiManager
        from fava_ai.knowledge.engine import KnowledgeEngine

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

        from fava_ai.tools.loader import load_external_tools
        external_tools_dir = self.config_dir / "tools"
        for ext_tool in load_external_tools(external_tools_dir):
            self._tool_registry.register(ext_tool)

        from fava_ai.prompts.registry import PromptRegistry
        self._prompt_registry = PromptRegistry(self.config_dir)

        from fava_ai.agent.runtime import AgentRuntime
        from fava_ai.agent.context import ContextBuilder

        context_builder = ContextBuilder(
            self.ledger, self._tool_registry, self._wiki_manager
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
    def provider_registry(self):
        return self._provider_registry

    @property
    def tool_registry(self):
        return self._tool_registry

    @property
    def agent_runtime(self):
        return self._agent_runtime

    # ── API Endpoints ──────────────────────────────────────────────

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

            result = self._agent_runtime.run(
                user_message=user_message,
                conversation_id=conversation_id,
                messages=messages,
                provider_name=provider_name,
            )

            conv_id = result["conversation_id"]
            if self._db:
                from fava_ai.storage.conversations import (
                    create_conversation, save_message, update_title,
                )
                if not conversation_id:
                    provider = provider_name or (
                        self.config.get("provider", "") if self.config else ""
                    )
                    create_conversation(
                        self._db, id=conv_id, title=user_message[:80],
                        provider=provider, model=""
                    )

                for msg in result["messages"]:
                    if msg.role != "system":
                        save_message(self._db, conv_id, msg)

                title = user_message[:80] if len(user_message) > 80 else user_message
                try:
                    update_title(self._db, conv_id, title)
                except Exception:
                    pass

            return jsonify({
                "conversation_id": conv_id,
                "content": result["content"],
                "usage": result.get("usage"),
                "provenance": result.get("provenance", {}),
                "provenance_summary": result.get("provenance_summary", ""),
                "tool_call_count": result.get("tool_call_count", 0),
            })

        except LimitExceeded as e:
            return jsonify({"error": f"Limit exceeded: {e}"}), 429
        except Exception as e:
            traceback.print_exc()
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

                result = self._agent_runtime.run(
                    user_message=user_message, conversation_id=conversation_id,
                    messages=messages, provider_name=provider_name,
                )

                yield f"data: {json.dumps({'type': 'content', 'content': result['content'], 'conversation_id': result['conversation_id']})}\n\n"
                for step in result.get("provenance", {}).get("steps", []):
                    if step.get("step_type") == "tool_call":
                        yield f"data: {json.dumps({'type': 'tool_call', 'step': step})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result['conversation_id'], 'usage': result.get('usage'), 'provenance_summary': result.get('provenance_summary', '')})}\n\n"

            except LimitExceeded as e:
                yield f"data: {json.dumps({'type': 'error', 'error': f'Limit exceeded: {e}'})}\n\n"
            except Exception as e:
                traceback.print_exc()
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
        from fava_ai.storage.conversations import list_conversations, get_conversation, delete_conversation
        if conv_id:
            if request.method == "GET":
                conv = get_conversation(self._db, conv_id)
                if not conv:
                    return jsonify({"error": "Not found"}), 404
                return jsonify(conv)
        return jsonify(list_conversations(self._db))

    @extension_endpoint("conversations", methods=["POST"])
    def api_create_conversation(self):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        data = request.get_json() or {}
        from fava_ai.storage.conversations import create_conversation
        conv = create_conversation(
            self._db,
            title=data.get("title", ""),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
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
            safe_provider_config = {}
            for name, cfg in provider_config.items():
                safe_cfg = dict(cfg)
                if "api_key" in safe_cfg:
                    safe_cfg["api_key"] = "***" if safe_cfg["api_key"] else ""
                safe_provider_config[name] = safe_cfg
            return jsonify({
                "providers": safe_provider_config, "agent": agent_config,
                "knowledge": knowledge_config,
                "config_dir": str(self._config_manager.config_dir),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("config", methods=["PUT"])
    def api_update_config(self):
        import yaml
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400
        config_path = self._config_manager._config_dir / "config.yaml"
        try:
            with open(config_path, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            self._config_manager._load_yaml()
            return jsonify({"saved": True, "path": str(config_path)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("providers", methods=["GET"])
    def api_providers(self):
        return jsonify(self._provider_registry.list_providers())

    @extension_endpoint("providers_test", methods=["POST"])
    def api_test_provider(self):
        data = request.get_json() or {}
        provider_name = data.get("provider", "")
        provider = self._provider_registry.get(provider_name)
        if not provider:
            provider = self._provider_registry.get_default()
        if not provider:
            return jsonify({"connected": False, "error": "No provider configured"})
        try:
            connected = provider.test_connection()
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
        if self._knowledge_engine and self._knowledge_engine.needs_rebuild(
            self.ledger.all_entries
        ):
            self._knowledge_engine.extract_all(
                self.ledger.all_entries, self.ledger.options
            )
