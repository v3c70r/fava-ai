from flask import jsonify


def register_tools_api(app, extension):
    @app.get("/tools")
    def list_tools():
        tools = []
        for tool in extension.tool_registry.list_tools():
            tools.append({
                "name": tool.name,
                "description": tool.description,
                "parameters": tool.parameters,
                "permission": tool.permission,
            })
        return jsonify(tools)

    @app.get("/tools/<name>")
    def tool_detail(name):
        tool = extension.tool_registry.get(name)
        if not tool:
            return jsonify({"error": f"Tool not found: {name}"}), 404
        return jsonify({
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.parameters,
            "permission": tool.permission,
        })
