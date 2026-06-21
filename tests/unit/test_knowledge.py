"""Unit tests for knowledge/ modules."""
import pytest
from pathlib import Path

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
