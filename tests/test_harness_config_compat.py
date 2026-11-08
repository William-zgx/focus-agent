from types import SimpleNamespace

from focus_agent.harness import HarnessConfig as PublicHarnessConfig
from focus_agent.harness import RuntimeHarnessConfig
from focus_agent.harness.runtime import HarnessConfig as RuntimePackageHarnessConfig
from focus_agent.harness.runtime.config import HarnessConfig as RuntimeModuleHarnessConfig
from focus_agent.harness.runtime.config import RuntimeFeatures as RuntimeModuleFeatures
from focus_agent.harness.runtime.runs import DisconnectMode, MultitaskStrategy
from focus_agent.harness.schemas import HarnessConfig as SchemaPackageHarnessConfig
from focus_agent.harness.schemas.config import HarnessConfig as SchemaModuleHarnessConfig
from focus_agent.harness.schemas.config import RuntimeFeatures as SchemaModuleFeatures


def test_harness_config_public_imports_share_canonical_schema_class():
    assert PublicHarnessConfig is SchemaModuleHarnessConfig
    assert SchemaPackageHarnessConfig is SchemaModuleHarnessConfig
    assert RuntimePackageHarnessConfig is SchemaModuleHarnessConfig
    assert RuntimeModuleHarnessConfig is SchemaModuleHarnessConfig
    assert RuntimeHarnessConfig is SchemaModuleHarnessConfig
    assert RuntimeModuleFeatures is SchemaModuleFeatures


def test_harness_config_keeps_runtime_compatibility_helpers():
    config = RuntimeModuleHarnessConfig(
        recursion_limit=42,
        metadata={"app_version": "1.2.3", "deployment": None},
    )

    runnable = config.runnable_config(
        "thread-1",
        overrides={"configurable": {"checkpoint_id": "checkpoint-1"}},
        metadata={"request_id": "req-1"},
    )

    assert runnable == {
        "recursion_limit": 42,
        "configurable": {
            "checkpoint_id": "checkpoint-1",
            "thread_id": "thread-1",
        },
        "metadata": {
            "app_version": "1.2.3",
            "request_id": "req-1",
        },
    }


def test_harness_config_from_settings_preserves_legacy_runtime_fields():
    settings = SimpleNamespace(
        model="openai:gpt-4.1-mini",
        selected_thinking_mode="medium",
        sse_heartbeat_seconds=2.5,
        background_queue_max_size=512,
        app_version="test-version",
        app_environment="test",
        deployment_name="local",
        agent_memory_backend="sqlite",
        agent_context_engineering_v2_enabled=True,
    )

    config = RuntimeModuleHarnessConfig.from_settings(settings)

    assert config.model == "openai:gpt-4.1-mini"
    assert config.default_model == "openai:gpt-4.1-mini"
    assert config.default_thinking_mode == "medium"
    assert config.heartbeat_seconds == 2.5
    assert config.streaming.heartbeat_seconds == 2.5
    assert config.stream_queue_maxsize == 512
    assert config.on_disconnect is DisconnectMode.CANCEL
    assert config.multitask_strategy is MultitaskStrategy.REJECT
    assert config.metadata == {
        "app_version": "test-version",
        "environment": "test",
        "deployment": "local",
    }
    assert config.features.memory is True
    assert config.features.context_engineering_v2 is True


def test_runtime_features_keep_enabled_and_implementation_compatibility():
    implementation = object()
    memory_impl = object()
    features = RuntimeModuleFeatures(
        memory=memory_impl,
        custom={"x": implementation},
    )

    assert features.enabled("memory") is True
    assert features.enabled("x") is True
    assert features.implementation("memory") is memory_impl
    assert features.implementation("x") is implementation


def test_runtime_features_still_coerce_boolean_strings_for_schema_fields():
    features = RuntimeModuleFeatures(memory="false", streaming="true")

    assert features.memory is False
    assert features.streaming is True
