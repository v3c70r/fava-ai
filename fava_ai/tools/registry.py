import json
import traceback

from fava_ai.tools.base import BaseTool, ToolDefinition, ToolResult, ToolError


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def unregister(self, name: str):
        self._tools.pop(name, None)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_tools(self) -> list[BaseTool]:
        return list(self._tools.values())

    def get_definitions(self) -> list[dict]:
        return [t.to_definition().to_openai_schema() for t in self._tools.values()]

    def execute(self, tool_call) -> ToolResult:
        name = tool_call.function.name
        tool = self._tools.get(name)
        if not tool:
            raise ToolError(f"Tool not found: {name}", tool_name=name)

        try:
            args = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as e:
            raise ToolError(f"Invalid tool arguments: {e}", tool_name=name)

        try:
            return tool.execute(**args)
        except ToolError:
            raise
        except Exception as e:
            raise ToolError(
                f"Tool execution error: {e}\n{traceback.format_exc()}",
                tool_name=name,
            )
