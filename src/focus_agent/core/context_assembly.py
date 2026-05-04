from __future__ import annotations

from . import context_assembly_coercion as _coercion
from . import context_assembly_lines as _lines
from . import context_assembly_rendering as _rendering


_ARTIFACT_LINE_RE = _lines._ARTIFACT_LINE_RE
_ARTIFACT_URI_RE = _lines._ARTIFACT_URI_RE
_LINE_CONFIDENCE_RE = _lines._LINE_CONFIDENCE_RE
_LINE_EVIDENCE_RE = _lines._LINE_EVIDENCE_RE
_LINE_SCORE_RE = _lines._LINE_SCORE_RE
_LINE_SOURCE_PREFIX_RE = _lines._LINE_SOURCE_PREFIX_RE
_PromptArtifactCandidate = _lines._PromptArtifactCandidate
_PromptFindingCandidate = _lines._PromptFindingCandidate
_PromptMemoryCandidate = _lines._PromptMemoryCandidate
_PromptTextCandidate = _lines._PromptTextCandidate
_artifact_dedupe_key = _lines._artifact_dedupe_key
_artifact_line_dedupe_key = _lines._artifact_line_dedupe_key
_artifact_line_rank = _lines._artifact_line_rank
_dedupe_artifact_lines = _lines._dedupe_artifact_lines
_dedupe_finding_lines = _lines._dedupe_finding_lines
_dedupe_memory_lines = _lines._dedupe_memory_lines
_dedupe_preferring_reference = _lines._dedupe_preferring_reference
_dedupe_ranked_lines = _lines._dedupe_ranked_lines
_dedupe_text_lines = _lines._dedupe_text_lines
_extract_line_confidence = _lines._extract_line_confidence
_extract_line_evidence_count = _lines._extract_line_evidence_count
_extract_line_score = _lines._extract_line_score
_extract_numeric = _lines._extract_numeric
_finding_line_dedupe_key = _lines._finding_line_dedupe_key
_finding_line_rank = _lines._finding_line_rank
_first_nonempty_line = _lines._first_nonempty_line
_line_preference = _lines._line_preference
_looks_promoted_line = _lines._looks_promoted_line
_memory_line_dedupe_key = _lines._memory_line_dedupe_key
_memory_line_rank = _lines._memory_line_rank
_normalize_for_dedupe = _lines._normalize_for_dedupe
_semantic_line_key = _lines._semantic_line_key
_strip_line_metadata = _lines._strip_line_metadata
_text_candidate = _lines._text_candidate
_text_candidate_preference = _lines._text_candidate_preference
_text_line_dedupe_key = _lines._text_line_dedupe_key

_artifact_to_line = _coercion._artifact_to_line
_coerce_artifact_lines = _coercion._coerce_artifact_lines
_coerce_constraints = _coercion._coerce_constraints
_coerce_imported_lines = _coercion._coerce_imported_lines
_coerce_legacy_imported_lines = _coercion._coerce_legacy_imported_lines
_coerce_local_finding_lines = _coercion._coerce_local_finding_lines
_coerce_pinned_facts = _coercion._coerce_pinned_facts
_finding_to_line = _coercion._finding_to_line

_block_priority_map = _rendering._block_priority_map
_branch_scope_block = _rendering._branch_scope_block
_context_block_header = _rendering._context_block_header
_context_block_priority = _rendering._context_block_priority
_current_plan_step_goal = _rendering._current_plan_step_goal
_mode_instructions = _rendering._mode_instructions
_render_block_order = _rendering._render_block_order
_render_lines = _rendering._render_lines
_skill_system_block = _rendering._skill_system_block


__all__ = [
    "_branch_scope_block",
    "_coerce_artifact_lines",
    "_coerce_constraints",
    "_coerce_imported_lines",
    "_coerce_legacy_imported_lines",
    "_coerce_local_finding_lines",
    "_coerce_pinned_facts",
    "_context_block_priority",
    "_current_plan_step_goal",
    "_dedupe_artifact_lines",
    "_dedupe_finding_lines",
    "_dedupe_memory_lines",
    "_dedupe_preferring_reference",
    "_dedupe_text_lines",
    "_mode_instructions",
    "_render_block_order",
    "_render_lines",
    "_skill_system_block",
]
