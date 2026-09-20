"""Unit tests for knowledge/ modules."""
from pathlib import Path

import pytest
from fava_ai.knowledge.wiki import WikiManager, WikiPage


def test_wiki_write_and_read(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write(
        "test/page.md",
        "# Hello\n\nWorld\n",
        {"title": "Test Page", "type": "test", "count": 42},
    )

    page = wiki.read("test/page.md")
    assert page.metadata["title"] == "Test Page"
    assert page.metadata["type"] == "test"
    assert page.metadata["count"] == 42
    assert "Hello" in page.content
    assert "World" in page.content


def test_wiki_exists(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    assert not wiki.exists("test.md")
    wiki.write("test.md", "content", {"title": "T"})
    assert wiki.exists("test.md")


def test_wiki_search(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("a.md", "Apple pie recipe", {"title": "Apple"})
    wiki.write("b.md", "Banana bread recipe", {"title": "Banana"})
    wiki.write("c.md", "Cherry pie recipe", {"title": "Cherry"})

    results = wiki.search("pie")
    assert len(results) == 2
    paths = {r["path"] for r in results}
    assert "a.md" in paths
    assert "c.md" in paths


def test_wiki_search_no_match(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("a.md", "hello", {"title": "A"})
    results = wiki.search("nonexistent")
    assert len(results) == 0


def test_wiki_list_pages(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("accounts/a.md", "a", {"title": "A", "type": "account"})
    wiki.write("accounts/b.md", "b", {"title": "B", "type": "account"})
    wiki.write("merchants/m.md", "m", {"title": "M", "type": "merchant"})

    all_pages = wiki.list_pages()
    assert len(all_pages) >= 3

    account_pages = wiki.list_pages("accounts")
    assert len(account_pages) == 2


def test_wiki_write_page(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    page = WikiPage(
        path=wiki.wiki_dir / "test.md",
        metadata={"title": "T", "type": "test"},
        content="Body",
    )
    wiki.write_page(page)
    assert wiki.exists("test.md")


def test_wiki_append_log(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.append_log("extraction_start", {"entries": 100})
    wiki.append_log("extraction_complete", {"accounts": 10})
    assert wiki.exists("log.md")
    log = wiki.read("log.md")
    assert "extraction_start" in log.content
    assert "extraction_complete" in log.content


def test_wiki_index_update(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("accounts/a.md", "content", {"title": "Account A", "type": "account"})
    wiki.write("merchants/m.md", "content", {"title": "Merchant M", "type": "merchant"})

    assert wiki.exists("index.md")
    index = wiki.read("index.md")
    assert "Account A" in index.content
    assert "Merchant M" in index.content


def test_wiki_page_from_file(tmp_path):
    path = tmp_path / "test.md"
    path.write_text("---\ntitle: Hello\ntype: test\n---\n\nBody text\n")
    page = WikiPage.from_file(path)
    assert page.metadata["title"] == "Hello"
    assert page.metadata["type"] == "test"
    assert page.content == "Body text"


def test_wiki_page_to_text():
    page = WikiPage(
        path=Path("/fake/test.md"),
        metadata={"title": "T", "type": "test"},
        content="Body text",
    )
    text = page.to_text()
    assert "---" in text
    assert "title: T" in text
    assert "Body text" in text


def test_wiki_delete_dir(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("accounts/a.md", "content", {"title": "A", "type": "account"})
    wiki.write("accounts/b.md", "content", {"title": "B", "type": "account"})
    assert wiki.exists("accounts/a.md")

    wiki.delete_dir("accounts")
    assert not wiki.exists("accounts/a.md")
    assert not wiki.exists("accounts/b.md")


def test_engine_needs_rebuild(tmp_path, sample_entries):
    from fava_ai.knowledge.engine import KnowledgeEngine

    wiki = WikiManager(tmp_path / "wiki")
    engine = KnowledgeEngine(wiki)
    assert engine.needs_rebuild(sample_entries) is True


def test_engine_extract_all(tmp_path, sample_entries):
    from fava_ai.knowledge.engine import KnowledgeEngine

    wiki = WikiManager(tmp_path / "wiki")
    engine = KnowledgeEngine(wiki)
    stats = engine.extract_all(sample_entries, {"operating_currency": ["USD"]})

    assert "accounts" in stats
    assert stats["accounts"].get("accounts_generated", 0) > 0

    assert "merchants" in stats
    assert stats["merchants"].get("merchants_generated", 0) >= 2

    assert "recurring" in stats
    assert "portfolio" in stats
    assert "spending" in stats
    assert "cashflow" in stats

    assert wiki.exists("overview.md")
    assert wiki.exists("index.md")
    assert wiki.exists("log.md")


def test_engine_rebuild_idempotent(tmp_path, sample_entries):
    from fava_ai.knowledge.engine import KnowledgeEngine

    wiki = WikiManager(tmp_path / "wiki")
    engine = KnowledgeEngine(wiki)
    engine.extract_all(sample_entries, {"operating_currency": ["USD"]})
    assert not engine.needs_rebuild(sample_entries)


# ── performance: deferred index + search cache ────────────────────


def test_extract_all_rebuilds_index_once(tmp_path, sample_entries):
    from fava_ai.knowledge.engine import KnowledgeEngine

    wiki = WikiManager(tmp_path / "wiki")
    rebuilds = []
    original = wiki._update_index

    def spy():
        if wiki._index_deferrals == 0:
            rebuilds.append(1)
        original()

    wiki._update_index = spy
    KnowledgeEngine(wiki).extract_all(sample_entries, {"operating_currency": ["USD"]})

    # Many pages are written, but index.md is regenerated only once.
    assert len(rebuilds) == 1
    assert wiki.exists("index.md")


def test_search_cache_is_reused_and_invalidated(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("a.md", "alpha content", {"title": "A", "type": "note"})

    assert wiki.search("alpha")
    cached = wiki._search_cache
    assert cached is not None

    # A second search reuses the cache object (no rebuild).
    wiki.search("alpha")
    assert wiki._search_cache is cached

    # A write invalidates it.
    wiki.write("b.md", "beta content", {"title": "B", "type": "note"})
    assert wiki._search_cache is None
    assert wiki.search("beta")


def test_search_cache_reflects_new_files(tmp_path):
    wiki = WikiManager(tmp_path / "wiki")
    wiki.write("a.md", "alpha", {"title": "A", "type": "note"})
    assert wiki.search("alpha")
    assert not wiki.search("gamma")

    wiki.write("c.md", "gamma rays", {"title": "C", "type": "note"})
    assert wiki.search("gamma")


# ── hash completeness ─────────────────────────────────────────────


def test_hash_changes_when_tags_change(tmp_path, sample_entries):
    from fava_ai.knowledge.engine import KnowledgeEngine

    wiki = WikiManager(tmp_path / "wiki")
    engine = KnowledgeEngine(wiki)

    before = engine._compute_hash(sample_entries)
    sample_entries[0].tags.add("new-tag")
    after = engine._compute_hash(sample_entries)
    assert before != after


def test_hash_changes_when_cost_changes(tmp_path, sample_entries):
    from decimal import Decimal

    from beancount.core.amount import Amount
    from fava_ai.knowledge.engine import KnowledgeEngine

    engine = KnowledgeEngine(WikiManager(tmp_path / "wiki"))
    before = engine._compute_hash(sample_entries)

    # beancount entries are namedtuples, so rebuild with a price attached.
    first = sample_entries[0]
    priced_posting = first.postings[0]._replace(
        price=Amount(Decimal("1.00"), "USD")
    )
    modified_first = first._replace(
        postings=[priced_posting, *first.postings[1:]]
    )
    modified = [modified_first, *sample_entries[1:]]

    after = engine._compute_hash(modified)
    assert before != after
