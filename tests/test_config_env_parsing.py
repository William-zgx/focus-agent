from __future__ import annotations

import pytest

from focus_agent.config import Settings
from focus_agent.config_parts.env import env_bool, env_float, env_int, parse_bool


@pytest.mark.parametrize("raw", ["1", "true", " TRUE ", "Yes", "on\n"])
def test_parse_bool_recognises_true_values(raw: str):
    assert parse_bool(raw) is True


@pytest.mark.parametrize("raw", ["0", "false", " False ", "NO", "off"])
def test_parse_bool_recognises_false_values(raw: str):
    assert parse_bool(raw) is False


@pytest.mark.parametrize("raw", [None, "", "  ", "maybe", "2"])
def test_parse_bool_returns_none_for_unknown_values(raw: object):
    assert parse_bool(raw) is None


def test_parse_bool_passes_through_bools():
    assert parse_bool(True) is True
    assert parse_bool(False) is False


@pytest.mark.parametrize(
    ("env", "default", "expected"),
    [
        ({}, True, True),
        ({}, False, False),
        ({"FLAG": " true "}, False, True),
        ({"FLAG": "OFF"}, True, False),
        ({"FLAG": "garbage"}, True, True),
        ({"FLAG": "garbage"}, False, False),
        ({"FLAG": ""}, True, True),
    ],
)
def test_env_bool_strips_casefolds_and_falls_back(env, default, expected):
    assert env_bool(env, "FLAG", default=default) is expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 7), ("", 7), ("  ", 7), (" 12 ", 12), ("-3", -3), ("1.5", 7), ("abc", 7)],
)
def test_env_int_parses_or_returns_default(raw, expected):
    env = {} if raw is None else {"N": raw}
    assert env_int(env, "N", 7) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [(None, 0.5), ("", 0.5), (" 2.25 ", 2.25), ("3", 3.0), ("abc", 0.5)],
)
def test_env_float_parses_or_returns_default(raw, expected):
    env = {} if raw is None else {"F": raw}
    assert env_float(env, "F", 0.5) == expected


def test_settings_from_env_tolerates_whitespace_and_invalid_numbers(monkeypatch, tmp_path):
    monkeypatch.setenv("FOCUS_AGENT_LOCAL_ENV_FILE", str(tmp_path / "missing-local.env"))
    monkeypatch.setenv("API_RELOAD", " TRUE ")
    monkeypatch.setenv("API_PORT", "not-a-port")
    monkeypatch.setenv("BRANCH_MAX_DEPTH", " 4 ")

    settings = Settings.from_env()

    assert settings.api_reload is True
    assert settings.api_port == Settings().api_port
    assert settings.branch_max_depth == 4
