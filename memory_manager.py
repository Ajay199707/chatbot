"""
Long-Term Memory Manager for the AI Desktop Companion.

Stores and manages persistent user facts, preferences, and personal details
across conversations and application restarts in `companion_memories.json`.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Optional, Tuple

MEMORY_DATA_FILE = "companion_memories.json"


def get_memories_path(custom_path: Optional[Path | str] = None) -> Path:
    """Resolve the path for persistent companion memories."""
    if custom_path:
        return Path(custom_path)

    # Determine base directory (respecting PyInstaller frozen path)
    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
    else:
        app_dir = Path(__file__).resolve().parent

    primary = app_dir / MEMORY_DATA_FILE
    if (
        not primary.exists()
        and getattr(sys, "frozen", False)
        and app_dir.name.lower() == "dist"
        and (app_dir.parent / MEMORY_DATA_FILE).is_file()
    ):
        return app_dir.parent / MEMORY_DATA_FILE
    return primary


def load_memories(path: Optional[Path | str] = None) -> List[str]:
    """Load list of remembered user facts from JSON file."""
    target = get_memories_path(path)
    if not target.is_file():
        return []

    try:
        data = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(data, list):
            cleaned = []
            seen = set()
            for item in data:
                if isinstance(item, str):
                    s = item.strip()
                    if s and s.lower() not in seen:
                        seen.add(s.lower())
                        cleaned.append(s)
            return cleaned
        elif isinstance(data, dict) and "memories" in data and isinstance(data["memories"], list):
            cleaned = []
            seen = set()
            for item in data["memories"]:
                if isinstance(item, str):
                    s = item.strip()
                    if s and s.lower() not in seen:
                        seen.add(s.lower())
                        cleaned.append(s)
            return cleaned
    except Exception:
        pass
    return []


def save_memories(memories: List[str], path: Optional[Path | str] = None) -> None:
    """Save list of remembered user facts to JSON file."""
    target = get_memories_path(path)
    cleaned = []
    seen = set()
    for item in memories:
        if isinstance(item, str):
            s = item.strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                cleaned.append(s)

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(cleaned, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass


def add_memory(fact: str, path: Optional[Path | str] = None) -> Tuple[bool, str]:
    """
    Add a new fact/preference to long-term memory.
    Returns (success: bool, message: str).
    """
    clean_fact = (fact or "").strip()
    if not clean_fact:
        return False, "Cannot remember empty fact."

    # Normalize whitespace
    clean_fact = re.sub(r"\s+", " ", clean_fact)

    memories = load_memories(path)
    lower_fact = clean_fact.lower()

    for existing in memories:
        if existing.lower() == lower_fact:
            return False, f"Fact already remembered: '{existing}'"

    memories.append(clean_fact)
    save_memories(memories, path)
    return True, f"Remembered: '{clean_fact}'"


def remove_memory(query_or_index: str, path: Optional[Path | str] = None) -> Tuple[int, List[str]]:
    """
    Remove memory by index (1-based) or substring match.
    Returns (count_removed: int, removed_facts: List[str]).
    """
    q = (query_or_index or "").strip()
    if not q:
        return 0, []

    memories = load_memories(path)
    if not memories:
        return 0, []

    removed = []
    # Check if 1-based index
    if q.isdigit():
        idx = int(q) - 1
        if 0 <= idx < len(memories):
            removed.append(memories.pop(idx))
            save_memories(memories, path)
            return 1, removed

    lower_q = q.lower()
    retained = []
    for item in memories:
        if lower_q in item.lower():
            removed.append(item)
        else:
            retained.append(item)

    if removed:
        save_memories(retained, path)
    return len(removed), removed


def clear_all_memories(path: Optional[Path | str] = None) -> None:
    """Clear all stored long-term memories."""
    save_memories([], path)


def format_memories_for_prompt(memories: Optional[List[str]] = None) -> str:
    """Format memory items for injection into the effective system prompt."""
    items = memories if memories is not None else load_memories()
    valid_items = [m.strip() for m in items if isinstance(m, str) and m.strip()]
    if not valid_items:
        return ""

    bullets = "\n".join(f"- {m}" for m in valid_items)
    return (
        f"\n\n[Persistent Long-Term Memory & User Facts]:\n{bullets}\n"
        "Keep these user facts, preferences, and personal details in mind across all conversations. "
        "You can remember new facts using the remember_user_fact tool, forget facts with forget_user_fact, "
        "or inspect them with list_user_memories."
    )
