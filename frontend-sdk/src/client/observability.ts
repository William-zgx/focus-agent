import { buildTrajectoryQueryString } from "./query";
import { applyEndpointMethods } from "./endpoint";
import type { EndpointClientConstructor, FocusAgentEndpointContext, FocusAgentEndpointMethodMap } from "./endpoint";
import type {
  FocusAgentObservabilityOverviewRequest,
  FocusAgentObservabilityOverviewResponse,
  FocusAgentTrajectoryBatchPromotionPreviewRequest,
  FocusAgentTrajectoryBatchPromotionPreviewResponse,
  FocusAgentTrajectoryBatchReplayCompareRequest,
  FocusAgentTrajectoryBatchReplayCompareResponse,
  FocusAgentTrajectoryDetailResponse,
  FocusAgentTrajectoryListRequest,
  FocusAgentTrajectoryListResponse,
  FocusAgentTrajectoryPromotionRequest,
  FocusAgentTrajectoryPromotionResponse,
  FocusAgentTrajectoryReplayRequest,
  FocusAgentTrajectoryReplayResponse,
  FocusAgentTrajectoryStatsRequest,
  FocusAgentTrajectoryStatsResponse,
} from "../types";

async function listTrajectoryTurns(
  this: FocusAgentEndpointContext,
  request: FocusAgentTrajectoryListRequest = {},
): Promise<FocusAgentTrajectoryListResponse> {
  return this.requestJson<FocusAgentTrajectoryListResponse>(
    `/v1/observability/trajectory${buildTrajectoryQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function getTrajectoryTurn(this: FocusAgentEndpointContext, turnId: string): Promise<FocusAgentTrajectoryDetailResponse> {
  return this.requestJson<FocusAgentTrajectoryDetailResponse>(
    `/v1/observability/trajectory/${encodeURIComponent(turnId)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function getTrajectoryStats(
  this: FocusAgentEndpointContext,
  request: FocusAgentTrajectoryStatsRequest = {},
): Promise<FocusAgentTrajectoryStatsResponse> {
  return this.requestJson<FocusAgentTrajectoryStatsResponse>(
    `/v1/observability/trajectory/stats${buildTrajectoryQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function getObservabilityOverview(
  this: FocusAgentEndpointContext,
  request: FocusAgentObservabilityOverviewRequest = {},
): Promise<FocusAgentObservabilityOverviewResponse> {
  return this.requestJson<FocusAgentObservabilityOverviewResponse>(
    `/v1/observability/overview${buildTrajectoryQueryString(request)}`,
    {
      method: "GET",
      headers: {},
    },
    true,
  );
}

async function replayTrajectoryTurn(
  this: FocusAgentEndpointContext,
  turnId: string,
  request: FocusAgentTrajectoryReplayRequest = {},
): Promise<FocusAgentTrajectoryReplayResponse> {
  return this.requestJson<FocusAgentTrajectoryReplayResponse>(
    `/v1/observability/trajectory/${encodeURIComponent(turnId)}/replay`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function promoteTrajectoryTurn(
  this: FocusAgentEndpointContext,
  turnId: string,
  request: FocusAgentTrajectoryPromotionRequest = {},
): Promise<FocusAgentTrajectoryPromotionResponse> {
  return this.requestJson<FocusAgentTrajectoryPromotionResponse>(
    `/v1/observability/trajectory/${encodeURIComponent(turnId)}/promote`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function batchPromoteTrajectoryTurnsPreview(
  this: FocusAgentEndpointContext,
  request: FocusAgentTrajectoryBatchPromotionPreviewRequest,
): Promise<FocusAgentTrajectoryBatchPromotionPreviewResponse> {
  return this.requestJson<FocusAgentTrajectoryBatchPromotionPreviewResponse>(
    "/v1/observability/trajectory/batch/promote-preview",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

async function batchReplayCompareTrajectoryTurns(
  this: FocusAgentEndpointContext,
  request: FocusAgentTrajectoryBatchReplayCompareRequest,
): Promise<FocusAgentTrajectoryBatchReplayCompareResponse> {
  return this.requestJson<FocusAgentTrajectoryBatchReplayCompareResponse>(
    "/v1/observability/trajectory/batch/replay-compare",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(request),
    },
    true,
  );
}

export interface ObservabilityEndpoints {
  listTrajectoryTurns: OmitThisParameter<typeof listTrajectoryTurns>;
  getTrajectoryTurn: OmitThisParameter<typeof getTrajectoryTurn>;
  getTrajectoryStats: OmitThisParameter<typeof getTrajectoryStats>;
  getObservabilityOverview: OmitThisParameter<typeof getObservabilityOverview>;
  replayTrajectoryTurn: OmitThisParameter<typeof replayTrajectoryTurn>;
  promoteTrajectoryTurn: OmitThisParameter<typeof promoteTrajectoryTurn>;
  batchPromoteTrajectoryTurnsPreview: OmitThisParameter<typeof batchPromoteTrajectoryTurnsPreview>;
  batchReplayCompareTrajectoryTurns: OmitThisParameter<typeof batchReplayCompareTrajectoryTurns>;
}

const observabilityEndpoints: FocusAgentEndpointMethodMap<ObservabilityEndpoints> = {
  listTrajectoryTurns,
  getTrajectoryTurn,
  getTrajectoryStats,
  getObservabilityOverview,
  replayTrajectoryTurn,
  promoteTrajectoryTurn,
  batchPromoteTrajectoryTurnsPreview,
  batchReplayCompareTrajectoryTurns,
};

export function applyObservabilityEndpoints(Client: EndpointClientConstructor): void {
  applyEndpointMethods(Client, observabilityEndpoints);
}
