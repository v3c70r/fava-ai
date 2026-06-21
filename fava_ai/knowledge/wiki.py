"""WikiManager — read/write/search markdown wiki pages with YAML frontmatter."""

import os
import re
import yaml
from datetime import datetime
from pathlib import Path
from typing import Any


FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


class WikiPage:
    def __init__(self, path: Path, metadata: dict | None = None, content: str = ""):
        self.path = Path(path)
        self.metadata = metadata or {}
        self.content = content

    @classmethod
    def from_file(cls, path: Path) -> "WikiPage":
        if not path.exists():
            return cls(path, {}, "")
        text = path.read_text(encoding="utf-8")
        meta = {}
        body = text
        m = FRONTMATTER_RE.match(text)
        if m:
            try:
                meta = yaml.safe_load(m.group(1)) or {}
            except yaml.YAMLError:
                pass
            body = text[m.end():]
        return cls(path, meta, body.strip())

    def to_text(self) -> str:
        meta_str = yaml.dump(self.metadata, allow_unicode=True, default_flow_style=False).strip()
        return f"---\n{meta_str}\n---\n\n{self.content}\n"

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(self.to_text(), encoding="utf-8")


class WikiManager:
    def __init__(self, wiki_dir: Path):
        self.wiki_dir = Path(wiki_dir)
        self.wiki_dir.mkdir(parents=True, exist_ok=True)

    # ── Read ──────────────────────────────────────────────────────

    def read(self, rel_path: str) -> WikiPage:
        path = self.wiki_dir / rel_path
        return WikiPage.from_file(path)

    def exists(self, rel_path: str) -> bool:
        return (self.wiki_dir / rel_path).exists()

    # ── Write ─────────────────────────────────────────────────────

    def write(self, rel_path: str, content: str, metadata: dict | None = None):
        path = self.wiki_dir / rel_path
        page = WikiPage(path, metadata, content)
        page.save()
        self._update_index()

    def write_page(self, page: WikiPage):
        page.save()
        self._update_index()

    # ── Search ────────────────────────────────────────────────────

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        query_lower = query.lower()
        results = []
        for md_file in self.wiki_dir.rglob("*.md"):
            if md_file.name.startswith("_"):
                continue
            try:
                text = md_file.read_text(encoding="utf-8")
                if query_lower in text.lower():
                    rel = str(md_file.relative_to(self.wiki_dir))
                    page = WikiPage.from_file(md_file)
                    results.append({
                        "path": rel,
                        "title": page.metadata.get("title", md_file.stem),
                        "type": page.metadata.get("type", ""),
                        "snippet": self._snippet(text, query_lower, 120),
                    })
            except Exception:
                continue
            if len(results) >= max_results:
                break
        return results

    def _snippet(self, text: str, query: str, context: int = 120) -> str:
        idx = text.lower().find(query)
        if idx < 0:
            return text[:context]
        start = max(0, idx - context // 2)
        end = min(len(text), idx + len(query) + context // 2)
        return text[start:end].replace("\n", " ")

    # ── List / Structure ──────────────────────────────────────────

    def list_pages(self, prefix: str = "") -> list[dict]:
        base = self.wiki_dir / prefix if prefix else self.wiki_dir
        if not base.exists():
            return []
        results = []
        for md_file in sorted(base.rglob("*.md")):
            rel = str(md_file.relative_to(self.wiki_dir))
            page = WikiPage.from_file(md_file)
            results.append({
                "path": rel,
                "title": page.metadata.get("title", md_file.stem),
                "type": page.metadata.get("type", ""),
                "size": md_file.stat().st_size,
                "updated": page.metadata.get("updated", ""),
            })
        return results

    # ── Index ─────────────────────────────────────────────────────

    def _update_index(self):
        pages = []
        for md_file in sorted(self.wiki_dir.rglob("*.md")):
            if md_file.name in ("index.md", "AGENTS.md", "log.md"):
                continue
            rel = str(md_file.relative_to(self.wiki_dir))
            page = WikiPage.from_file(md_file)
            pages.append({
                "path": rel,
                "title": page.metadata.get("title", md_file.stem),
                "type": page.metadata.get("type", ""),
            })

        lines = [
            "---",
            "title: Wiki Index",
            "type: index",
            f"updated: {datetime.now().isoformat()[:19]}",
            "---",
            "",
            "# Wiki Index",
            "",
        ]

        by_type: dict[str, list] = {}
        for p in pages:
            t = p.get("type", "other")
            by_type.setdefault(t, []).append(p)

        for t in sorted(by_type.keys()):
            lines.append(f"## {t.title()}")
            for p in by_type[t]:
                lines.append(f"- [[{p['path']}|{p['title']}]]")
            lines.append("")

        index = self.wiki_dir / "index.md"
        index.write_text("\n".join(lines), encoding="utf-8")

    # ── Log ───────────────────────────────────────────────────────

    def append_log(self, event: str, details: dict | None = None):
        log_file = self.wiki_dir / "log.md"
        timestamp = datetime.now().isoformat()[:19]
        detail_str = ""
        if details:
            detail_str = " | " + yaml.dump(details, allow_unicode=True, default_flow_style=True).strip()
        entry = f"- {timestamp} | {event}{detail_str}\n"

        if not log_file.exists():
            log_file.write_text(
                "---\ntitle: Audit Log\ntype: log\n---\n\n# Audit Log\n\n", encoding="utf-8"
            )
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(entry)

    # ── Clean ─────────────────────────────────────────────────────

    def delete_dir(self, rel_path: str):
        dir_path = self.wiki_dir / rel_path
        if dir_path.exists():
            import shutil
            shutil.rmtree(dir_path)
            self._update_index()
