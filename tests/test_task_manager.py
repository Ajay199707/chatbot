"""
tests/test_task_manager.py - Unit tests for task_manager.py
"""

from datetime import datetime, timedelta
import pytest
from task_manager import (
    TaskManager,
    TodoItem,
    ReminderItem,
    AlarmItem,
    parse_natural_datetime,
    parse_alarm_time,
)


def test_parse_natural_datetime_relative():
    base = datetime(2026, 11, 16, 10, 0, 0)

    # In 10 minutes
    dt, rec = parse_natural_datetime("in 10 minutes", reference_dt=base)
    assert dt == base + timedelta(minutes=10)
    assert rec == "none"

    # In 5 mins
    dt, _ = parse_natural_datetime("in 5 mins", reference_dt=base)
    assert dt == base + timedelta(minutes=5)

    # In 2 hours
    dt, _ = parse_natural_datetime("in 2 hours", reference_dt=base)
    assert dt == base + timedelta(hours=2)

    # In 30 seconds
    dt, _ = parse_natural_datetime("in 30s", reference_dt=base)
    assert dt == base + timedelta(seconds=30)


def test_parse_natural_datetime_clock_time():
    base = datetime(2026, 11, 16, 10, 0, 0)

    # Later today at 4:30 PM
    dt, rec = parse_natural_datetime("at 4:30 pm", reference_dt=base)
    assert dt == datetime(2026, 11, 16, 16, 30, 0)
    assert rec == "none"

    # Time in the past rolls over to tomorrow if today not explicitly specified
    dt, _ = parse_natural_datetime("at 8:00 am", reference_dt=base)
    assert dt == datetime(2026, 11, 17, 8, 0, 0)

    # Tomorrow at 9:00 AM
    dt, _ = parse_natural_datetime("tomorrow at 9:00 am", reference_dt=base)
    assert dt == datetime(2026, 11, 17, 9, 0, 0)


def test_parse_natural_datetime_recurring():
    base = datetime(2026, 11, 16, 10, 0, 0)

    dt, rec = parse_natural_datetime("everyday at 8:00 am", reference_dt=base)
    assert rec == "daily"
    assert dt.hour == 8

    _, rec = parse_natural_datetime("weekdays at 9am", reference_dt=base)
    assert rec == "weekdays"

    _, rec = parse_natural_datetime("every week at 10am", reference_dt=base)
    assert rec == "weekly"


def test_parse_alarm_time():
    assert parse_alarm_time("7:30 am") == "07:30"
    assert parse_alarm_time("7:30 pm") == "19:30"
    assert parse_alarm_time("07:00") == "07:00"
    assert parse_alarm_time("21:45") == "21:45"
    assert parse_alarm_time("invalid text") is None


def test_todo_crud_and_persistence(tmp_path):
    data_file = tmp_path / "test_tasks.json"
    tm = TaskManager(str(data_file))

    # Add todos
    t1 = tm.add_todo("Buy groceries", priority="high", category="shopping")
    t2 = tm.add_todo("Prepare project report", priority="high", category="work")
    assert len(tm.get_todos("pending")) == 2

    # Complete todo
    completed = tm.complete_todo("groceries")
    assert completed is not None
    assert completed.completed is True
    assert len(tm.get_todos("pending")) == 1
    assert len(tm.get_todos("completed")) == 1

    # Reload from file to verify persistence
    tm2 = TaskManager(str(data_file))
    assert len(tm2.get_todos("pending")) == 1
    assert tm2.get_todos("pending")[0].title == "Prepare project report"

    # Delete todo
    assert tm2.delete_todo("report") is True
    assert len(tm2.get_todos("all")) == 1

    # Clear completed
    cleared = tm2.clear_completed_todos()
    assert cleared == 1
    assert len(tm2.get_todos("all")) == 0


def test_reminder_crud_and_due_check(tmp_path):
    data_file = tmp_path / "test_reminders.json"
    tm = TaskManager(str(data_file))

    base = datetime(2026, 11, 16, 10, 0, 0)
    due_dt = base + timedelta(minutes=5)

    rem = tm.add_reminder("Take a stretch break", due_time=due_dt)
    assert rem.status == "pending"

    # Check due when before due time
    due_rems, _ = tm.check_due_items(current_dt=base + timedelta(minutes=2))
    assert len(due_rems) == 0

    # Check due when past due time
    due_rems, _ = tm.check_due_items(current_dt=base + timedelta(minutes=6))
    assert len(due_rems) == 1
    assert due_rems[0].message == "Take a stretch break"

    # Snooze reminder
    snoozed = tm.snooze_reminder(rem.id, minutes=10)
    assert snoozed is not None
    assert snoozed.status == "pending"
    assert snoozed.snoozed_until is not None

    # Dismiss reminder
    assert tm.dismiss_reminder(rem.id) is True
    assert len(tm.get_reminders("pending")) == 0


def test_alarm_crud_and_due_check(tmp_path):
    data_file = tmp_path / "test_alarms.json"
    tm = TaskManager(str(data_file))

    alarm = tm.add_alarm("08:00", label="Morning Standup", days=["Mon", "Tue"])
    assert alarm is not None
    assert alarm.time_str == "08:00"
    assert alarm.enabled is True

    # 2026-11-16 is a Monday
    monday_8am = datetime(2026, 11, 16, 8, 0, 0)
    _, due_alarms = tm.check_due_items(current_dt=monday_8am)
    assert len(due_alarms) == 1
    assert due_alarms[0].label == "Morning Standup"

    # Check same day again -> should not trigger twice
    _, due_alarms2 = tm.check_due_items(current_dt=monday_8am)
    assert len(due_alarms2) == 0

    # Toggle off
    tm.toggle_alarm(alarm.id, enabled=False)
    assert alarm.enabled is False

    # Delete alarm
    assert tm.delete_alarm(alarm.id) is True
    assert len(tm.get_alarms()) == 0


def test_daily_summary(tmp_path):
    data_file = tmp_path / "test_summary.json"
    tm = TaskManager(str(data_file))

    tm.add_todo("Write test cases", priority="high")
    tm.add_todo("Review pull request")
    tm.add_alarm("09:00", label="Daily Wakeup")
    tm.add_reminder("Call client", due_time=datetime(2026, 11, 16, 15, 0, 0))

    summary = tm.get_daily_summary(current_dt=datetime(2026, 11, 16, 8, 0, 0))
    assert summary["pending_todo_count"] == 2
    assert summary["active_alarm_count"] == 1
    assert summary["today_reminder_count"] == 1
    assert "Call client" in summary["today_reminders"]
