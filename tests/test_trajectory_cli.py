from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from focus_agent import trajectory_cli


def test_list_command_passes_filters_and_prints_json(monkeypatch, capsys):
    calls: dict[str, object] = {}

    class FakeRepo:
        def list_turns(self, *, filters, limit, offset):
            calls["filters"] = filters
            calls["limit"] = limit
            calls["offset"] = offset
            return [{"id": "turn-1", "status": "succeeded"}]

    def _create_repo(database_uri: str):
        calls["database_uri"] = database_uri
        return FakeRepo()

    monkeypatch.setenv("DATABASE_URI", "postgresql://example/list")
    monkeypatch.setattr(trajectory_cli, "create_repository", _create_repo)

    exit_code = trajectory_cli.main(
        [
            "list",
            "--request-id",
            "req-1",
            "--trace-id",
            "trace-1",
            "--thread-id",
            "thread-1",
            "--status",
            "succeeded",
            "--tool",
            "read_file",
            "--limit",
            "5",
            "--offset",
            "2",
        ]
    )

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert calls == {
        "database_uri": "postgresql://example/list",
        "filters": {
            "request_id": "req-1",
            "trace_id": "trace-1",
            "thread_id": "thread-1",
            "status": ["succeeded"],
            "tool": ["read_file"],
        },
        "limit": 5,
        "offset": 2,
    }
    assert payload["count"] == 1
    assert payload["items"] == [{"id": "turn-1", "status": "succeeded"}]


def test_show_command_serializes_datetime(monkeypatch, capsys):
    calls: dict[str, object] = {}

    class FakeRepo:
        def get_turn(self, turn_id: str):
            calls["turn_id"] = turn_id
            return {
                "id": turn_id,
                "started_at": datetime(2026, 4, 21, 8, 30, tzinfo=timezone.utc),
            }

    monkeypatch.setenv("DATABASE_URI", "postgresql://example/show")
    monkeypatch.setattr(trajectory_cli, "create_repository", lambda _: FakeRepo())

    exit_code = trajectory_cli.main(["show", "turn-42"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert calls["turn_id"] == "turn-42"
    assert payload["item"] == {
        "id": "turn-42",
        "started_at": "2026-04-21T08:30:00+00:00",
    }


def test_export_command_writes_jsonl_file(monkeypatch, tmp_path, capsys):
    calls: dict[str, object] = {}
    output_path = tmp_path / "trajectory.jsonl"

    class FakeRepo:
        def export_turns(self, *, filters, limit, offset):
            calls["filters"] = filters
            calls["limit"] = limit
            calls["offset"] = offset
            return [
                {"id": "turn-1", "status": "failed"},
                {"id": "turn-2", "status": "succeeded"},
            ]

    monkeypatch.setenv("DATABASE_URI", "postgresql://example/export")
    monkeypatch.setattr(trajectory_cli, "create_repository", lambda _: FakeRepo())

    exit_code = trajectory_cli.main(
        [
            "export",
            "--scene",
            "long_dialog_research",
            "--limit",
            "2",
            "--output",
            str(output_path),
        ]
    )

    assert exit_code == 0
    assert capsys.readouterr().out == ""
    assert calls == {
        "filters": {"scene": ["long_dialog_research"]},
        "limit": 2,
        "offset": 0,
    }
    assert output_path.read_text(encoding="utf-8").splitlines() == [
        '{"id": "turn-1", "status": "failed"}',
        '{"id": "turn-2", "status": "succeeded"}',
    ]


def test_stats_command_prints_json(monkeypatch, capsys):
    class FakeRepo:
        def stats(self, *, filters):
            assert filters == {"fallback_used": True, "has_error": True}
            return {"turns": 3, "failed_turns": 1}

    monkeypatch.setenv("DATABASE_URI", "postgresql://example/stats")
    monkeypatch.setattr(trajectory_cli, "create_repository", lambda _: FakeRepo())

    exit_code = trajectory_cli.main(["stats", "--fallback-used", "--has-error"])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "filters": {"fallback_used": True, "has_error": True},
        "stats": {"failed_turns": 1, "turns": 3},
    }


def test_main_requires_database_uri(monkeypatch):
    monkeypatch.delenv("DATABASE_URI", raising=False)

    with pytest.raises(SystemExit) as excinfo:
        trajectory_cli.main(["list"])

    assert excinfo.value.code == 2
