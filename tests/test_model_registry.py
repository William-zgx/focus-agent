from focus_agent.config import ConfiguredModel, ModelCatalogConfig, ProviderConfig, Settings
from focus_agent import model_registry
from focus_agent.model_registry import build_model_catalog, create_chat_model, resolve_model_config


def test_build_model_catalog_keeps_default_first():
    settings = Settings(
        model="moonshot:kimi-k2.6",
        model_choices=("openai:deepseek-reasoner", "moonshot:kimi-k2.6"),
    )

    catalog = build_model_catalog(settings)

    assert [item.id for item in catalog] == [
        "moonshot:kimi-k2.6",
        "openai:deepseek-reasoner",
    ]
    assert catalog[0].provider == "moonshot"
    assert catalog[0].is_default is True
    assert catalog[0].supports_thinking is True
    assert catalog[0].default_thinking_enabled is True
    assert catalog[1].supports_thinking is True
    assert catalog[1].default_thinking_enabled is True


def test_resolve_model_config_maps_moonshot_to_openai_backend():
    resolved = resolve_model_config(
        "moonshot:kimi-k2.6",
        environ={
            "MOONSHOT_BASE_URL": "https://api.moonshot.cn/v1",
            "MOONSHOT_API_KEY": "secret",
        },
    )

    assert resolved.provider == "moonshot"
    assert resolved.backend_provider == "openai"
    assert resolved.client_kwargs["base_url"] == "https://api.moonshot.cn/v1"
    assert resolved.client_kwargs["api_key"] == "secret"


def test_resolve_model_config_disables_kimi_thinking_via_extra_body():
    resolved = resolve_model_config(
        "moonshot:kimi-k2.6",
        thinking_mode="disabled",
    )

    assert resolved.model_name == "kimi-k2.6"
    assert resolved.request_kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_resolve_model_config_disables_deepseek_reasoner_by_switching_backend_model():
    resolved = resolve_model_config(
        "openai:deepseek-reasoner",
        thinking_mode="disabled",
    )

    assert resolved.provider == "openai"
    assert resolved.model_name == "deepseek-chat"
    assert resolved.request_kwargs == {}


def test_resolve_model_config_maps_ollama_to_openai_backend():
    resolved = resolve_model_config("ollama:qwen2.5:7b")

    assert resolved.provider == "ollama"
    assert resolved.backend_provider == "openai"
    assert resolved.model_name == "qwen2.5:7b"
    assert resolved.client_kwargs["base_url"] == "http://127.0.0.1:11434/v1"
    assert resolved.client_kwargs["api_key"] == "ollama"


def test_build_model_catalog_uses_structured_provider_and_model_metadata():
    settings = Settings(
        model="deepseek:deepseek-reasoner",
        model_choices=("ollama:gemma4-hauhau:q8",),
        model_catalog=ModelCatalogConfig(
            providers=(
                ProviderConfig(
                    id="deepseek",
                    label="DeepSeek",
                    backend_provider="openai",
                    base_url_env="DEEPSEEK_BASE_URL",
                    api_key_env="DEEPSEEK_API_KEY",
                    aliases=("ds",),
                ),
            ),
            models=(
                ConfiguredModel(
                    id="deepseek:deepseek-reasoner",
                    label="DeepSeek Reasoner",
                    supports_thinking=True,
                    default_thinking_enabled=True,
                    thinking_disable_switch_model="deepseek-chat",
                ),
            ),
        ),
    )

    catalog = build_model_catalog(settings)

    assert [item.id for item in catalog] == [
        "deepseek:deepseek-reasoner",
        "ollama:gemma4-hauhau:q8",
    ]
    assert catalog[0].provider == "deepseek"
    assert catalog[0].provider_label == "DeepSeek"
    assert catalog[0].label == "DeepSeek Reasoner · DeepSeek"


def test_resolve_model_config_uses_structured_provider_configuration():
    settings = Settings(
        model="deepseek:deepseek-reasoner",
        model_catalog=ModelCatalogConfig(
            providers=(
                ProviderConfig(
                    id="deepseek",
                    label="DeepSeek",
                    backend_provider="openai",
                    base_url_env="DEEPSEEK_BASE_URL",
                    api_key_env="DEEPSEEK_API_KEY",
                    aliases=("ds",),
                ),
            ),
            models=(
                ConfiguredModel(
                    id="deepseek:deepseek-reasoner",
                    label="DeepSeek Reasoner",
                    supports_thinking=True,
                    default_thinking_enabled=True,
                    thinking_disable_switch_model="deepseek-chat",
                ),
            ),
        ),
    )

    resolved = resolve_model_config(
        "ds:deepseek-reasoner",
        thinking_mode="disabled",
        environ={
            "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            "DEEPSEEK_API_KEY": "secret",
        },
        settings=settings,
    )

    assert resolved.provider == "deepseek"
    assert resolved.backend_provider == "openai"
    assert resolved.model_name == "deepseek-chat"
    assert resolved.client_kwargs["base_url"] == "https://api.deepseek.com"
    assert resolved.client_kwargs["api_key"] == "secret"


def test_create_chat_model_omits_temperature_for_kimi_k2_6(monkeypatch):
    captured: dict[str, object] = {}

    def fake_init_chat_model(model_name: str, **kwargs):
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(model_registry, "init_chat_model", fake_init_chat_model)

    create_chat_model("moonshot:kimi-k2.6", temperature=0.0)

    assert captured["model_name"] == "openai:kimi-k2.6"
    assert "temperature" not in captured["kwargs"]


def test_create_chat_model_keeps_temperature_for_other_models(monkeypatch):
    captured: dict[str, object] = {}

    def fake_init_chat_model(model_name: str, **kwargs):
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(model_registry, "init_chat_model", fake_init_chat_model)

    create_chat_model("openai:gpt-4.1-mini", temperature=0.2)

    assert captured["model_name"] == "openai:gpt-4.1-mini"
    assert captured["kwargs"]["temperature"] == 0.2


def test_create_chat_model_uses_openai_backend_for_ollama(monkeypatch):
    captured: dict[str, object] = {}

    def fake_init_chat_model(model_name: str, **kwargs):
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(model_registry, "init_chat_model", fake_init_chat_model)

    create_chat_model("ollama:qwen2.5:7b", temperature=0.1)

    assert captured["model_name"] == "openai:qwen2.5:7b"
    assert captured["kwargs"]["base_url"] == "http://127.0.0.1:11434/v1"
    assert captured["kwargs"]["api_key"] == "ollama"
    assert captured["kwargs"]["temperature"] == 0.1


def test_create_chat_model_uses_structured_provider_backend(monkeypatch):
    captured: dict[str, object] = {}

    def fake_init_chat_model(model_name: str, **kwargs):
        captured["model_name"] = model_name
        captured["kwargs"] = kwargs
        return object()

    monkeypatch.setattr(model_registry, "init_chat_model", fake_init_chat_model)
    settings = Settings(
        model="deepseek:deepseek-reasoner",
        model_catalog=ModelCatalogConfig(
            providers=(
                ProviderConfig(
                    id="deepseek",
                    label="DeepSeek",
                    backend_provider="openai",
                    base_url_env="DEEPSEEK_BASE_URL",
                    api_key_env="DEEPSEEK_API_KEY",
                ),
            ),
            models=(
                ConfiguredModel(
                    id="deepseek:deepseek-reasoner",
                    label="DeepSeek Reasoner",
                    supports_thinking=True,
                    default_thinking_enabled=True,
                ),
            ),
        ),
    )

    create_chat_model(
        "deepseek:deepseek-reasoner",
        temperature=0.1,
        settings=settings,
    )

    assert captured["model_name"] == "openai:deepseek-reasoner"
