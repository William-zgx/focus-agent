import json

from langchain.messages import AIMessage, ToolMessage

from focus_agent.engine.graph_evidence import (
    EVIDENCE_LAYER_SNIPPET,
    TRUST_TIER_BACKGROUND,
    TRUST_TIER_HIGH,
    TRUST_TIER_LOW,
    TRUST_TIER_MEDIUM,
    evidence_bundle_source_snippets,
    evidence_bundle_to_citation_refs,
    normalize_evidence_bundle,
    normalize_evidence_ledger,
)


def _tool_call(call_id: str, name: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"id": call_id, "name": name, "args": {}}])


def _tool_message(call_id: str, payload: dict[str, object], *, tool_name: str = "") -> ToolMessage:
    artifact = {"tool_name": tool_name} if tool_name else None
    return ToolMessage(
        content=json.dumps(payload),
        tool_call_id=call_id,
        artifact=artifact,
    )


def test_normalize_evidence_bundle_marks_government_official_source_high():
    bundle = normalize_evidence_bundle(
        [
            _tool_call("search-1", "web_search"),
            _tool_message(
                "search-1",
                {
                    "query": "cdc flu guidance",
                    "provider": "tavily",
                    "results": [
                        {
                            "title": "Influenza guidance",
                            "url": "https://www.cdc.gov/flu/treatment/index.html",
                            "content": "CDC guidance for clinicians on influenza treatment.",
                        }
                    ],
                },
            ),
        ],
        observed_at="2026-05-14T00:00:00Z",
    )

    assert bundle == [
        {
            "source_name": "cdc.gov",
            "url": "https://www.cdc.gov/flu/treatment/index.html",
            "title": "Influenza guidance",
            "snippet": "CDC guidance for clinicians on influenza treatment.",
            "trust_tier": TRUST_TIER_HIGH,
            "observed_at": "2026-05-14T00:00:00Z",
        }
    ]
    assert evidence_bundle_to_citation_refs(bundle) == [
        {
            "label": "Influenza guidance",
            "uri": "https://www.cdc.gov/flu/treatment/index.html",
            "quote": "CDC guidance for clinicians on influenza treatment.",
            "source_artifact_id": None,
        }
    ]


def test_normalize_evidence_bundle_marks_recognized_news_medium():
    bundle = normalize_evidence_bundle(
        [
            _tool_call("search-1", "web_search"),
            _tool_message(
                "search-1",
                {
                    "query": "market update",
                    "provider": "duckduckgo",
                    "results": [
                        {
                            "title": "Markets rise",
                            "url": "https://www.reuters.com/markets/example",
                            "content": "Reuters reported a broad market rally.",
                        }
                    ],
                },
            ),
        ],
        observed_at="2026-05-14T00:00:00Z",
    )

    assert bundle[0]["source_name"] == "reuters.com"
    assert bundle[0]["trust_tier"] == TRUST_TIER_MEDIUM


def test_search_results_are_snippets_and_keep_publication_and_observation_times():
    ledger = normalize_evidence_ledger(
        [
            _tool_call("search-1", "web_search"),
            _tool_message(
                "search-1",
                {
                    "query": "market update",
                    "provider": "duckduckgo",
                    "results": [
                        {
                            "title": "Markets rise",
                            "url": "https://www.reuters.com/markets/example",
                            "content": "Reuters reported a broad market rally.",
                            "published_at": "2026-05-13",
                            "observed_at": "2026-05-13T12:00:00Z",
                        }
                    ],
                },
            ),
        ],
        observed_at="2026-05-14T00:00:00Z",
    )

    assert ledger[0]["evidence_layer"] == EVIDENCE_LAYER_SNIPPET
    assert ledger[0]["published_at"] == "2026-05-13"
    assert ledger[0]["observed_at"] == "2026-05-13T12:00:00Z"


def test_context_truncated_web_payload_keeps_source_snippets_not_internal_summary():
    messages = [
        _tool_call("search-1", "web_search"),
        _tool_message(
            "search-1",
            {
                "query": "market update",
                "truncated_by_context_policy": True,
                "summary": "Prompt-only artifactized view.",
                "results": [
                    {
                        "title": "Markets rise",
                        "url": "https://www.reuters.com/markets/example",
                        "content": "Representative result kept in the compact view.",
                    }
                ],
            },
        ),
    ]

    bundle = normalize_evidence_bundle(messages)
    ledger = normalize_evidence_ledger(messages)
    assert len(bundle) == len(ledger) == 1
    assert ledger[0]["evidence_layer"] == "snippet"
    assert bundle[0]["snippet"] == "Representative result kept in the compact view."
    assert "Prompt-only" not in str(bundle)


def test_empty_web_fetch_result_is_low_trust_not_strong_evidence():
    bundle = normalize_evidence_bundle(
        [
            _tool_call("fetch-1", "web_fetch"),
            _tool_message(
                "fetch-1",
                {
                    "url": "https://www.sec.gov/news",
                    "final_url": "https://www.sec.gov/news",
                    "title": "SEC News",
                    "content": "",
                    "content_type": "text/html",
                },
            ),
        ],
        observed_at="2026-05-14T00:00:00Z",
    )

    assert bundle[0]["source_name"] == "sec.gov"
    assert bundle[0]["snippet"] == ""
    assert bundle[0]["trust_tier"] == TRUST_TIER_LOW
    assert not any(item["trust_tier"] in {TRUST_TIER_HIGH, TRUST_TIER_MEDIUM} for item in bundle)


def test_monthly_climate_weather_pages_are_background_sources():
    bundle = normalize_evidence_bundle(
        [
            _tool_call("fetch-1", "web_fetch"),
            _tool_message(
                "fetch-1",
                {
                    "url": "https://weather.com/weather/monthly/l/New+York+NY",
                    "final_url": "https://weather.com/weather/monthly/l/New+York+NY",
                    "title": "Monthly Weather in New York",
                    "content": "Average climate values and monthly weather outlooks.",
                },
            ),
        ],
        observed_at="2026-05-14T00:00:00Z",
    )

    assert bundle[0]["trust_tier"] == TRUST_TIER_BACKGROUND
    assert evidence_bundle_source_snippets(bundle) == [
        "- Evidence [background]: weather.com - Monthly Weather in New York "
        "Average climate values and monthly weather outlooks. "
        "(https://weather.com/weather/monthly/l/New+York+NY)"
    ]


def test_web_citation_preserves_long_url_and_ignores_failed_pages():
    url = "https://example.com/" + "long-path/" * 80
    messages = [
        _tool_call("fetch", "web_fetch"),
        _tool_message(
            "fetch",
            {
                "url": url,
                "content": "Source passage",
                "truncated_by_context_policy": True,
                "summary": "Internal processing notice",
            },
        ),
        _tool_call("failed", "web_fetch"),
        _tool_message(
            "failed",
            {"url": "https://example.com/blocked", "status": "error", "error": "Access denied"},
        ),
        _tool_call("search", "web_search"),
        _tool_message(
            "search", {"truncated_by_context_policy": True, "summary": "Internal notice"}
        ),
    ]
    bundle = normalize_evidence_bundle(messages)
    assert len(bundle) == 1
    assert bundle[0]["url"] == url
    assert evidence_bundle_to_citation_refs(bundle)[0]["uri"] == url
