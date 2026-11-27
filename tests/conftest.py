"""
Pytest configuration and global isolation fixtures.
"""

from __future__ import annotations

from pathlib import Path
import pytest


@pytest.fixture(autouse=True)
def isolate_test_persistence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate chat history, memories, and task files for each test."""
    temp_hist = tmp_path / "chat_history.json"
    temp_mems = tmp_path / "companion_memories.json"

    import desktop_companion as dc
    import memory_manager

    monkeypatch.setattr(dc, "_resolve_history_file", lambda: temp_hist)
    monkeypatch.setattr(memory_manager, "get_memories_path", lambda custom_path=None: temp_mems)
    yield
