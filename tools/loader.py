"""External tool plugin loader — discovers and loads tools from .fava-ai/tools/."""

import importlib.util
import sys
from pathlib import Path

from fava_ai.tools.base import BaseTool


def load_external_tools(tools_dir: Path) -> list[BaseTool]:
    """Discover and load external tool plugins from a directory.

    Each .py file in tools_dir is loaded as a module.
    The module should export a list of BaseTool instances via `tools` attribute.

    Example external tool plugin (market_data.py):
        from fava_ai.tools.base import BaseTool, ToolResult

        class MarketPriceTool(BaseTool):
            name = "market_price"
            description = "Get current market price for a ticker"
            parameters = {"type": "object", "properties": {
                "ticker": {"type": "string"}
            }, "required": ["ticker"]}

            def execute(self, ticker: str) -> ToolResult:
                price = fetch_price(ticker)
                return ToolResult(content=f"{ticker}: ${price}", metadata={"ticker": ticker, "price": price})

        tools = [MarketPriceTool()]
    """
    tools = []
    if not tools_dir.exists():
        return tools

    sys.path.insert(0, str(tools_dir.parent))

    for py_file in sorted(tools_dir.glob("*.py")):
        if py_file.name.startswith("_"):
            continue

        try:
            module_name = f"fava_ai_external_{py_file.stem}"
            spec = importlib.util.spec_from_file_location(module_name, py_file)
            if spec is None or spec.loader is None:
                continue

            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            if hasattr(module, "tools"):
                for tool in module.tools:
                    if isinstance(tool, BaseTool):
                        tools.append(tool)

        except Exception as e:
            # Log load error but don't crash
            print(f"[fava_ai] Failed to load tool plugin {py_file}: {e}", file=sys.stderr)

    return tools
