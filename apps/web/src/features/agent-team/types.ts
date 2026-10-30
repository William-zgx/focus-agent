import type {
	FocusAgentAgentTeamArtifact,
	FocusAgentAgentTeamCreateSessionRequest,
	FocusAgentAgentTeamCreateTaskRequest,
	FocusAgentAgentTeamDispatchRequest,
	FocusAgentAgentTeamEvidence,
	FocusAgentAgentTeamEvidenceListResponse,
	FocusAgentAgentTeamFinalAnswerStatus,
	FocusAgentAgentTeamListSessionsRequest,
	FocusAgentAgentTeamMergeBundle,
	FocusAgentAgentTeamMergeDecisionRequest,
	FocusAgentAgentTeamMergeDecisionResponse,
	FocusAgentAgentTeamMergeNextAction,
	FocusAgentAgentTeamMergeReview,
	FocusAgentAgentTeamMergeReviewPreviewResponse,
	FocusAgentAgentTeamMergeReviewResponse,
	FocusAgentAgentTeamMergeReviewStatus,
	FocusAgentAgentTeamMergeReviewTask,
	FocusAgentAgentTeamMergeReviewTaskSummary,
	FocusAgentAgentTeamPlanningMetadata,
	FocusAgentAgentTeamPlanSessionRequest,
	FocusAgentAgentTeamReadiness,
	FocusAgentAgentTeamRunMetadata,
	FocusAgentAgentTeamRunSessionRequest,
	FocusAgentAgentTeamRunSessionResponse,
	FocusAgentAgentTeamRunTaskResponse,
	FocusAgentAgentTeamSession,
	FocusAgentAgentTeamSessionListResponse,
	FocusAgentAgentTeamSessionStatus,
	FocusAgentAgentTeamSessionView,
	FocusAgentAgentTeamTask,
	FocusAgentAgentTeamTaskOutput,
	FocusAgentAgentTeamTaskRunRequest,
	FocusAgentAgentTeamTaskStatus,
	FocusAgentAgentTeamToolApproval,
	FocusAgentAgentTeamToolApprovalDecisionRequest,
	FocusAgentAgentTeamToolApprovalDecisionResponse,
} from "@focus-agent/web-sdk";

// Web names for the published SDK Agent Team types. The SDK types follow the
// backend contract (docs/api/openapi.json); add fields there, not here.

export type AgentTeamSessionStatus = FocusAgentAgentTeamSessionStatus;
export type AgentTeamTaskStatus = FocusAgentAgentTeamTaskStatus;
export type AgentTeamFinalAnswerStatus = FocusAgentAgentTeamFinalAnswerStatus;
export type AgentTeamMergeDecisionAction = FocusAgentAgentTeamMergeNextAction;

export type AgentTeamMergeReviewStatus = FocusAgentAgentTeamMergeReviewStatus;
export type AgentTeamMergeReviewTask = FocusAgentAgentTeamMergeReviewTask;
export type AgentTeamMergeReviewTaskSummary =
	FocusAgentAgentTeamMergeReviewTaskSummary;
export type AgentTeamMergeReview = FocusAgentAgentTeamMergeReview;
export type AgentTeamMergeReviewResponse =
	FocusAgentAgentTeamMergeReviewResponse;
export type AgentTeamMergeReviewPreviewResponse =
	FocusAgentAgentTeamMergeReviewPreviewResponse;

export type AgentTeamMergeDecisionRequest =
	FocusAgentAgentTeamMergeDecisionRequest;
export type AgentTeamMergeDecisionResponse =
	FocusAgentAgentTeamMergeDecisionResponse;

export type AgentTeamSession = FocusAgentAgentTeamSession;
export type AgentTeamTask = FocusAgentAgentTeamTask;
export type AgentTeamRunMetadata = FocusAgentAgentTeamRunMetadata;
export type AgentTeamReadiness = FocusAgentAgentTeamReadiness;
export type AgentTeamEvidence = FocusAgentAgentTeamEvidence;
export type AgentTeamEvidenceListResponse =
	FocusAgentAgentTeamEvidenceListResponse;
export type AgentTeamArtifact = FocusAgentAgentTeamArtifact;
export type AgentTeamTaskOutput = FocusAgentAgentTeamTaskOutput;
export type AgentTeamMergeBundle = FocusAgentAgentTeamMergeBundle;
export type AgentTeamPlanningMetadata = FocusAgentAgentTeamPlanningMetadata;

export type AgentTeamToolApproval = FocusAgentAgentTeamToolApproval;
export type AgentTeamToolApprovalDecisionRequest =
	FocusAgentAgentTeamToolApprovalDecisionRequest;
export type AgentTeamToolApprovalDecisionResponse =
	FocusAgentAgentTeamToolApprovalDecisionResponse;

export type AgentTeamSessionView = FocusAgentAgentTeamSessionView;

export type AgentTeamCreateSessionRequest =
	FocusAgentAgentTeamCreateSessionRequest;
export type AgentTeamListSessionsRequest =
	FocusAgentAgentTeamListSessionsRequest;
export type AgentTeamSessionListResponse =
	FocusAgentAgentTeamSessionListResponse;
export type AgentTeamCreateTaskRequest = FocusAgentAgentTeamCreateTaskRequest;
export type AgentTeamDispatchRequest = FocusAgentAgentTeamDispatchRequest;
export type AgentTeamPlanSessionRequest = FocusAgentAgentTeamPlanSessionRequest;
export type AgentTeamRunSessionRequest = FocusAgentAgentTeamRunSessionRequest;
export type AgentTeamRunTaskRequest = FocusAgentAgentTeamTaskRunRequest;

/** Any SDK Agent Team response the session cache knows how to merge. */
export type AgentTeamActionResponse =
	| AgentTeamSession
	| AgentTeamSessionView
	| AgentTeamTask
	| AgentTeamMergeBundle
	| AgentTeamMergeDecisionResponse
	| FocusAgentAgentTeamRunSessionResponse
	| FocusAgentAgentTeamRunTaskResponse;
