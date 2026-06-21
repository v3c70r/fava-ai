from flask import jsonify


def register_providers_api(app, extension):
    @app.get("/providers")
    def list_providers():
        return jsonify(extension.provider_registry.list_providers())

    @app.get("/providers/<name>/models")
    def list_models(name):
        provider = extension.provider_registry.get(name)
        if not provider:
            return jsonify({"error": f"Provider not found: {name}"}), 404
        try:
            models = provider.list_models()
            return jsonify({"provider": name, "models": models})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
