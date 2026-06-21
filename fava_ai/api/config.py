from flask import request, jsonify


def register_config_api(app, extension):
    @app.get("/config")
    def get_config():
        try:
            provider_config = extension.config_manager.get_provider_config()
            agent_config = extension.config_manager.get_agent_config()
            knowledge_config = extension.config_manager.get_knowledge_config()

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
                "config_dir": str(extension.config_manager.config_dir),
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    @app.put("/config")
    def update_config():
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data"}), 400

        import yaml
        config_path = extension.config_manager._config_dir / "config.yaml"
        try:
            with open(config_path, "w") as f:
                yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
            extension.config_manager._load_yaml()
            return jsonify({"saved": True, "path": str(config_path)})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
