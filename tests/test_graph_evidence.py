import json

from langchain.messages import AIMessage, ToolMessage

from focus_agent.engine.graph_evidence import (
    TRUST_TIER_BACKGROUND,
    TRUST_TIER_HIGH,
    TRUST_TIER_LOW,
    TRUST_TIER_MEDIUM,
    evidence_bundle_source_snippets,
    evidence_bundle_to_citation_refs,
    normalize_evidence_bundle,
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
