from focus_agent.engine.graph import policy
from focus_agent.engine.graph import policy_intent_parsing as parsing


def test_policy_reexports_intent_parsing_helpers():
    helper_names = (
        "_HTTP_URL_RE",
        "_SKILL_ID_RE",
        "_filter_bare_current_hits",
        "_explicit_web_tool_contract_reason_codes",
        "_preferred_first_args",
        "_skill_view_name_from_text",
        "_skill_install_name_from_text",
        "_should_prefer_web_fetch",
        "_first_http_url",
        "_workspace_search_query",
    )

    for helper_name in helper_names:
        assert getattr(policy, helper_name) is getattr(parsing, helper_name)


def test_preferred_args_keep_skill_name_parsing_behavior():
    assert policy._preferred_first_args(
        "skill_view",
        "skill_view build-web-apps:frontend-testing-debugging",
    ) == {"name": "build-web-apps:frontend-testing-debugging"}
    assert policy._preferred_first_args(
        "skill_view",
        "Please call skill_view for systematic-debugging",
    ) == {"name": "systematic-debugging"}
    assert policy._preferred_first_args(
        "skills_search",
        "stock-analyzer，帮我安装这个 skill",
    ) == {"query": "stock-analyzer", "scope": "all"}
    assert policy._preferred_first_args(
        "skill_install",
        "skill_install: stock-analyzer",
    ) == {"skill_id": "stock-analyzer"}


def test_preferred_args_keep_url_and_query_parsing_behavior():
    assert policy._preferred_first_args(
        "web_fetch",
        "Fetch https://example.com/path?q=focus，then summarize it.",
    ) == {"url": "https://example.com/path?q=focus"}
    assert policy._preferred_first_args(
        "search_code",
        "Find function build_tool_intent_plan in the repo and policy.py",
    ) == {"query": "Find build_tool_intent_plan in the and policy.py"}
    assert policy._preferred_first_args("web_search", "  latest AI news  ") == {
        "query": "  latest AI news  "
    }


def test_preferred_web_search_args_compact_long_prompts_to_quoted_research_terms():
    prompt = (
        "请完成一项实时事实核查：先实际调用 web_search 查询"
        "“Python 3.13 free-threaded mode official documentation”和"
        "“MDN HTTP 307 Temporary Redirect official”；然后根据官方来源给出结论。" + " 补充说明" * 100
    )

    args = policy._preferred_first_args("web_search", prompt)

    assert len(args["query"]) <= 400
    assert args["query"] == (
        "Python 3.13 free-threaded mode official documentation "
        "MDN HTTP 307 Temporary Redirect official"
    )
