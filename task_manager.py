"""
task_manager.py - Persistent Reminder, Alarm, and To-Do List Engine
Provides thread-safe atomic JSON persistence, natural language time parsing,
active due-item checking, and task lifecycle management for the AI Companion.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

TASK_DATA_FILE = "reminders_and_tasks.json"

DAYS_OF_WEEK = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
DAY_NAME_MAP = {
    "mon": "Mon", "monday": "Mon",
    "tue": "Tue", "tuesday": "Tue",
    "wed": "Wed", "wednesday": "Wed",
    "thu": "Thu", "thursday": "Thu",
    "fri": "Fri", "friday": "Fri",
    "sat": "Sat", "saturday": "Sat",
    "sun": "Sun", "sunday": "Sun",
}


@dataclass
class TodoItem:
    """Represents a single task in the to-do list."""
    id: str
    title: str
    priority: str = "medium"  # "low", "medium", "high"
    category: str = "general"  # "work", "personal", "study", "shopping", "general"
    due_date: Optional[str] = None  # YYYY-MM-DD or None
    completed: bool = False
    completed_at: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TodoItem:
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            title=str(data.get("title", "")),
            priority=str(data.get("priority", "medium")).lower(),
            category=str(data.get("category", "general")).lower(),
            due_date=data.get("due_date"),
            completed=bool(data.get("completed", False)),
            completed_at=data.get("completed_at"),
            created_at=str(data.get("created_at") or datetime.now().isoformat()),
        )


@dataclass
class ReminderItem:
    """Represents a time-based reminder."""
    id: str
    message: str
    due_time: str  # ISO 8601 string
    recurrence: str = "none"  # "none", "daily", "weekdays", "weekly"
    snoozed_until: Optional[str] = None  # ISO 8601 or None
    status: str = "pending"  # "pending", "triggered", "dismissed"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ReminderItem:
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            message=str(data.get("message", "")),
            due_time=str(data.get("due_time", "")),
            recurrence=str(data.get("recurrence", "none")).lower(),
            snoozed_until=data.get("snoozed_until"),
            status=str(data.get("status", "pending")).lower(),
            created_at=str(data.get("created_at") or datetime.now().isoformat()),
        )


@dataclass
class AlarmItem:
    """Represents a daily or scheduled alarm."""
    id: str
    time_str: str  # "HH:MM" (24-hour format, e.g. "07:30")
    label: str = "Alarm"
    days: List[str] = field(default_factory=lambda: ["all"])  # ["all"] or list of ["Mon", "Tue", ...]
    enabled: bool = True
    status: str = "active"  # "active", "ringing", "dismissed"
    last_triggered_date: Optional[str] = None  # "YYYY-MM-DD"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AlarmItem:
        days = data.get("days", ["all"])
        if isinstance(days, str):
            days = [days]
        return cls(
            id=str(data.get("id") or uuid.uuid4().hex[:8]),
            time_str=str(data.get("time_str", "07:00")),
            label=str(data.get("label", "Alarm")),
            days=days,
            enabled=bool(data.get("enabled", True)),
            status=str(data.get("status", "active")),
            last_triggered_date=data.get("last_triggered_date"),
            created_at=str(data.get("created_at") or datetime.now().isoformat()),
        )


# ============================================================================
# Natural Language Time Parser
# ============================================================================

def parse_natural_datetime(
    time_expr: str,
    reference_dt: Optional[datetime] = None,
) -> Tuple[Optional[datetime], str]:
    """Parse a natural language time expression into a target datetime and recurrence rule.

    Returns:
        (target_datetime, recurrence_rule) where recurrence_rule is one of:
        "none", "daily", "weekdays", "weekly"
    """
    now = reference_dt or datetime.now()
    expr = time_expr.strip().lower()

    if not expr:
        return None, "none"

    # Check for recurring keywords
    recurrence = "none"
    if "everyday" in expr or "every day" in expr or "daily" in expr:
        recurrence = "daily"
    elif "weekday" in expr or "weekdays" in expr:
        recurrence = "weekdays"
    elif "every week" in expr or "weekly" in expr:
        recurrence = "weekly"

    # 1. ISO 8601 string direct check
    try:
        dt = datetime.fromisoformat(time_expr.strip())
        return dt, recurrence
    except ValueError:
        pass

    # 2. Relative offset: "in X seconds / minutes / hours / days" or just "X minutes"
    # Matches: "in 10 minutes", "15 minutes", "in 5 mins", "10m", "in 2 hours", "1h", "in 30s"
    rel_m = re.search(
        r"(?:\b(?:in|after)\s+)?(\d+(?:\.\d+)?)\s*(s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?|h(?:(?:ou)?rs?)?|d(?:ays?)?)\b",
        expr,
    )
    if rel_m:
        val = float(rel_m.group(1))
        unit = rel_m.group(2).lower()
        if unit.startswith("s"):
            target = now + timedelta(seconds=val)
        elif unit.startswith("m"):
            target = now + timedelta(minutes=val)
        elif unit.startswith("h"):
            target = now + timedelta(hours=val)
        elif unit.startswith("d"):
            target = now + timedelta(days=val)
        else:
            target = now + timedelta(minutes=val)
        return target, recurrence

    # 4. Target day modifiers: "today", "tomorrow", or specific day like "on friday"
    day_offset = 0
    if "tomorrow" in expr:
        day_offset = 1
    elif "today" in expr:
        day_offset = 0
    else:
        # Check day names: e.g. "on monday", "monday", "every monday"
        for name, short in DAY_NAME_MAP.items():
            if re.search(r"\b" + name + r"\b", expr):
                target_weekday = DAYS_OF_WEEK.index(short)
                current_weekday = now.weekday()  # Mon=0, Sun=6
                days_ahead = target_weekday - current_weekday
                if days_ahead <= 0:
                    days_ahead += 7
                day_offset = days_ahead
                if "every" in expr:
                    recurrence = "weekly"
                break

    # 5. Clock time parsing: "7:30 pm", "07:30", "7 pm", "8am", "19:00", "at 4"
    time_m = re.search(
        r"(?:at\s+)?\b(\d{1,2})(?::(\d{2}))?(?::(\d{2}))?\s*(am|pm)?\b",
        expr,
    )
    if time_m:
        raw_hr = int(time_m.group(1))
        raw_min = int(time_m.group(2)) if time_m.group(2) else 0
        raw_sec = int(time_m.group(3)) if time_m.group(3) else 0
        meridiem = time_m.group(4)

        if meridiem:
            meridiem = meridiem.lower()
            if meridiem == "pm" and raw_hr < 12:
                raw_hr += 12
            elif meridiem == "am" and raw_hr == 12:
                raw_hr = 0
        elif raw_hr < 7 and not ("today" in expr or "tomorrow" in expr):
            # If no AM/PM is given and hour is small (e.g. "at 4"), assume PM if already past AM
            if now.hour >= raw_hr:
                raw_hr += 12

        base_date = (now + timedelta(days=day_offset)).date()
        target = datetime(base_date.year, base_date.month, base_date.day, raw_hr, raw_min, raw_sec)

        # If time is in the past for today, push to tomorrow (unless day_offset was explicitly set)
        if target <= now and day_offset == 0 and "today" not in expr:
            target += timedelta(days=1)

        return target, recurrence

    # 6. Fallback: If only a day is given (e.g. "tomorrow"), default to 9:00 AM
    if "tomorrow" in expr:
        tomorrow_date = (now + timedelta(days=1)).date()
        return datetime(tomorrow_date.year, tomorrow_date.month, tomorrow_date.day, 9, 0, 0), recurrence

    return None, recurrence


def parse_alarm_time(time_str: str) -> Optional[str]:
    """Parse time string into normalized 'HH:MM' (24-hour) format."""
    s = time_str.strip().lower()
    m = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b", s)
    if not m:
        return None
    hr = int(m.group(1))
    mn = int(m.group(2)) if m.group(2) else 0
    meridiem = m.group(3)

    if meridiem:
        if meridiem == "pm" and hr < 12:
            hr += 12
        elif meridiem == "am" and hr == 12:
            hr = 0
    elif hr < 7 and mn == 0:
        # Default typical alarm hours (e.g. "6" -> 06:00, "7" -> 07:00)
        pass

    if 0 <= hr <= 23 and 0 <= mn <= 59:
        return f"{hr:02d}:{mn:02d}"
    return None


# ============================================================================
# TaskManager Engine
# ============================================================================

class TaskManager:
    """Manages persistent to-dos, reminders, and alarms."""

    def __init__(self, data_path: Optional[str] = None):
        self._path = Path(data_path or TASK_DATA_FILE)
        self.todos: List[TodoItem] = []
        self.reminders: List[ReminderItem] = []
        self.alarms: List[AlarmItem] = []
        self.load()

    # ------------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------------

    def load(self) -> None:
        """Load data from JSON file with corrupt-file safety."""
        if not self._path.exists():
            return
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.todos = [TodoItem.from_dict(d) for d in data.get("todos", [])]
            self.reminders = [ReminderItem.from_dict(d) for d in data.get("reminders", [])]
            self.alarms = [AlarmItem.from_dict(d) for d in data.get("alarms", [])]
        except Exception:
            # If corrupted, start with fresh lists but preserve existing file as backup
            backup = self._path.with_suffix(".corrupt.bak")
            try:
                if self._path.exists():
                    self._path.replace(backup)
            except Exception:
                pass
            self.todos = []
            self.reminders = []
            self.alarms = []

    def save(self) -> None:
        """Atomic write to disk to prevent partial corruption."""
        data = {
            "version": 1,
            "todos": [t.to_dict() for t in self.todos],
            "reminders": [r.to_dict() for r in self.reminders],
            "alarms": [a.to_dict() for a in self.alarms],
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
            tmp.replace(self._path)
        except Exception:
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    # ------------------------------------------------------------------------
    # To-Do List Operations
    # ------------------------------------------------------------------------

    def add_todo(
        self,
        title: str,
        priority: str = "medium",
        category: str = "general",
        due_date: Optional[str] = None,
    ) -> TodoItem:
        item = TodoItem(
            id=f"todo_{uuid.uuid4().hex[:6]}",
            title=title.strip(),
            priority=priority.lower(),
            category=category.lower(),
            due_date=due_date,
        )
        self.todos.append(item)
        self.save()
        return item

    def get_todos(self, filter_mode: str = "pending") -> List[TodoItem]:
        """filter_mode: 'pending', 'completed', or 'all'."""
        if filter_mode == "pending":
            return [t for t in self.todos if not t.completed]
        if filter_mode == "completed":
            return [t for t in self.todos if t.completed]
        return list(self.todos)

    def complete_todo(self, query: str) -> Optional[TodoItem]:
        """Mark a task completed by ID or substring match."""
        q = query.strip().lower()
        for t in self.todos:
            if t.id.lower() == q or q in t.title.lower():
                t.completed = True
                t.completed_at = datetime.now().isoformat()
                self.save()
                return t
        return None

    def delete_todo(self, query: str) -> bool:
        """Delete a task by ID or substring match."""
        q = query.strip().lower()
        initial = len(self.todos)
        self.todos = [t for t in self.todos if not (t.id.lower() == q or q in t.title.lower())]
        if len(self.todos) < initial:
            self.save()
            return True
        return False

    def clear_completed_todos(self) -> int:
        initial = len(self.todos)
        self.todos = [t for t in self.todos if not t.completed]
        cleared = initial - len(self.todos)
        if cleared > 0:
            self.save()
        return cleared

    # ------------------------------------------------------------------------
    # Reminder Operations
    # ------------------------------------------------------------------------

    def add_reminder(
        self,
        message: str,
        due_time: datetime,
        recurrence: str = "none",
    ) -> ReminderItem:
        item = ReminderItem(
            id=f"rem_{uuid.uuid4().hex[:6]}",
            message=message.strip(),
            due_time=due_time.isoformat(),
            recurrence=recurrence,
            status="pending",
        )
        self.reminders.append(item)
        self.save()
        return item

    def get_reminders(self, status: str = "pending") -> List[ReminderItem]:
        if status == "all":
            return list(self.reminders)
        return [r for r in self.reminders if r.status == status]

    def dismiss_reminder(self, reminder_id: str) -> bool:
        for r in self.reminders:
            if r.id == reminder_id or reminder_id in r.message.lower():
                r.status = "dismissed"
                self.save()
                return True
        return False

    def delete_reminder(self, reminder_id: str) -> bool:
        orig_count = len(self.reminders)
        self.reminders = [r for r in self.reminders if r.id != reminder_id and reminder_id not in r.message.lower()]
        if len(self.reminders) != orig_count:
            self.save()
            return True
        return False

    def snooze_reminder(self, reminder_id: str, minutes: int = 5) -> Optional[ReminderItem]:
        for r in self.reminders:
            if r.id == reminder_id or reminder_id in r.message.lower():
                snooze_dt = datetime.now() + timedelta(minutes=minutes)
                r.snoozed_until = snooze_dt.isoformat()
                r.status = "pending"
                self.save()
                return r
        return None

    # ------------------------------------------------------------------------
    # Alarm Operations
    # ------------------------------------------------------------------------

    def add_alarm(
        self,
        time_str: str,
        label: str = "Alarm",
        days: Optional[List[str]] = None,
    ) -> Optional[AlarmItem]:
        normalized = parse_alarm_time(time_str)
        if not normalized:
            return None
        item = AlarmItem(
            id=f"alm_{uuid.uuid4().hex[:6]}",
            time_str=normalized,
            label=label.strip() or "Alarm",
            days=days or ["all"],
            enabled=True,
            status="active",
        )
        self.alarms.append(item)
        self.save()
        return item

    def get_alarms(self) -> List[AlarmItem]:
        return list(self.alarms)

    def toggle_alarm(self, alarm_id: str, enabled: Optional[bool] = None) -> Optional[AlarmItem]:
        for a in self.alarms:
            if a.id == alarm_id or alarm_id in a.label.lower():
                a.enabled = (not a.enabled) if enabled is None else bool(enabled)
                a.status = "active" if a.enabled else "dismissed"
                self.save()
                return a
        return None

    def delete_alarm(self, alarm_id: str) -> bool:
        initial = len(self.alarms)
        self.alarms = [a for a in self.alarms if not (a.id == alarm_id or alarm_id in a.label.lower())]
        if len(self.alarms) < initial:
            self.save()
            return True
        return False

    # ------------------------------------------------------------------------
    # Due Checking (Active Heartbeat)
    # ------------------------------------------------------------------------

    def check_due_items(
        self,
        current_dt: Optional[datetime] = None,
    ) -> Tuple[List[ReminderItem], List[AlarmItem]]:
        """Check for reminders and alarms that are due right now."""
        now = current_dt or datetime.now()
        due_reminders: List[ReminderItem] = []
        due_alarms: List[AlarmItem] = []
        changed = False

        # Check Reminders
        for r in self.reminders:
            if r.status != "pending":
                continue

            target_iso = r.snoozed_until or r.due_time
            try:
                target_dt = datetime.fromisoformat(target_iso)
            except Exception:
                continue

            if now >= target_dt:
                due_reminders.append(r)
                r.status = "triggered"
                changed = True

                # Handle recurrence
                if r.recurrence == "daily":
                    next_dt = target_dt + timedelta(days=1)
                    r.due_time = next_dt.isoformat()
                    r.snoozed_until = None
                    r.status = "pending"
                elif r.recurrence == "weekdays":
                    next_dt = target_dt + timedelta(days=1)
                    while next_dt.weekday() >= 5:  # Skip Sat & Sun
                        next_dt += timedelta(days=1)
                    r.due_time = next_dt.isoformat()
                    r.snoozed_until = None
                    r.status = "pending"
                elif r.recurrence == "weekly":
                    next_dt = target_dt + timedelta(days=7)
                    r.due_time = next_dt.isoformat()
                    r.snoozed_until = None
                    r.status = "pending"

        # Check Alarms
        today_str = now.strftime("%Y-%m-%d")
        current_time_str = now.strftime("%H:%M")
        current_day_short = DAYS_OF_WEEK[now.weekday()]

        for a in self.alarms:
            if not a.enabled:
                continue
            if a.last_triggered_date == today_str:
                continue

            # Check day filter
            if "all" not in a.days and current_day_short not in a.days:
                continue

            if current_time_str == a.time_str:
                due_alarms.append(a)
                a.last_triggered_date = today_str
                a.status = "ringing"
                changed = True

        if changed:
            self.save()

        return due_reminders, due_alarms

    # ------------------------------------------------------------------------
    # Daily Summary Helper for Morning Greeting
    # ------------------------------------------------------------------------

    def get_daily_summary(self, current_dt: Optional[datetime] = None) -> Dict[str, Any]:
        """Provides a structured summary for the wake-up greeting."""
        now = current_dt or datetime.now()
        pending_todos = self.get_todos("pending")
        active_alarms = [a for a in self.alarms if a.enabled]
        pending_reminders = self.get_reminders("pending")

        today_reminders = []
        for r in pending_reminders:
            try:
                dt = datetime.fromisoformat(r.snoozed_until or r.due_time)
                if dt.date() == now.date():
                    today_reminders.append(r)
            except Exception:
                pass

        return {
            "pending_todo_count": len(pending_todos),
            "pending_todos": [t.title for t in pending_todos[:3]],
            "active_alarm_count": len(active_alarms),
            "today_reminder_count": len(today_reminders),
            "today_reminders": [r.message for r in today_reminders[:2]],
        }


# Global instance singleton
_default_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    global _default_manager
    if _default_manager is None:
        _default_manager = TaskManager()
    return _default_manager


# ============================================================================
# Tool Functions for AI & Offline Execution
# ============================================================================

def tool_add_todo(
    title: str,
    priority: str = "medium",
    category: str = "general",
    due_date: str = "",
) -> str:
    """Add a new task to the user's to-do list."""
    tm = get_task_manager()
    due = due_date.strip() if due_date else None
    item = tm.add_todo(title, priority=priority, category=category, due_date=due)
    pri_badge = {"high": "[HIGH]", "low": "[LOW]"}.get(item.priority, "[MED]")
    return f"Added task: {pri_badge} '{item.title}' (Category: {item.category}, Due: {item.due_date or 'None'}, ID: {item.id})"


def tool_list_todos(filter_mode: str = "pending") -> str:
    """List tasks from the to-do list."""
    tm = get_task_manager()
    todos = tm.get_todos(filter_mode)
    if not todos:
        return f"No {filter_mode} tasks found in your to-do list."
    lines = [f"To-Do List ({len(todos)} {filter_mode}):"]
    for i, t in enumerate(todos, start=1):
        status_box = "[x]" if t.completed else "[ ]"
        pri = {"high": "[HIGH]", "low": "[LOW]"}.get(t.priority, "[MED]")
        due_str = f" (Due: {t.due_date})" if t.due_date else ""
        lines.append(f"{i}. {status_box} {pri} {t.title}{due_str} (ID: {t.id})")
    return "\n".join(lines)


def tool_complete_todo(query: str) -> str:
    """Mark a task completed by title or ID."""
    tm = get_task_manager()
    item = tm.complete_todo(query)
    if item:
        return f"Completed task: '{item.title}' (ID: {item.id})"
    return f"No matching task found for '{query}'."


def tool_delete_todo(query: str) -> str:
    """Delete a task or clear completed tasks."""
    tm = get_task_manager()
    if query.strip().lower() in ("completed", "done", "clear completed"):
        cleared = tm.clear_completed_todos()
        return f"Cleared {cleared} completed task(s)."
    deleted = tm.delete_todo(query)
    if deleted:
        return f"Deleted task matching '{query}'."
    return f"No matching task found for '{query}'."


def tool_set_reminder(message: str, time_expr: str) -> str:
    """Set a reminder using natural language time expression."""
    tm = get_task_manager()
    dt, rec = parse_natural_datetime(time_expr)
    if not dt:
        return f"Could not understand time '{time_expr}'. Try 'in 15 minutes', 'at 4:30 pm', or 'tomorrow at 9am'."
    item = tm.add_reminder(message, dt, recurrence=rec)
    now = datetime.now()
    diff = dt - now
    if diff.total_seconds() > 0:
        mins = int(diff.total_seconds() // 60)
        time_hint = f"in {mins} min(s)" if mins < 60 else f"in {mins // 60}h {mins % 60}m"
    else:
        time_hint = "now"
    rec_str = f" [Recurring: {rec}]" if rec != "none" else ""
    return f"Reminder set: '{item.message}' for {dt.strftime('%Y-%m-%d %I:%M %p')} ({time_hint}){rec_str}. (ID: {item.id})"


def tool_list_reminders(status: str = "pending") -> str:
    """List reminders by status."""
    tm = get_task_manager()
    rems = tm.get_reminders(status)
    if not rems:
        return f"No {status} reminders found."
    lines = [f"Reminders ({len(rems)} {status}):"]
    for i, r in enumerate(rems, start=1):
        target_iso = r.snoozed_until or r.due_time
        try:
            target_dt = datetime.fromisoformat(target_iso)
            time_display = target_dt.strftime("%b %d, %I:%M %p")
        except Exception:
            time_display = target_iso
        snooze_str = " (Snoozed)" if r.snoozed_until else ""
        rec_str = f" [{r.recurrence}]" if r.recurrence != "none" else ""
        lines.append(f"{i}. '{r.message}' at {time_display}{snooze_str}{rec_str} (ID: {r.id})")
    return "\n".join(lines)


def tool_dismiss_reminder(query: str) -> str:
    """Dismiss a reminder by message keyword or ID."""
    tm = get_task_manager()
    dismissed = tm.dismiss_reminder(query)
    if dismissed:
        return f"Dismissed reminder matching '{query}'."
    return f"No matching reminder found for '{query}'."


def tool_delete_reminder(query: str) -> str:
    """Delete a reminder completely by message keyword or ID."""
    tm = get_task_manager()
    deleted = tm.delete_reminder(query)
    if deleted:
        return f"Deleted reminder matching '{query}'."
    return f"No matching reminder found for '{query}'."


def tool_snooze_reminder(query: str, minutes: int = 5) -> str:
    """Snooze a reminder for N minutes."""
    tm = get_task_manager()
    r = tm.snooze_reminder(query, minutes=minutes)
    if r:
        return f"Snoozed reminder '{r.message}' for {minutes} minute(s)."
    return f"No matching reminder found for '{query}'."


def tool_set_alarm(time_str: str, label: str = "Alarm", days: str = "all") -> str:
    """Set a daily or scheduled alarm."""
    tm = get_task_manager()
    day_list = [d.strip() for d in days.split(",") if d.strip()] if days != "all" else ["all"]
    alarm = tm.add_alarm(time_str, label=label, days=day_list)
    if not alarm:
        return f"Could not parse alarm time '{time_str}'. Please use format like '07:30' or '7:30 AM'."
    days_str = ", ".join(alarm.days)
    return f"Alarm set for {alarm.time_str} (Label: '{alarm.label}', Days: {days_str}, ID: {alarm.id})"


def tool_list_alarms() -> str:
    """List all alarms."""
    tm = get_task_manager()
    alarms = tm.get_alarms()
    if not alarms:
        return "No alarms configured."
    lines = [f"Alarms ({len(alarms)}):"]
    for i, a in enumerate(alarms, start=1):
        status = "ON" if a.enabled else "OFF"
        days_str = ", ".join(a.days)
        lines.append(f"{i}. [{status}] {a.time_str} - '{a.label}' ({days_str}) (ID: {a.id})")
    return "\n".join(lines)


def tool_toggle_alarm(alarm_id: str, enabled: bool = True) -> str:
    """Enable or disable an alarm."""
    tm = get_task_manager()
    a = tm.toggle_alarm(alarm_id, enabled=enabled)
    if a:
        status = "enabled" if a.enabled else "disabled"
        return f"Alarm '{a.label}' at {a.time_str} is now {status}."
    return f"No alarm found matching '{alarm_id}'."


def tool_delete_alarm(alarm_id: str) -> str:
    """Delete an alarm by ID or label."""
    tm = get_task_manager()
    deleted = tm.delete_alarm(alarm_id)
    if deleted:
        return f"Deleted alarm matching '{alarm_id}'."
    return f"No alarm found matching '{alarm_id}'."


# Tool Specifications
TASK_TOOL_SPECS: List[Dict[str, Any]] = [
    {
        "name": "add_todo",
        "description": "Add a task to the user's to-do list. Use when the user asks to add a todo, remember a task, or create a checklist item.",
        "properties": {
            "title": {"type": "string", "description": "The task title or description."},
            "priority": {"type": "string", "enum": ["low", "medium", "high"], "description": "Priority level (default 'medium')."},
            "category": {"type": "string", "description": "Category such as 'work', 'personal', 'shopping', 'study'."},
            "due_date": {"type": "string", "description": "Optional due date in YYYY-MM-DD format."},
        },
        "required": ["title"],
        "fn": tool_add_todo,
    },
    {
        "name": "list_todos",
        "description": "List the user's to-do items. Use when the user asks to show, view, or check their todo list or pending tasks.",
        "properties": {
            "filter_mode": {"type": "string", "enum": ["pending", "completed", "all"], "description": "Filter by task status."}
        },
        "required": [],
        "fn": tool_list_todos,
    },
    {
        "name": "complete_todo",
        "description": "Mark a task completed on the to-do list. Use when the user says done, finished, or completed a task.",
        "properties": {
            "query": {"type": "string", "description": "Task ID or keyword from the task title."}
        },
        "required": ["query"],
        "fn": tool_complete_todo,
    },
    {
        "name": "delete_todo",
        "description": "Delete a task from the to-do list or clear completed tasks.",
        "properties": {
            "query": {"type": "string", "description": "Task ID, keyword from the title, or 'completed' to clear finished tasks."}
        },
        "required": ["query"],
        "fn": tool_delete_todo,
    },
    {
        "name": "set_reminder",
        "description": "Set a reminder for a specific time or relative interval. Use when the user asks to remind them of something.",
        "properties": {
            "message": {"type": "string", "description": "The reminder text or note."},
            "time_expr": {"type": "string", "description": "Time expression like 'in 15 minutes', 'at 4:30 pm', 'tomorrow 9am', or 'everyday at 8am'."},
        },
        "required": ["message", "time_expr"],
        "fn": tool_set_reminder,
    },
    {
        "name": "list_reminders",
        "description": "List scheduled reminders. Use when the user asks to see upcoming reminders.",
        "properties": {
            "status": {"type": "string", "enum": ["pending", "triggered", "all"], "description": "Filter by status."}
        },
        "required": [],
        "fn": tool_list_reminders,
    },
    {
        "name": "dismiss_reminder",
        "description": "Dismiss a reminder so it no longer alerts.",
        "properties": {
            "query": {"type": "string", "description": "Reminder ID or keyword from message."}
        },
        "required": ["query"],
        "fn": tool_dismiss_reminder,
    },
    {
        "name": "delete_reminder",
        "description": "Delete a reminder completely.",
        "properties": {
            "query": {"type": "string", "description": "Reminder ID or message keyword."}
        },
        "required": ["query"],
        "fn": tool_delete_reminder,
    },
    {
        "name": "snooze_reminder",
        "description": "Snooze a reminder for a specified number of minutes.",
        "properties": {
            "query": {"type": "string", "description": "Reminder ID or keyword from message."},
            "minutes": {"type": "integer", "description": "Minutes to snooze (default 5)."},
        },
        "required": ["query"],
        "fn": tool_snooze_reminder,
    },
    {
        "name": "set_alarm",
        "description": "Set a daily or scheduled alarm time. Use when the user asks to set an alarm or wake them up at a time.",
        "properties": {
            "time_str": {"type": "string", "description": "Alarm time, e.g. '07:30', '7:00 AM', '6:30'."},
            "label": {"type": "string", "description": "Alarm label or reason, e.g. 'Morning Wake Up'."},
            "days": {"type": "string", "description": "Comma-separated days, e.g. 'Mon,Tue,Wed,Thu,Fri', or 'all'."},
        },
        "required": ["time_str"],
        "fn": tool_set_alarm,
    },
    {
        "name": "list_alarms",
        "description": "List all configured alarms and their status.",
        "properties": {},
        "required": [],
        "fn": tool_list_alarms,
    },
    {
        "name": "toggle_alarm",
        "description": "Turn an alarm on or off.",
        "properties": {
            "alarm_id": {"type": "string", "description": "Alarm ID or label keyword."},
            "enabled": {"type": "boolean", "description": "True to enable, False to disable."},
        },
        "required": ["alarm_id", "enabled"],
        "fn": tool_toggle_alarm,
    },
    {
        "name": "delete_alarm",
        "description": "Delete an alarm completely.",
        "properties": {
            "alarm_id": {"type": "string", "description": "Alarm ID or label keyword."}
        },
        "required": ["alarm_id"],
        "fn": tool_delete_alarm,
    },
]

TASK_TOOL_FUNCTIONS = {spec["name"]: spec["fn"] for spec in TASK_TOOL_SPECS}

