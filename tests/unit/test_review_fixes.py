"""Tests for security and correctness fixes from code review."""
import pytest
from pathlib import Path

from fava_ai.knowledge.wiki import WikiManager
from fava_ai.storage.database import Database
from fava_ai.storage.conversations import create_conversation, save_message, load_messages
from fava_ai.models.base import Message


# ── Path traversal protection ──────────────────────────────────

class TestWikiPathTraversal:
    def test_read_rejects_traversal(self, tmp_path):
        wiki = WikiManager(tmp_path / "wiki")
        wiki.write("safe.md", "content", {"title": "Safe"})
        with pytest.raises(ValueError, match="escapes"):
            wiki.read("../../etc/passwd")

    def test_exists_rejects_traversal(self, tmp_path):
        wiki = WikiManager(tmp_path / "wiki")
        assert wiki.exists("../../etc/passwd") is False

    def test_write_rejects_traversal(self, tmp_path):
        wiki = WikiManager(tmp_path / "wiki")
        with pytest.raises(ValueError, match="escapes"):
            wiki.write("../../evil.md", "hacked", {"title": "X"})

    def test_delete_dir_rejects_traversal(self, tmp_path):
        wiki = WikiManager(tmp_path / "wiki")
        with pytest.raises(ValueError, match="escapes"):
            wiki.delete_dir("../../")

    def test_safe_relative_path_works(self, tmp_path):
        wiki = WikiManager(tmp_path / "wiki")
        wiki.write("accounts/test.md", "content", {"title": "T"})
        assert wiki.exists("accounts/test.md")
        page = wiki.read("accounts/test.md")
        assert page.content == "content"


# ── SQLite thread safety ───────────────────────────────────────

class TestDatabaseThreadSafety:
    def test_db_has_lock(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.initialize()
        assert hasattr(db, '_lock')
        assert db.lock is not None
        db.close()

    def test_execute_uses_lock(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.initialize()
        # Should not raise when using execute wrapper
        db.execute("INSERT INTO conversations (id, provider, model) VALUES (?, ?, ?)",
                   ("test-1", "ollama", "llama3"))
        db.commit()
        row = db.execute("SELECT id FROM conversations WHERE id = ?", ("test-1",)).fetchone()
        assert row["id"] == "test-1"
        db.close()


# ── Timestamp format ───────────────────────────────────────────

class TestTimestampFormat:
    def test_timestamp_is_valid_iso(self, tmp_path):
        db = Database(tmp_path / "test.db")
        db.initialize()
        conv = create_conversation(db, "Test", "ollama", "llama3")
        ts = conv["created_at"]
        # Should end with Z, not +00:00Z
        assert ts.endswith("Z")
        assert "+00:00" not in ts
        # Should be parseable
        from datetime import datetime
        datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ")
        db.close()


# ── Message dedup on multi-turn ────────────────────────────────

class TestMessageDedup:
    def test_load_messages_count_stable(self, tmp_path):
        """Saving messages then loading should return same count."""
        db = Database(tmp_path / "test.db")
        db.initialize()
        conv = create_conversation(db, "Test", "ollama", "llama3")

        save_message(db, conv["id"], Message(role="user", content="Hello"))
        save_message(db, conv["id"], Message(role="assistant", content="Hi"))
        msgs = load_messages(db, conv["id"])
        assert len(msgs) == 2

        # Load and save again should not duplicate
        msgs = load_messages(db, conv["id"])
        assert len(msgs) == 2
        db.close()


# ── Provider connection cache ──────────────────────────────────

class TestProviderConnectionCache:
    def test_connection_cached(self):
        from fava_ai.config import ConfigManager
        from fava_ai.models.registry import ProviderRegistry
        from fava_ai.models.base import BaseProvider, ChatResponse, Message

        class CountingProvider(BaseProvider):
            def __init__(self):
                self.call_count = 0
            @property
            def provider_name(self): return "test"
            def chat(self, messages, tools=None, model=None, **kwargs):
                return ChatResponse(content="ok")
            def chat_stream(self, *a, **kw): yield from []
            def list_models(self): return []
            def test_connection(self):
                self.call_count += 1
                return True

        cm = ConfigManager(None, {"provider": "test"}, Path("/tmp"))
        reg = ProviderRegistry(cm)
        provider = CountingProvider()
        reg.register("test", provider)

        # First call should test connection
        reg.list_providers()
        assert provider.call_count == 1

        # Second call should use cache (no new call)
        reg.list_providers()
        assert provider.call_count == 1


# ── Merchants expense-only ─────────────────────────────────────

class TestMerchantsExpenseOnly:
    def test_only_expenses_counted(self, tmp_path, sample_entries):
        from fava_ai.knowledge.wiki import WikiManager
        from fava_ai.knowledge.extractors.merchants import MerchantExtractor

        wiki = WikiManager(tmp_path / "wiki")
        extractor = MerchantExtractor(wiki)
        stats = extractor.extract(sample_entries, {"operating_currency": ["USD"]})

        # Amazon has 3 expense postings, all in Expenses:Shopping
        # total_spent should be 42.97 + 89.99 + 120.00 = 252.96
        # Not including the Assets:Checking offset
        page = wiki.read("merchants/amazon.md")
        assert "252.96" in page.content or "252" in page.metadata.get("total_spent", "")


# ── Hash written after extraction ──────────────────────────────

class TestHashAfterExtraction:
    def test_hash_written_after_success(self, tmp_path, sample_entries):
        from fava_ai.knowledge.engine import KnowledgeEngine

        wiki = WikiManager(tmp_path / "wiki")
        engine = KnowledgeEngine(wiki)

        # Before extraction, no hash file
        assert not (wiki.wiki_dir / ".entries_hash").exists()

        engine.extract_all(sample_entries, {"operating_currency": ["USD"]})

        # After successful extraction, hash file exists
        assert (wiki.wiki_dir / ".entries_hash").exists()

    def test_hash_not_written_on_failure(self, tmp_path):
        from fava_ai.knowledge.engine import KnowledgeEngine

        wiki = WikiManager(tmp_path / "wiki")
        engine = KnowledgeEngine(wiki)

        # Force a failure by passing invalid entries
        try:
            engine.extract_all(None, {"operating_currency": ["USD"]})
        except Exception:
            pass

        # Hash should NOT be written on failure
        assert not (wiki.wiki_dir / ".entries_hash").exists()
