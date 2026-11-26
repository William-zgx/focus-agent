from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
smoke = importlib.import_module("context_ui_smoke")


def _call(tool_name: str, call_id: str, args: dict) -> dict:
    return {
        "type": "ai",
        "content": "",
        "tool_calls": [{"name": tool_name, "id": call_id, "args": args}],
    }


def _result(call_id: str, payload: dict, *, status: str = "success") -> dict:
    return {
        "type": "tool",
        "tool_call_id": call_id,
        "status": status,
        "content": json.dumps(payload, ensure_ascii=False),
    }


def _read_file_state(*, total_lines: int = 300) -> dict:
    return {
        "messages": [
            _call(
                "read_file",
                "read-1",
                {"path": "evidence.txt", "start_line": 1, "end_line": 300},
            ),
            _result(
                "read-1",
                {"total_lines": total_lines, "content": "1 | first\n300 | last"},
            ),
        ]
    }


def _artifact_state(*, returned_marker: str = "OBS-real") -> dict:
    return {
        "messages": [
            _call(
                "artifact_read",
                "artifact-1",
                {
                    "artifact_id": "tool-observation://read_file/read-1",
                    "offset": 100,
                    "limit": 300,
                },
            ),
            _result("artifact-1", {"content": f"page with {returned_marker}"}),
        ]
    }


def test_read_file_summary_requires_tool_supported_line_count():
    smoke.assert_read_file_summary_evidence(
        _read_file_state(),
        "The file contains 300 lines.",
        filename="evidence.txt",
        start_line=1,
        end_line=300,
        total_lines=300,
    )

    with pytest.raises(AssertionError, match="300-line summary"):
        smoke.assert_read_file_summary_evidence(
            _read_file_state(total_lines=299),
            "The file contains 300 lines.",
            filename="evidence.txt",
            start_line=1,
            end_line=300,
            total_lines=300,
        )


def test_read_file_summary_rejects_longer_number_containing_expected_count():
    with pytest.raises(AssertionError, match="final response is not supported"):
        smoke.assert_read_file_summary_evidence(
            _read_file_state(),
            "The file contains 3000 lines.",
            filename="evidence.txt",
            start_line=1,
            end_line=300,
            total_lines=300,
        )


def test_read_file_summary_allows_default_start_line():
    state = _read_file_state()
    del state["messages"][0]["tool_calls"][0]["args"]["start_line"]

    smoke.assert_read_file_summary_evidence(
        state,
        "The file contains 300 lines.",
        filename="evidence.txt",
        start_line=1,
        end_line=300,
        total_lines=300,
    )


def test_read_file_summary_rejects_range_mention_instead_of_count():
    with pytest.raises(AssertionError, match="final response is not supported"):
        smoke.assert_read_file_summary_evidence(
            _read_file_state(),
            "Read lines 1-300; the file has 301 lines.",
            filename="evidence.txt",
            start_line=1,
            end_line=300,
            total_lines=300,
        )


def test_read_file_summary_returns_call_whose_result_supports_claim():
    state = _read_file_state()
    good_call = state["messages"][0]["tool_calls"][0]
    good_result = state["messages"][1]
    bad_call = {**good_call, "id": "read-bad"}
    bad_result = {
        **good_result,
        "tool_call_id": "read-bad",
        "content": json.dumps({"total_lines": 299}),
    }
    state["messages"].extend(
        [
            {"type": "ai", "tool_calls": [bad_call]},
            bad_result,
        ]
    )

    call = smoke.assert_read_file_summary_evidence(
        state,
        "The file contains 300 lines.",
        filename="evidence.txt",
        start_line=1,
        end_line=300,
        total_lines=300,
    )
    assert call["id"] == "read-1"


def test_read_file_summary_accepts_structured_total_lines_claim():
    smoke.assert_read_file_summary_evidence(
        _read_file_state(),
        "Read completed with total_lines=300.",
        filename="evidence.txt",
        start_line=1,
        end_line=300,
        total_lines=300,
    )


def test_read_file_summary_rejects_model_self_report_without_tool_call():
    with pytest.raises(AssertionError, match="missing read_file tool call"):
        smoke.assert_read_file_summary_evidence(
            {"messages": [{"type": "ai", "content": "The file contains 300 lines."}]},
            "The file contains 300 lines.",
            filename="evidence.txt",
            start_line=1,
            end_line=300,
            total_lines=300,
        )


def test_artifact_readback_accepts_matching_call_result_and_claim():
    smoke.assert_artifact_readback_evidence(
        _artifact_state(),
        "The verification code is OBS-real.",
        artifact_id="tool-observation://read_file/read-1",
        offset=100,
        limit=300,
        marker="OBS-real",
    )


def test_artifact_readback_rejects_claim_without_real_tool_call():
    with pytest.raises(AssertionError, match="missing artifact_read tool call"):
        smoke.assert_artifact_readback_evidence(
            {"messages": [{"type": "ai", "content": "The code is OBS-fake."}]},
            "The code is OBS-fake.",
            artifact_id="tool-observation://read_file/read-1",
            offset=100,
            limit=300,
            marker="OBS-real",
        )


def test_artifact_readback_rejects_fabricated_claim_even_with_tool_call():
    with pytest.raises(AssertionError, match="final response is not supported"):
        smoke.assert_artifact_readback_evidence(
            _artifact_state(),
            "The verification code is OBS-fake.",
            artifact_id="tool-observation://read_file/read-1",
            offset=100,
            limit=300,
            marker="OBS-real",
        )


def test_artifact_readback_rejects_tool_result_without_required_marker():
    with pytest.raises(AssertionError, match="tool result does not contain"):
        smoke.assert_artifact_readback_evidence(
            _artifact_state(returned_marker="OBS-other"),
            "The verification code is OBS-real.",
            artifact_id="tool-observation://read_file/read-1",
            offset=100,
            limit=300,
            marker="OBS-real",
        )


def test_artifact_readback_rejects_failed_tool_result():
    state = _artifact_state()
    state["messages"][1]["status"] = "error"
    with pytest.raises(AssertionError, match="no successful tool result"):
        smoke.assert_artifact_readback_evidence(
            state,
            "The verification code is OBS-real.",
            artifact_id="tool-observation://read_file/read-1",
            offset=100,
            limit=300,
            marker="OBS-real",
        )
