import json
import traceback

from flask import request, jsonify, Response, stream_with_context

from fava_ai.agent.limits import LimitExceeded


def register_chat_api(app, extension):
    """Register chat API endpoints on the Flask app."""

    @app.post("/chat")
    def chat():
        try:
            data = request.get_json()
            if not data or "message" not in data:
                return jsonify({"error": "message is required"}), 400

            user_message = data["message"]
            conversation_id = data.get("conversation_id")

            messages = None
            if conversation_id and extension.db:
                from fava_ai.storage.conversations import load_messages
                messages = load_messages(extension.db, conversation_id)

            provider_name = data.get("provider")

            result = extension.agent_runtime.run(
                user_message=user_message,
                conversation_id=conversation_id,
                messages=messages,
                provider_name=provider_name,
            )

            conv_id = result["conversation_id"]
            if extension.db:
                from fava_ai.storage.conversations import (
                    create_conversation,
                    save_message,
                    update_title,
                )
                if not conversation_id:
                    provider = provider_name or (extension._config_manager._extension_config.get("provider", ""))
                    model = ""
                    create_conversation(extension.db, title=user_message[:80], provider=provider, model=model)

                for msg in result["messages"]:
                    if msg.role != "system":
                        save_message(extension.db, conv_id, msg)

                title = user_message[:80] if len(user_message) > 80 else user_message
                try:
                    update_title(extension.db, conv_id, title)
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

    @app.post("/chat/stream")
    def chat_stream():
        data = request.get_json()
        if not data or "message" not in data:
            return jsonify({"error": "message is required"}), 400

        def generate():
            try:
                user_message = data["message"]
                conversation_id = data.get("conversation_id")

                messages = None
                if conversation_id and extension.db:
                    from fava_ai.storage.conversations import load_messages
                    messages = load_messages(extension.db, conversation_id)

                provider_name = data.get("provider")

                result = extension.agent_runtime.run(
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

    @app.post("/providers/test")
    def test_provider():
        data = request.get_json() or {}
        provider_name = data.get("provider", "")
        provider = extension.provider_registry.get(provider_name)
        if not provider:
            provider = extension.provider_registry.get_default()
        if not provider:
            return jsonify({"connected": False, "error": "No provider configured"})
        try:
            connected = provider.test_connection()
            return jsonify({"connected": connected})
        except Exception as e:
            return jsonify({"connected": False, "error": str(e)})
