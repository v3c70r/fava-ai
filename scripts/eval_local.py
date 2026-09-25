#!/usr/bin/env python3
"""Evaluate the fava-ai agent stack against a live OpenAI-compatible endpoint.

Builds the same component graph as the Fava extension (config, provider
registry, tools, wiki/knowledge, context builder, agent runtime) and runs a set
of ledger questions, reporting latency, tool usage, provenance and errors.

Usage:
    python scripts/eval_local.py \
        --base-url http://localhost:8080/v1 \
        --api-key "$EMBEDDING_API_KEY" \
        --model /path/to/model.gguf \
        --ledger tests/data/ledgers/rich-features.beancount

Options:
    --stream        also exercise run_stream and measure time-to-first-token
    --timeout N     per-question agent timeout in seconds (default 600)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from beancount import loader  # noqa: E402
from fava_ai.agent.context import ContextBuilder  # noqa: E402
from fava_ai.agent.errors import AgentError  # noqa: E402
from fava_ai.agent.runtime import AgentRuntime  # noqa: E402
from fava_ai.config import ConfigManager  # noqa: E402
from fava_ai.knowledge.engine import KnowledgeEngine  # noqa: E402
from fava_ai.knowledge.wiki import WikiManager  # noqa: E402
from fava_ai.models.registry import ProviderRegistry  # noqa: E402
from fava_ai.prompts.registry import PromptRegistry  # noqa: E402
from fava_ai.tools.builtin.ledger import register_ledger_tools  # noqa: E402
from fava_ai.tools.builtin.wiki import register_wiki_tools  # noqa: E402
from fava_ai.tools.registry import ToolRegistry  # noqa: E402

DEFAULT_QUESTIONS = [
    "What is the operating currency and date range of this ledger?",
    "What are my top 3 expense categories by total amount?",
    "How much did I spend on rent in total?",
    "What investment holdings do I have, and what did they cost?",
]


class MockLedger:
    def __init__(self, entries, options, path):
        self.all_entries = entries
        self.options = options
        self.beancount_file_path = str(path)


def build_stack(args):
    entries, errors, options = loader.load_file(args.ledger)
    if errors:
        print(f"!! ledger has {len(errors)} errors (continuing)")

    ledger = MockLedger(entries, options, args.ledger)

    extension_config = {
        "provider": "local",
        "base_url": args.base_url,
        "api_key": args.api_key or "",
        "model": args.model,
        "agent": {
            "max_iterations": args.max_iterations,
            "max_tool_calls": 12,
            "timeout_seconds": args.timeout,
            "max_context_tokens": 24000,
        },
        "knowledge": {"auto_extract": True},
    }
    config_dir = Path(args.config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)
    # Everything comes from the directive: no config.yaml is written.
    cm = ConfigManager(ledger, extension_config, config_dir)

    wiki = WikiManager(config_dir / "wiki")
    knowledge = KnowledgeEngine(wiki, cm.get_knowledge_config())
    if knowledge.needs_rebuild(entries):
        t0 = time.time()
        knowledge.extract_all(entries, options)
        print(f"   [wiki] extracted in {time.time() - t0:.2f}s")

    providers = ProviderRegistry(cm)
    tools = ToolRegistry()
    register_ledger_tools(tools, ledger)
    register_wiki_tools(tools, wiki)
    prompts = PromptRegistry(config_dir)
    context = ContextBuilder(ledger, tools, wiki, prompts)

    runtime = AgentRuntime(
        provider_registry=providers,
        tool_registry=tools,
        context_builder=context,
        config=cm.get_agent_config(),
    )
    return runtime, cm, tools, wiki


def run_question(runtime, tools, question):
    result = {
        "question": question,
        "answer": None,
        "error": None,
        "error_type": None,
        "wall_seconds": None,
        "tool_calls": [],
        "tool_errors": [],
        "iterations": None,
        "partial": False,
        "stop_reason": None,
    }
    t0 = time.time()
    try:
        res = runtime.run(question)
        result["wall_seconds"] = round(time.time() - t0, 2)
        result["answer"] = res["content"]
        steps = res["provenance"]["steps"]
        result["iterations"] = sum(1 for s in steps if s["step_type"] == "plan")
        result["partial"] = res.get("partial", False)
        result["stop_reason"] = res.get("stop_reason")
        for step in steps:
            if step["step_type"] == "tool_call":
                result["tool_calls"].append({
                    "tool": step["tool_name"],
                    "input": (step["tool_input"] or "")[:200],
                    "error": step["error"],
                })
                if step["error"]:
                    result["tool_errors"].append(step["error"])
    except AgentError as e:
        result["wall_seconds"] = round(time.time() - t0, 2)
        result["error"] = str(e)
        result["error_type"] = type(e).__name__
    except Exception as e:  # noqa: BLE001
        result["wall_seconds"] = round(time.time() - t0, 2)
        result["error"] = f"{type(e).__name__}: {e}"
        result["error_type"] = type(e).__name__
    return result


def run_stream_question(runtime, question):
    """Measure time-to-first-token (reasoning or content) and total time."""
    out = {"question": question, "ttft": None, "ttft_content": None,
           "total": None, "deltas": 0, "reasoning_deltas": 0,
           "tool_calls": 0, "error": None, "final": None}
    t0 = time.time()
    try:
        for event in runtime.run_stream(question):
            if event["type"] == "reasoning_delta":
                out["reasoning_deltas"] += 1
                if out["ttft"] is None:
                    out["ttft"] = round(time.time() - t0, 2)
            if event["type"] == "content_delta":
                if out["ttft"] is None:
                    out["ttft"] = round(time.time() - t0, 2)
                if out["ttft_content"] is None:
                    out["ttft_content"] = round(time.time() - t0, 2)
                out["deltas"] += 1
            if event["type"] == "tool_call":
                out["tool_calls"] += 1
            if event["type"] == "done":
                out["final"] = event["result"]["content"]
        out["total"] = round(time.time() - t0, 2)
    except AgentError as e:
        out["total"] = round(time.time() - t0, 2)
        out["error"] = f"{type(e).__name__}: {e}"
    except Exception as e:  # noqa: BLE001
        out["total"] = round(time.time() - t0, 2)
        out["error"] = f"{type(e).__name__}: {e}"
    return out


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost:8080/v1")
    parser.add_argument("--api-key", default=None,
                        help="API key for the endpoint (omit for none)")
    parser.add_argument("--model", required=True)
    parser.add_argument("--ledger", default="tests/data/ledgers/rich-features.beancount")
    parser.add_argument("--config-dir", default=".eval-fava-ai")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--max-iterations", type=int, default=6)
    parser.add_argument("--stream", action="store_true")
    parser.add_argument("--question", action="append", default=None)
    parser.add_argument("--json-out", default=None)
    args = parser.parse_args()

    questions = args.question or DEFAULT_QUESTIONS

    print("=" * 78)
    print("fava-ai local endpoint evaluation")
    print(f"endpoint : {args.base_url}")
    print(f"model    : {args.model}")
    print(f"ledger   : {args.ledger}")
    print(f"timeout  : {args.timeout}s | max_iterations: {args.max_iterations}")
    print("=" * 78)

    runtime, cm, tools, wiki = build_stack(args)
    print(f"tools registered: {len(tools.list_tools())}")

    results = []
    print("\n--- blocking run() ---")
    for q in questions:
        print(f"\nQ: {q}")
        r = run_question(runtime, tools, q)
        results.append(r)
        if r["error"]:
            print(f"   ERROR ({r['error_type']}) after {r['wall_seconds']}s: {r['error']}")
        else:
            print(f"   {r['wall_seconds']}s | iterations={r['iterations']} | "
                  f"partial={r['partial']} stop={r['stop_reason']} | "
                  f"tools={[t['tool'] for t in r['tool_calls']]}")
            print(f"   A: {r['answer']}")
        for te in r["tool_errors"]:
            print(f"   tool error: {te}")

    stream_results = []
    if args.stream:
        print("\n--- streaming run_stream() ---")
        for q in questions:
            print(f"\nQ: {q}")
            s = run_stream_question(runtime, q)
            stream_results.append(s)
            print(f"   ttft={s['ttft']}s (content={s['ttft_content']}s) total={s['total']}s "
                  f"deltas={s['deltas']} reasoning_deltas={s['reasoning_deltas']} "
                  f"tool_calls={s['tool_calls']} error={s['error']}")
            if s["final"]:
                print(f"   A: {s['final']}")

    print("\n" + "=" * 78)
    print("SUMMARY")
    print("=" * 78)
    ok = [r for r in results if not r["error"]]
    failed = [r for r in results if r["error"]]
    print(f"blocking: {len(ok)}/{len(results)} ok, {len(failed)} failed")
    if ok:
        avg = sum(r["wall_seconds"] for r in ok) / len(ok)
        print(f"avg wall time: {avg:.1f}s")
        print(f"total tool calls: {sum(len(r['tool_calls']) for r in ok)}")
        print(f"tool errors: {sum(len(r['tool_errors']) for r in ok)}")
    for r in failed:
        print(f"  FAIL [{r['error_type']}] {r['question'][:50]}: {r['error']}")

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {"blocking": results, "streaming": stream_results}, indent=2
        ), encoding="utf-8")
        print(f"\nwrote {args.json_out}")


if __name__ == "__main__":
    main()
