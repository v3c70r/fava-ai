"""Test the Fava AI agent with DeepSeek API against beancount fixtures.

Requires DEEPSEEK_API_KEY environment variable.
Usage: python3 test_deepseek.py
"""
import sys
import os

if not os.environ.get("DEEPSEEK_API_KEY"):
    print("Error: set DEEPSEEK_API_KEY env var first")
    sys.exit(1)

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
from fava_ai.models.deepseek import DeepSeekProvider
from fava_ai.tools.registry import ToolRegistry
from fava_ai.tools.builtin.ledger import register_ledger_tools
from fava_ai.agent.runtime import AgentRuntime
from fava_ai.agent.context import ContextBuilder

config_dir = Path("/tmp/fava-ai-test")
config_dir.mkdir(parents=True, exist_ok=True)

import yaml
config_yaml = {
    "providers": {
        "deepseek": {
            "api_key": os.environ["DEEPSEEK_API_KEY"],
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
        api_key=os.environ["DEEPSEEK_API_KEY"],
        model="deepseek-chat",
    ),
)

tool_registry = ToolRegistry()
register_ledger_tools(tool_registry, ledger)

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
        print(f"<<< Assistant: {result['content'][:200]}")
        tc_count = result.get("tool_call_count", 0)
        prov = result.get("provenance", {})
        print(f"  (Tool calls: {tc_count}, steps: {prov.get('total_steps', 0)})")
    except Exception as e:
        print(f"<<< Error: {e}")

db.close()
print("\nDone!")
