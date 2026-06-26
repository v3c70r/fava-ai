"""Dashboard generation tools — create Fava dashboards via API."""

import json

from fava_ai.tools.base import BaseTool, ToolResult


class ListDashboardsTool(BaseTool):
    def __init__(self, ledger=None):
        self._ledger = ledger

    @property
    def name(self) -> str:
        return "list_dashboards"

    @property
    def description(self) -> str:
        return "List existing Fava dashboards configured in the ledger."

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    def execute(self) -> ToolResult:
        dashboards = []
        if self._ledger:
            entries = self._ledger.all_entries
            for e in entries:
                if hasattr(e, "values") and len(e.values) > 1:
                    dtype = str(e.values[0].value) if hasattr(e.values[0], "value") else ""
                    if dtype == "fava-dashboard":
                        name = str(e.values[1].value) if len(e.values) > 1 and hasattr(e.values[1], "value") else "unnamed"
                        dashboards.append({"name": name, "date": str(e.date)})

        return ToolResult(
            content=json.dumps({"dashboards": dashboards, "count": len(dashboards)}, indent=2),
            metadata={"count": len(dashboards)},
        )


class GenerateDashboardTool(BaseTool):
    @property
    def name(self) -> str:
        return "generate_dashboard"

    @property
    def description(self) -> str:
        return (
            "Generate a Fava dashboard definition from parameters. "
            "A dashboard is a grid of charts. Each chart has a BQL query and a chart type "
            "(line, bar, pie, table). Use this to create custom visualizations."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Dashboard name"},
                "description": {"type": "string", "description": "Dashboard description (optional)"},
                "charts": {
                    "type": "array",
                    "description": "List of chart definitions",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "query": {"type": "string", "description": "BQL query"},
                            "chart_type": {
                                "type": "string",
                                "enum": ["line", "bar", "pie", "table", "treemap"],
                            },
                            "width": {"type": "integer"},
                            "height": {"type": "integer"},
                        },
                        "required": ["name", "query", "chart_type"],
                    },
                },
            },
            "required": ["name", "charts"],
        }

    def execute(self, name: str, charts: list, description: str = "") -> ToolResult:
        dashboard = {
            "name": name,
            "description": description,
            "charts": charts,
            "total_charts": len(charts),
        }
        return ToolResult(
            content=json.dumps(dashboard, indent=2),
            metadata={"name": name, "chart_count": len(charts)},
        )


class GenerateChartTool(BaseTool):
    @property
    def name(self) -> str:
        return "generate_chart"

    @property
    def description(self) -> str:
        return "Generate a single Fava chart configuration from a BQL query and chart type."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Chart title"},
                "query": {"type": "string", "description": "BQL query for chart data"},
                "chart_type": {
                    "type": "string",
                    "enum": ["line", "bar", "pie", "table", "treemap"],
                },
                "width": {"type": "integer", "description": "Chart width in grid units (default 1)"},
                "height": {"type": "integer", "description": "Chart height in grid units (default 1)"},
            },
            "required": ["name", "query", "chart_type"],
        }

    def execute(self, name: str, query: str, chart_type: str, width: int = 1, height: int = 1) -> ToolResult:
        chart = {
            "name": name,
            "query": query,
            "chart_type": chart_type,
            "width": width,
            "height": height,
        }
        return ToolResult(
            content=json.dumps(chart, indent=2),
            metadata={"name": name, "chart_type": chart_type},
        )


def register_dashboard_tools(registry, ledger=None):
    registry.register(ListDashboardsTool(ledger))
    registry.register(GenerateDashboardTool())
    registry.register(GenerateChartTool())
