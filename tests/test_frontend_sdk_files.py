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
    assert 'FocusAgentMergeProposal' in types_text
    assert 'FocusAgentApplyMergeDecisionRequest' in types_text
    assert 'preparing_merge_review' in types_text
    assert 'FocusAgentCreateConversationRequest' in types_text
    assert 'FocusAgentUpdateConversationRequest' in types_text
    assert 'FocusAgentTrajectoryFilters' in types_text
    assert 'FocusAgentTrajectoryListRequest' in types_text
    assert 'FocusAgentTrajectoryTurnSummary' in types_text
    assert 'FocusAgentTrajectoryTurnDetail' in types_text
    assert 'FocusAgentTrajectoryStatsResponse' in types_text
    assert 'FocusAgentTrajectoryReplayRequest' in types_text
    assert 'FocusAgentTrajectoryReplayResponse' in types_text
    assert 'FocusAgentTrajectoryPromotionResponse' in types_text

    client_text = (root / 'src' / 'client.ts').read_text()
    assert 'class FocusAgentClient' in client_text
    assert 'class FocusAgentRequestError' in client_text
    assert 'listModels' in client_text
    assert 'listConversations' in client_text
    assert 'createConversation' in client_text
    assert 'renameConversation' in client_text
    assert 'archiveConversation' in client_text
    assert 'activateConversation' in client_text
    assert 'getThreadState' in client_text
    assert 'getBranchTree' in client_text
    assert 'streamTurn' in client_text
    assert 'streamResume' in client_text
    assert 'forkBranch' in client_text
    assert 'archiveBranch' in client_text
    assert 'activateBranch' in client_text
    assert 'prepareMergeProposal' in client_text
    assert 'applyMergeDecision' in client_text
    assert 'listTrajectoryTurns' in client_text
    assert 'getTrajectoryTurn' in client_text
    assert 'getTrajectoryStats' in client_text
    assert 'replayTrajectoryTurn' in client_text
    assert 'promoteTrajectoryTurn' in client_text
    assert 'buildTrajectoryQueryString' in client_text
    assert 'new FocusAgentRequestError(response.status, response.statusText)' in client_text
