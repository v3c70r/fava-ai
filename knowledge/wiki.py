"""WikiManager — read/write/search markdown wiki pages with YAML frontmatter."""

import re
import shutil
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import yaml

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)
_META_FILES = {"index.md", "AGENTS.md", "log.md"}
_TOKEN_RE = re.compile(r"[a-z0-9]+")

#: Query terms too common to be meaningful for scoring.
_STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "is", "are",
    "was", "were", "be", "my", "me", "i", "we", "you", "it", "its", "this",
    "that", "what", "which", "how", "much", "many", "do", "does", "did", "get",
    "show", "list", "all", "with", "by", "at", "as", "from", "total", "please",
}


def _stem(word: str) -> str:
    """Very small suffix folder so `groceries` matches `grocery`.

    The same function is applied to indexed tokens and query tokens, so exact
    linguistic correctness matters less than consistency.
    """
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _tokenize(text: str) -> list[str]:
    return _TOKEN_RE.findall(text.lower())


def _rel_posix(path: Path, base: Path) -> str:
    """Relative path with forward slashes on every OS (for links and tool I/O)."""
    return path.relative_to(base).as_posix()


def _is_meta(md_file: Path) -> bool:
    return md_file.name in _META_FILES or md_file.name.startswith("_")


class WikiPage:
    def __init__(self, path: Path, metadata: dict | None = None, content: str = ""):
        self.path = Path(path)
        self.metadata = metadata or {}
        self.content = content

    @classmethod
    def from_file(cls, path: Path) -> "WikiPage":
        if not path.exists():
            return cls(path, {}, "")
        return cls.from_text(path, path.read_text(encoding="utf-8"))

    @classmethod
    def from_text(cls, path: Path, text: str) -> "WikiPage":
        meta: dict = {}
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
        # Number of active `defer_index()` blocks; while > 0 the index is not
        # rebuilt on every write (avoids O(n^2) work during full extraction).
        self._index_deferrals = 0
        # Lazy search cache: (stat-key) -> list of parsed page records.
        self._search_cache: list[dict] | None = None
        self._search_cache_key: tuple | None = None

    @contextmanager
    def defer_index(self):
        """Batch many writes, rebuilding index.md and the search cache once."""
        self._index_deferrals += 1
        try:
            yield
        finally:
            self._index_deferrals -= 1
            if self._index_deferrals == 0:
                self._invalidate_search_cache()
                self._update_index()

    def _invalidate_search_cache(self):
        self._search_cache = None
        self._search_cache_key = None

    def _safe_path(self, rel_path: str) -> Path:
        """Resolve rel_path and ensure it stays inside wiki_dir."""
        base = self.wiki_dir.resolve()
        target = (base / rel_path).resolve()
        if target != base and base not in target.parents:
            raise ValueError(f"Path escapes wiki directory: {rel_path}")
        return target

    # ── Read ──────────────────────────────────────────────────────

    def read(self, rel_path: str) -> WikiPage:
        path = self._safe_path(rel_path)
        return WikiPage.from_file(path)

    def exists(self, rel_path: str) -> bool:
        try:
            return self._safe_path(rel_path).exists()
        except ValueError:
            return False

    # ── Write ─────────────────────────────────────────────────────

    def write(self, rel_path: str, content: str, metadata: dict | None = None):
        path = self._safe_path(rel_path)
        page = WikiPage(path, metadata, content)
        page.save()
        self._invalidate_search_cache()
        self._update_index()

    def write_page(self, page: WikiPage):
        page.save()
        self._invalidate_search_cache()
        self._update_index()

    # ── Search ────────────────────────────────────────────────────

    def _search_index(self) -> list[dict]:
        """Parsed, tokenized copy of every content page, cached by file stat.

        Rebuilding only happens when a file's mtime/size changes, so repeated
        searches during a chat turn are cheap.
        """
        files = sorted(
            f for f in self.wiki_dir.rglob("*.md") if not _is_meta(f)
        )
        try:
            key = tuple(
                (str(f), f.stat().st_mtime_ns, f.stat().st_size) for f in files
            )
        except OSError:
            key = None
        if key is not None and self._search_cache is not None and self._search_cache_key == key:
            return self._search_cache

        entries = []
        for md_file in files:
            try:
                text = md_file.read_text(encoding="utf-8")
            except OSError:
                continue
            page = WikiPage.from_text(md_file, text)
            title = page.metadata.get("title", md_file.stem)
            body_counts = Counter(_stem(t) for t in _tokenize(page.content))
            entries.append({
                "path": _rel_posix(md_file, self.wiki_dir),
                "stem": md_file.stem,
                "text": page.content,
                "lower": page.content.lower(),
                "title": title,
                "title_tokens": {_stem(t) for t in _tokenize(str(title))},
                "body_counts": body_counts,
                "type": page.metadata.get("type", ""),
            })
        self._search_cache = entries
        self._search_cache_key = key
        return entries

    def search(self, query: str, max_results: int = 20) -> list[dict]:
        """Word-boundary + light-stemming search, ranked by relevance.

        Falls back to plain substring matching only when no page matches any
        query token (so exact substrings still work for odd queries).
        """
        query_lower = query.lower()
        raw_words = _tokenize(query) or [query_lower]
        terms = [t for t in (_stem(w) for w in raw_words) if t and t not in _STOPWORDS]

        scored: list[tuple[float, dict]] = []
        for entry in self._search_index():
            score = 0.0
            for term in terms:
                if term in entry["title_tokens"]:
                    score += 10.0
                count = entry["body_counts"].get(term, 0)
                if count:
                    score += min(count, 3)  # cap term-frequency contribution
            if query_lower and query_lower in entry["lower"]:
                score += 2.0  # small exact-phrase bonus
            if score > 0:
                scored.append((score, entry))

        if not scored:
            # Substring fallback (previous behaviour) when nothing tokenized.
            for entry in self._search_index():
                if len(query_lower) > 2 and query_lower in entry["lower"]:
                    scored.append((1.0, entry))

        scored.sort(key=lambda item: (-item[0], item[1]["path"]))
        results = []
        for _score, entry in scored[:max_results]:
            results.append({
                "path": entry["path"],
                "title": entry["title"],
                "type": entry["type"],
                "snippet": self._snippet(entry["text"], set(raw_words), 120),
            })
        return results

    def _snippet(self, text: str, query_words: set, context: int = 120) -> str:
        text_lower = text.lower()
        best_pos = len(text)
        for w in query_words:
            if len(w) > 2:
                pos = text_lower.find(w)
                if 0 <= pos < best_pos:
                    best_pos = pos
        if best_pos >= len(text):
            return text[:context].replace("\n", " ")
        start = max(0, best_pos - context // 2)
        end = min(len(text), best_pos + context // 2)
        return text[start:end].replace("\n", " ")

    # ── List / Structure ──────────────────────────────────────────

    def list_pages(self, prefix: str = "") -> list[dict]:
        base = self.wiki_dir / prefix if prefix else self.wiki_dir
        if not base.exists():
            return []
        results = []
        for md_file in sorted(base.rglob("*.md")):
            if _is_meta(md_file):
                continue
            page = WikiPage.from_file(md_file)
            results.append({
                "path": _rel_posix(md_file, self.wiki_dir),
                "title": page.metadata.get("title", md_file.stem),
                "type": page.metadata.get("type", ""),
                "size": md_file.stat().st_size,
                "updated": page.metadata.get("updated", ""),
            })
        return results

    # ── Index ─────────────────────────────────────────────────────

    def _update_index(self):
        if self._index_deferrals > 0:
            return
        pages = []
        for md_file in sorted(self.wiki_dir.rglob("*.md")):
            if _is_meta(md_file):
                continue
            page = WikiPage.from_file(md_file)
            pages.append({
                "path": _rel_posix(md_file, self.wiki_dir),
                "title": page.metadata.get("title", md_file.stem),
                "type": page.metadata.get("type", ""),
            })

        lines = [
            "---",
            "title: Wiki Index",
            "type: index",
            f"updated: {datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')}",
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

    # ── Section indexes ───────────────────────────────────────────

    def write_section_index(self, section: str, title: str) -> int:
        """Write `<section>/_index.md` listing that section's pages.

        Used by the overview page links; hidden from search and the main index.
        """
        pages = self.list_pages(section)
        lines = [
            "---",
            f"title: {title}",
            "type: index",
            f"updated: {datetime.now().strftime('%Y-%m-%dT%H:%M:%SZ')}",
            "---",
            "",
            f"# {title}",
            "",
            f"{len(pages)} page(s).",
            "",
        ]
        for p in sorted(pages, key=lambda x: x["path"]):
            lines.append(f"- [[{p['path']}|{p['title']}]]")

        target = self.wiki_dir / section / "_index.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return len(pages)

    # ── Log ───────────────────────────────────────────────────────

    def append_log(self, event: str, details: dict | None = None):
        log_file = self.wiki_dir / "log.md"
        timestamp = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
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
        dir_path = self._safe_path(rel_path)
        if dir_path.exists() and dir_path.is_dir():
            shutil.rmtree(dir_path)
            self._invalidate_search_cache()
            self._update_index()
