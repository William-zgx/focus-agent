"""Compatibility shim for legacy context policy imports."""

from .context import policy as _policy
from .context.policy import *  # noqa: F401,F403

_estimate_with_tokenizer = _policy._estimate_with_tokenizer
_message_budget_units = _policy._message_budget_units


def approximate_token_count(*args, **kwargs):
    original = _policy._estimate_with_tokenizer
    _policy._estimate_with_tokenizer = _estimate_with_tokenizer
    try:
        return _policy.approximate_token_count(*args, **kwargs)
    finally:
        _policy._estimate_with_tokenizer = original


def apply_prompt_budget_guard(*args, **kwargs):
    original_estimator = _policy._estimate_with_tokenizer
    original_budget_units = _policy._message_budget_units
    _policy._estimate_with_tokenizer = _estimate_with_tokenizer
    _policy._message_budget_units = _message_budget_units
    try:
        return _policy.apply_prompt_budget_guard(*args, **kwargs)
    finally:
        _policy._estimate_with_tokenizer = original_estimator
        _policy._message_budget_units = original_budget_units
