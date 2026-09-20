"""External tool plugin loader — discovers and loads tools from .fava-ai/tools/."""

import importlib.util
import logging
from pathlib import Path

from fava_ai.tools.base import BaseTool

logger = logging.getLogger(__name__)


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
    tools: list[BaseTool] = []
    if not tools_dir.exists():
        return tools

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

        except Exception:
            # Log the load error but don't crash Fava.
            logger.exception("Failed to load tool plugin %s", py_file)

    return tools
