"""Test the Fava AI agent with DeepSeek API against beancount fixtures."""
import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

from pathlib import Path
from beancount import loader

fixtures_dir = Path(__file__).parent / "tests" / "fixtures" / "ledgers"
example_file = fixtures_dir / "beancount-example.beancount"

print(f"Loading ledger: {example_file}")
entries, errors, options = loader.load_file(str(example_file))

if errors:
    print(f"Parse errors: {errors}")
    sys.exit(1)

print(f"Loaded {len(entries)} entries successfully")

class MockLedger:
    all_entries = entries
    beancount_file_path = str(example_file)
    options = options

ledger = MockLedger()

from fava_ai.config import ConfigManager
from fava_ai.storage.database import Database
from fava_ai.models.registry import ProviderRegistry
from fava_ai.tools.registry import ToolRegistry
from fava_ai.tools.builtin.ledger import register_ledger_tools
from fava_ai.agent.runtime import AgentRuntime
from fava_ai.agent.context import ContextBuilder
from fava_ai.models.deepseek import DeepSeekProvider

config_dir = Path("/tmp/fava-ai-test")
config_dir.mkdir(parents=True, exist_ok=True)

import yaml
config_yaml = {
    "providers": {
        "deepseek": {
            "api_key": "sk-ab94f22f6016438c9972e3a6ae6a7b5f",
            "model": "deepseek-chat",
        }
    }
}
with open(config_dir / "config.yaml", "w") as f:
    yaml.dump(config_yaml, f)

extension_config = {"provider": "deepseek", "model": "deepseek-chat"}

config_manager = ConfigManager(ledger, extension_config, config_dir)

db = Database(config_dir / "conversations.db")
db.initialize()

provider_registry = ProviderRegistry(config_manager)
provider_registry.register(
    "deepseek",
    DeepSeekProvider(
        api_key="sk-ab94f22f6016438c9972e3a6ae6a7b5f",
        model="deepseek-chat",
    ),
)

tool_registry = ToolRegistry()
register_ledger_tools(tool_registry, ledger)

print(f"\nRegistered {len(tool_registry.list_tools())} tools:")
for tool in tool_registry.list_tools():
    print(f"  - {tool.name}")

context_builder = ContextBuilder(ledger, tool_registry)

agent = AgentRuntime(
    provider_registry=provider_registry,
    tool_registry=tool_registry,
    context_builder=context_builder,
    config={"max_iterations": 10, "max_tool_calls": 20, "timeout_seconds": 120},
)

print("\n" + "="*60)
print("Testing with DeepSeek API...")
print("="*60)

test_questions = [
    "What is the operating currency and date range of this ledger?",
    "How many accounts are in this ledger?",
    "What are the top 3 expenses by total amount?",
]

for question in test_questions:
    print(f"\n>>> User: {question}")
    try:
        result = agent.run(
            user_message=question,
            provider_name="deepseek",
        )
        print(f"<<< Assistant: {result['content']}")
        tc_count = result.get("tool_call_count", 0)
        trace = result.get("trace", [])
        print(f"  (Tool calls: {tc_count}, steps: {len(trace)})")
        for step in trace:
            if step.get("step_type") == "tool_call":
                print(f"    → Tool: {step.get('tool_name')} ({step.get('tool_input', '')})")
    except Exception as e:
        print(f"<<< Error: {e}")
        import traceback
        traceback.print_exc()

db.close()
print("\nDone!")
