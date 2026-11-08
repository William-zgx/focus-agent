from focus_agent.core.productivity import FocusTaskStatus
from focus_agent.repositories.sqlite_productivity_repository import SQLiteProductivityRepository
from focus_agent.services.productivity import ProductivityService


def test_sqlite_productivity_repository_round_trips_notes_and_tasks(tmp_path):
    repository = SQLiteProductivityRepository(str(tmp_path / "focus.sqlite3"))
    service = ProductivityService(repository)

    note = service.create_note(
        user_id="user-1",
        title="Planning note",
        body="Ship the smallest useful slice.",
        tags=["planning", "planning"],
        source_thread_id="thread-1",
        source_kind="chat_answer",
        source_id="turn-1",
        source_url="/app/chat/thread-1",
        pinned_context={"thread_id": "thread-1"},
        captured_from="chat",
    )
    hidden = service.create_note(user_id="user-2", title="Private", body="Other")
    task = service.create_task(
        user_id="user-1",
        title="Verify API",
        priority=2,
        source_thread_id="thread-1",
        source_note_id=note.note_id,
        source_kind="merge_review",
        source_id="review-1",
        source_url="/app/merge-review/review-1",
        pinned_context={"session_id": "session-1"},
        captured_from="merge_review",
        assignee_user_id="user-1",
    )

    updated_note = service.update_note(note_id=note.note_id, user_id="user-1", body="Updated")
    completed = service.complete_task(task_id=task.task_id, user_id="user-1")

    assert updated_note is not None
    assert updated_note.source_thread_id == "thread-1"
    assert updated_note.source_kind == "chat_answer"
    assert updated_note.source_id == "turn-1"
    assert updated_note.source_url == "/app/chat/thread-1"
    assert updated_note.pinned_context == {"thread_id": "thread-1"}
    assert updated_note.captured_from == "chat"
    assert repository.get_note(note_id=note.note_id, user_id="user-1").body == "Updated"
    assert repository.get_note(note_id=hidden.note_id, user_id="user-1") is None
    assert [item.note_id for item in repository.list_notes(user_id="user-1", query="updated")] == [
        note.note_id
    ]
    assert completed is not None
    assert completed.status == FocusTaskStatus.COMPLETED
    assert completed.source_note_id == note.note_id
    assert completed.source_kind == "merge_review"
    assert completed.source_id == "review-1"
    assert completed.source_url == "/app/merge-review/review-1"
    assert completed.pinned_context == {"session_id": "session-1"}
    assert completed.captured_from == "merge_review"
    assert completed.assignee_user_id == "user-1"
    assert repository.get_task(task_id=task.task_id, user_id="user-2") is None
    assert (
        repository.list_task_events(task_id=task.task_id, user_id="user-1")[-1].kind == "completed"
    )


def test_sqlite_list_notes_filters_tags_before_pagination(tmp_path):
    repository = SQLiteProductivityRepository(str(tmp_path / "focus.sqlite3"))
    service = ProductivityService(repository)
    tagged = service.create_note(user_id="user-1", title="Tagged", body="x", tags=["x", "y"])
    for index in range(3):
        service.create_note(user_id="user-1", title=f"Plain {index}", body="x")

    assert [n.note_id for n in repository.list_notes(user_id="user-1", tags=["x"], limit=1)] == [
        tagged.note_id
    ]
    assert [n.note_id for n in repository.list_notes(user_id="user-1", tags=["x", "y"])] == [
        tagged.note_id
    ]
    assert repository.list_notes(user_id="user-1", tags=["x", "z"]) == []
