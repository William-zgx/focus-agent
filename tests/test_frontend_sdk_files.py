from pathlib import Path


def _sdk_client_text(root: Path) -> str:
    sources = [(root / 'src' / 'client.ts').read_text()]
    sources.extend(path.read_text() for path in sorted((root / 'src' / 'client').glob('*.ts')))
    return '\n'.join(sources)


def _sdk_types_text(root: Path) -> str:
    return '\n'.join(
        path.read_text()
        for path in sorted((root / 'src' / 'types').glob('*.ts'))
    )


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
        root / 'src' / 'errors.ts',
        root / 'src' / 'transport.ts',
        root / 'src' / 'reducers.ts',
        root / 'src' / 'guards.ts',
    ]
    for path in required:
        assert path.exists(), f'missing {path}'

    types_barrel_text = (root / 'src' / 'types.ts').read_text()
    assert 'export * from "./types/stream.js";' in types_barrel_text
    assert 'export interface FocusAgentEvent' not in types_barrel_text
    assert 'export type FocusAgentEventName' not in types_barrel_text

    types_text = _sdk_types_text(root)
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
    assert 'FocusAgentDelegationPlanResponse' in types_text
    assert 'FocusAgentModelRouterPolicyResponse' in types_text
    assert 'FocusAgentSelfRepairPromotePreviewResponse' in types_text
    assert 'FocusAgentReviewQueueListResponse' in types_text
    assert 'FocusAgentContextPolicyResponse' in types_text
    assert 'FocusAgentContextPreviewResponse' in types_text
    assert 'FocusAgentContextArtifactListResponse' in types_text
    assert 'FocusAgentTaskLedgerPlanResponse' in types_text
    assert 'FocusAgentArtifactSynthesisResponse' in types_text
    assert 'FocusAgentCriticEvaluateResponse' in types_text
    assert 'FocusAgentBranchActionProposal' in types_text
    assert 'FocusAgentBranchActionExecuteResponse' in types_text
    assert 'FocusAgentToolApprovalInterrupt' in types_text
    assert 'branch.action.executed' in types_text

    client_text = _sdk_client_text(root)
    assert 'class FocusAgentClient' in client_text
    assert 'FocusAgentRequestError' in client_text
    assert 'FocusAgentTransport' in client_text

    errors_text = (root / 'src' / 'errors.ts').read_text()
    assert 'class FocusAgentRequestError' in errors_text
    assert 'request_id' in errors_text
    assert 'raw' in errors_text

    transport_text = (root / 'src' / 'transport.ts').read_text()
    guards_text = (root / 'src' / 'guards.ts').read_text()
    assert 'class FocusAgentTransport' in transport_text
    assert 'isToolApprovalInterrupt' in guards_text
    assert 'payload.kind === "tool_approval"' in guards_text
    assert 'createFocusAgentRequestError' in transport_text
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
    assert 'executeBranchAction' in client_text
    assert 'dismissBranchAction' in client_text
    assert 'archiveBranch' in client_text
    assert 'activateBranch' in client_text
    assert 'prepareMergeProposal' in client_text
    assert 'applyMergeDecision' in client_text
    assert 'listTrajectoryTurns' in client_text
    assert 'getTrajectoryTurn' in client_text
    assert 'getTrajectoryStats' in client_text
    assert 'replayTrajectoryTurn' in client_text
    assert 'promoteTrajectoryTurn' in client_text
    assert 'planAgentDelegation' in client_text
    assert 'routeAgentModel' in client_text
    assert 'previewAgentSelfRepairPromotion' in client_text
    assert 'listAgentReviewQueue' in client_text
    assert 'getAgentContextPolicy' in client_text
    assert 'previewAgentContext' in client_text
    assert 'listAgentContextArtifacts' in client_text
    assert 'planAgentTaskLedger' in client_text
    assert 'synthesizeAgentArtifacts' in client_text
    assert 'evaluateAgentCriticGate' in client_text
    assert 'buildTrajectoryQueryString' in client_text
    assert 'this.transport.requestJson' in client_text
