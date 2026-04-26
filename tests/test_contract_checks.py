from __future__ import annotations

from copy import deepcopy

from scripts import check_contracts


def test_contract_snapshots_match_current() -> None:
    assert check_contracts.check_contracts() == []


def test_api_operation_id_only_change_is_nonbreaking() -> None:
    current = check_contracts.build_api_contract()
    expected = deepcopy(current)
    expected["routes"][0]["operation_id"] = "renamed_operation"

    assert check_contracts.compare_api_contract(expected, current) == []


def test_api_route_shape_change_is_breaking() -> None:
    current = check_contracts.build_api_contract()
    expected = deepcopy(current)
    expected["routes"][0]["responses"] = {"200": {"type": "string"}}

    failures = check_contracts.compare_api_contract(expected, current)

    assert failures
    assert "API route contract changed" in failures[0]


def test_api_parameter_shape_change_is_breaking() -> None:
    current = check_contracts.build_api_contract()
    expected = deepcopy(current)
    route = next(route for route in expected["routes"] if route["parameters"])
    route["parameters"][0]["schema"] = {"type": "integer", "minimum": 999}

    failures = check_contracts.compare_api_contract(expected, current)

    assert failures
    assert "API route contract changed" in failures[0]


def test_api_schema_constraint_change_is_breaking() -> None:
    current = check_contracts.build_api_contract()
    expected = deepcopy(current)
    schema_name = next(
        name
        for name, schema in expected["schemas"].items()
        if isinstance(schema, dict) and schema.get("properties")
    )
    property_name = next(iter(expected["schemas"][schema_name]["properties"]))
    expected["schemas"][schema_name]["properties"][property_name]["maxLength"] = 1

    failures = check_contracts.compare_api_contract(expected, current)

    assert failures
    assert "API route contract changed" in failures[0]


def test_sdk_contract_change_is_breaking() -> None:
    current = check_contracts.build_sdk_contract()
    expected = deepcopy(current)
    expected["client_methods"] = [name for name in expected["client_methods"] if name != "streamTurn"]

    failures = check_contracts.compare_sdk_contract(expected, current)

    assert failures == ["SDK contract changed: client_methods"]


def test_sdk_type_shape_change_is_breaking() -> None:
    current = check_contracts.build_sdk_contract()
    expected = deepcopy(current)
    type_name = expected["exported_types"][0]
    expected["exported_type_declarations"][type_name] = "export interface Changed {}"

    failures = check_contracts.compare_sdk_contract(expected, current)

    assert failures == ["SDK contract changed: exported_type_declarations"]


def test_sdk_package_export_change_is_breaking() -> None:
    current = check_contracts.build_sdk_contract()
    expected = deepcopy(current)
    expected["package_exports"] = [value for value in expected["package_exports"] if value != "./toolProtocol"]

    failures = check_contracts.compare_sdk_contract(expected, current)

    assert failures == ["SDK contract changed: package_exports"]


def test_web_sdk_import_change_is_breaking() -> None:
    current = check_contracts.build_sdk_contract()
    expected = deepcopy(current)
    import_path = next(iter(expected["web_sdk_imports"]))
    expected["web_sdk_imports"][import_path] = [
        name for name in expected["web_sdk_imports"][import_path] if name != expected["web_sdk_imports"][import_path][0]
    ]

    failures = check_contracts.compare_sdk_contract(expected, current)

    assert failures == ["SDK contract changed: web_sdk_imports"]


def test_web_sdk_import_scan_captures_app_usage() -> None:
    current = check_contracts.build_sdk_contract()

    assert "apps/web/src/shared/sdk/focus-agent-provider.tsx" in current["web_sdk_imports"]
    assert "FocusAgentClient" in current["web_sdk_imports"]["apps/web/src/shared/sdk/focus-agent-provider.tsx"]
    assert current["package_exports"] == [
        "./client",
        "./guards",
        "./parser",
        "./reducers",
        "./toolProtocol",
        "./types",
    ]


def test_sdk_type_alias_scan_keeps_object_members_after_semicolons() -> None:
    current = check_contracts.build_sdk_contract()
    declaration = current["exported_type_declarations"]["FocusAgentEvent"]

    assert "data: FocusAgentEventPayloadMap[K];" in declaration
    assert "raw?: string;" in declaration
