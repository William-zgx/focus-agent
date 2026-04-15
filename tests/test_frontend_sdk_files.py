from pathlib import Path


def test_frontend_sdk_files_exist_and_export_core_surfaces():
    root = Path(__file__).resolve().parents[1] / 'frontend-sdk'
    required = [
        root / 'package.json',
        root / 'tsconfig.json',
        root / 'README.md',
        root / 'src' / 'index.ts',
        root / 'src' / 'types.ts',
        root / 'src' / 'parser.ts',
        root / 'src' / 'client.ts',
        root / 'src' / 'reducers.ts',
        root / 'src' / 'guards.ts',
    ]
    for path in required:
        assert path.exists(), f'missing {path}'

    types_text = (root / 'src' / 'types.ts').read_text()
    assert 'visible_text.delta' in types_text
    assert 'reasoning.delta' in types_text
    assert 'tool_call.delta' in types_text
    assert 'ConclusionPolicy' not in types_text
    assert 'archived_branches' in types_text
    assert 'selected_model' in types_text
    assert 'selected_thinking_mode' in types_text
    assert 'thinking_mode' in types_text
    assert 'provider_label' in types_text
    assert 'supports_thinking' in types_text

    client_text = (root / 'src' / 'client.ts').read_text()
    assert 'class FocusAgentClient' in client_text
    assert 'listModels' in client_text
    assert 'streamTurn' in client_text
    assert 'streamResume' in client_text
