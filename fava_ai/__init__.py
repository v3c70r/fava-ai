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
        self._agent_runtime = None

        self._init_components()

    def _init_components(self):
        from fava_ai.config import ConfigManager
        from fava_ai.storage.database import Database
        from fava_ai.models.registry import ProviderRegistry
        from fava_ai.tools.registry import ToolRegistry
        from fava_ai.tools.builtin.ledger import register_ledger_tools

        self._config_manager = ConfigManager(
            self.ledger, self.config or {}, self.config_dir
        )

        db_path = self.config_dir / "conversations.db"
        self._db = Database(db_path)
        self._db.initialize()

        self._provider_registry = ProviderRegistry(self._config_manager)

        self._tool_registry = ToolRegistry()
        register_ledger_tools(self._tool_registry, self.ledger)

        from fava_ai.agent.runtime import AgentRuntime
        from fava_ai.agent.context import ContextBuilder

        context_builder = ContextBuilder(self.ledger, self._tool_registry)

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
                    create_conversation,
                    save_message,
                    update_title,
                )
                if not conversation_id:
                    provider = provider_name or (
                        self.config.get("provider", "") if self.config else ""
                    )
                    create_conversation(
                        self._db, title=user_message[:80],
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
                "trace": result.get("trace", []),
                "tool_call_count": result.get("tool_call_count", 0),
            })

        except LimitExceeded as e:
            return jsonify({"error": f"Limit exceeded: {e}"}), 429
        except Exception as e:
            traceback.print_exc()
            return jsonify({"error": str(e)}), 500

    @extension_endpoint("chat/stream", methods=["POST"])
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
                    user_message=user_message,
                    conversation_id=conversation_id,
                    messages=messages,
                    provider_name=provider_name,
                )

                yield f"data: {json.dumps({'type': 'content', 'content': result['content'], 'conversation_id': result['conversation_id']})}\n\n"

                for step in result.get("trace", []):
                    if step["step_type"] == "tool_call":
                        yield f"data: {json.dumps({'type': 'tool_call', 'step': step})}\n\n"

                yield f"data: {json.dumps({'type': 'done', 'conversation_id': result['conversation_id'], 'usage': result.get('usage')})}\n\n"

            except LimitExceeded as e:
                yield f"data: {json.dumps({'type': 'error', 'error': f'Limit exceeded: {e}'})}\n\n"
            except Exception as e:
                traceback.print_exc()
                yield f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n"

        return Response(
            stream_with_context(generate()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
            },
        )

    @extension_endpoint("conversations", methods=["GET"])
    def api_list_conversations(self):
        if not self._db:
            return jsonify([])
        from fava_ai.storage.conversations import list_conversations
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

    @extension_endpoint("conversations/<conv_id>", methods=["GET"])
    def api_get_conversation(self, conv_id):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        from fava_ai.storage.conversations import get_conversation
        conv = get_conversation(self._db, conv_id)
        if not conv:
            return jsonify({"error": "Not found"}), 404
        return jsonify(conv)

    @extension_endpoint("conversations/<conv_id>", methods=["DELETE"])
    def api_delete_conversation(self, conv_id):
        if not self._db:
            return jsonify({"error": "No database"}), 500
        from fava_ai.storage.conversations import delete_conversation
        delete_conversation(self._db, conv_id)
        return jsonify({"deleted": True})

    @extension_endpoint("tools", methods=["GET"])
    def api_list_tools(self):
        tools = []
        for tool in self._tool_registry.list_tools():
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "permission": tool.permission,
            })
        return jsonify(tools)

    @extension_endpoint("tools/<name>", methods=["GET"])
    def api_tool_detail(self, name):
        tool = self._tool_registry.get(name)
        if not tool:
            return jsonify({"error": f"Tool not found: {name}"}), 404
        return jsonify({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "permission": tool.permission,
        })

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
                "providers": safe_provider_config,
                "agent": agent_config,
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
    def api_list_providers(self):
        return jsonify(self._provider_registry.list_providers())

    @extension_endpoint("providers/test", methods=["POST"])
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

    @extension_endpoint("providers/<name>/models", methods=["GET"])
    def api_list_models(self, name):
        provider = self._provider_registry.get(name)
        if not provider:
            return jsonify({"error": f"Provider not found: {name}"}), 404
        try:
            models = provider.list_models()
            return jsonify({"provider": name, "models": models})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    def after_load_file(self):
        """Fires on ledger load/reload."""
        pass
