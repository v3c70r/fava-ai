from flask import request, jsonify


def register_conversations_api(app, extension):
    @app.get("/conversations")
    def list_conversations():
        if not extension.db:
            return jsonify([])
        from fava_ai.storage.conversations import list_conversations as list_convs
        return jsonify(list_convs(extension.db))

    @app.get("/conversations/<conv_id>")
    def get_conversation(conv_id):
        if not extension.db:
            return jsonify({"error": "No database"}), 500
        from fava_ai.storage.conversations import get_conversation as get_conv
        conv = get_conv(extension.db, conv_id)
        if not conv:
            return jsonify({"error": "Not found"}), 404
        return jsonify(conv)

    @app.post("/conversations")
    def create_conversation():
        if not extension.db:
            return jsonify({"error": "No database"}), 500
        data = request.get_json() or {}
        from fava_ai.storage.conversations import create_conversation as create_conv
        conv = create_conv(
            extension.db,
            title=data.get("title", ""),
            provider=data.get("provider", ""),
            model=data.get("model", ""),
        )
        return jsonify(conv), 201

    @app.delete("/conversations/<conv_id>")
    def delete_conversation(conv_id):
        if not extension.db:
            return jsonify({"error": "No database"}), 500
        from fava_ai.storage.conversations import delete_conversation as delete_conv
        delete_conv(extension.db, conv_id)
        return jsonify({"deleted": True})
