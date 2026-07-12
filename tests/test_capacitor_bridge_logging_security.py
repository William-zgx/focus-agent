import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ANDROID_BRIDGE_ROOT = (
    ROOT / "node_modules" / "@capacitor" / "android" / "capacitor" / "src" / "main"
)


def _evaluated_capacitor_config() -> dict:
    result = subprocess.run(
        ["pnpm", "exec", "cap", "config", "--json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(result.stdout)


def test_android_bridge_logging_is_disabled_in_all_build_types():
    config = _evaluated_capacitor_config()["app"]["extConfig"]

    assert config["android"]["loggingBehavior"] == "none"
    assert "webContentsDebuggingEnabled" not in config["android"]
    assert "loggingBehavior" not in config


def test_capacitor_logging_gate_covers_sensitive_plugin_payloads():
    cap_config_source = (
        ANDROID_BRIDGE_ROOT / "java" / "com" / "getcapacitor" / "CapConfig.java"
    ).read_text()
    bridge_source = (
        ANDROID_BRIDGE_ROOT / "java" / "com" / "getcapacitor" / "Bridge.java"
    ).read_text()
    js_export_source = (
        ANDROID_BRIDGE_ROOT / "java" / "com" / "getcapacitor" / "JSExport.java"
    ).read_text()
    native_bridge_source = (ANDROID_BRIDGE_ROOT / "assets" / "native-bridge.js").read_text()

    none_branch = re.search(
        r"case LOG_BEHAVIOR_NONE:\s+loggingEnabled = false;\s+break;",
        cap_config_source,
    )
    assert none_branch, "Capacitor no longer maps loggingBehavior=none to disabled logging"
    assert re.search(
        r"if \(Logger\.shouldLog\(\)\) \{.*?call\.getData\(\)\.toString\(\)",
        bridge_source,
        re.DOTALL,
    ), "Capacitor plugin payload logging is no longer protected by Logger.shouldLog()"
    assert 'isLoggingEnabled: " + loggingEnabled' in js_export_source
    assert re.search(
        r"if \(cap\.isLoggingEnabled && pluginName !== 'Console'\) \{\s+"
        r"cap\.logToNative\(callData\);",
        native_bridge_source,
    ), "Capacitor JavaScript bridge call logging is no longer gated"
    assert re.search(
        r"if \(cap\.isLoggingEnabled && result\.pluginId !== 'Console'\) \{\s+"
        r"cap\.logFromNative\(result\);",
        native_bridge_source,
    ), "Capacitor JavaScript bridge result logging is no longer gated"


def test_debug_webview_diagnostics_remain_build_type_scoped():
    cap_config_source = (
        ANDROID_BRIDGE_ROOT / "java" / "com" / "getcapacitor" / "CapConfig.java"
    ).read_text()
    bridge_source = (
        ANDROID_BRIDGE_ROOT / "java" / "com" / "getcapacitor" / "Bridge.java"
    ).read_text()

    assert re.search(
        r"webContentsDebuggingEnabled = JSONUtils\.getBoolean\("
        r'configJSON, "android\.webContentsDebuggingEnabled", isDebug\);',
        cap_config_source,
    )
    assert (
        "WebView.setWebContentsDebuggingEnabled(this.config.isWebContentsDebuggingEnabled());"
    ) in bridge_source
