"""ExecutionTracker — per-response audit trail with provenance."""

import time
import uuid
from dataclasses import dataclass, field


@dataclass
class ProvenanceStep:
    step_index: int
    step_type: str  # "plan", "tool_call", "synthesis"
    tool_name: str | None = None
    tool_input: str | None = None
    tool_output: str | None = None
    bql_query: str | None = None
    wiki_sources: list[str] | None = None
    started_at: float | None = None
    completed_at: float | None = None
    error: str | None = None

    def to_dict(self) -> dict:
        return {
            "step_index": self.step_index,
            "step_type": self.step_type,
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
            "tool_output": self.tool_output,
            "bql_query": self.bql_query,
            "wiki_sources": self.wiki_sources,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
        }


class ExecutionTracker:
    def __init__(self, message_id: str | None = None):
        self.id = str(uuid.uuid4())
        self.message_id = message_id or ""
        self.steps: list[ProvenanceStep] = []
        self.started_at = time.time()
        self.completed_at: float | None = None
        self.total_tool_calls = 0
        self.total_bql_queries = 0
        self.total_wiki_lookups = 0

    def record_plan(self, iteration: int):
        self.steps.append(ProvenanceStep(
            step_index=iteration,
            step_type="plan",
            started_at=time.time(),
        ))

    def record_tool_call(self, iteration: int, tool_name: str, tool_input: str,
                         tool_output: str, error: str | None = None):
        step = ProvenanceStep(
            step_index=iteration,
            step_type="tool_call",
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output[:1000] if tool_output else None,
            error=error,
            started_at=time.time(),
            completed_at=time.time(),
        )

        if tool_name == "run_bql":
            self.total_bql_queries += 1
            step.bql_query = tool_input
        elif tool_name in ("wiki_search", "wiki_read", "wiki_list"):
            self.total_wiki_lookups += 1

        self.total_tool_calls += 1
        self.steps.append(step)

    def record_synthesis(self, iteration: int):
        self.steps.append(ProvenanceStep(
            step_index=iteration,
            step_type="synthesis",
            completed_at=time.time(),
        ))
        self.completed_at = time.time()

    def to_dict(self) -> dict:
        return {
            "tracker_id": self.id,
            "message_id": self.message_id,
            "total_steps": len(self.steps),
            "total_tool_calls": self.total_tool_calls,
            "total_bql_queries": self.total_bql_queries,
            "total_wiki_lookups": self.total_wiki_lookups,
            "duration_seconds": round((self.completed_at or time.time()) - self.started_at, 2),
            "steps": [s.to_dict() for s in self.steps],
        }

    def provenance_summary(self) -> str:
        """Human-readable provenance summary for the UI footer."""
        lines = []
        tools_used = set()
        bql_queries = []
        wiki_pages = []

        for s in self.steps:
            if s.step_type == "tool_call" and s.tool_name and not s.error:
                tools_used.add(s.tool_name)
            if s.bql_query:
                bql_queries.append(s.bql_query)

        lines.append(f"**Tools used:** {', '.join(sorted(tools_used))}" if tools_used else "No tools used")
        lines.append(f"**Tool calls:** {self.total_tool_calls}")
        if bql_queries:
            lines.append(f"**BQL queries run:** {len(bql_queries)}")
        if self.total_wiki_lookups:
            lines.append(f"**Wiki lookups:** {self.total_wiki_lookups}")
        return "\n".join(lines)
