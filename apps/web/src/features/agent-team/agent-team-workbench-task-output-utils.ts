import { isRecord, uniqueNonEmptyStrings } from "./agent-team-workbench-utils";
import type { AgentTeamArtifact, AgentTeamTask, AgentTeamTaskOutput } from "./types";

type RawRunTextMode = "task" | "bundle";

const TASK_RAW_RUN_TEXT_PATTERN =
  /(?:^|\b)(fake delegated|delegated fake run|delegated (?:fake|inline|background|observe) run|run-|artifact-)/i;
const BUNDLE_RAW_RUN_TEXT_PATTERN = /(?:^|\b)(fake delegated|delegated fake run|run-|artifact-)/i;

export function latestTaskOutput(outputs: AgentTeamTaskOutput[]) {
  return [...outputs].sort((left, right) => Date.parse(right.created_at ?? "") - Date.parse(left.created_at ?? ""))[0] ?? null;
}

export function outputsForTask(outputs: AgentTeamTaskOutput[], task: AgentTeamTask) {
  return outputs.filter((output) => output.task_id === task.task_id);
}

export function artifactsForTask(
  artifacts: AgentTeamArtifact[],
  task: AgentTeamTask,
  outputs: AgentTeamTaskOutput[] = [],
) {
  const artifactIds = new Set([
    ...(task.artifact_ids ?? []),
    ...(task.output_artifact_ids ?? []),
    ...outputs.map((output) => output.artifact_id).filter((artifactId): artifactId is string => Boolean(artifactId)),
  ]);
  return artifacts.filter((artifact) => artifact.task_id === task.task_id || artifactIds.has(artifact.artifact_id));
}

export function uniqueStrings(items: Array<string | null | undefined>) {
  return uniqueNonEmptyStrings(items);
}

export function uniqueCompactStrings(items: Array<string | null | undefined>) {
  return Array.from(
    new Set(
      items
        .map((item) => item?.trim().replace(/\s+/g, " "))
        .filter((item): item is string => Boolean(item)),
    ),
  );
}

export function stringFromUnknown(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

export function formatUnknown(value: unknown) {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

export function isRawRunText(value: string, mode: RawRunTextMode = "task") {
  return (mode === "bundle" ? BUNDLE_RAW_RUN_TEXT_PATTERN : TASK_RAW_RUN_TEXT_PATTERN).test(value.trim());
}

export function hasFakeExecution(outputs: AgentTeamTaskOutput[]) {
  return outputs.some((output) => {
    const metadata = isRecord(output.metadata) ? output.metadata : {};
    const execution = isRecord(metadata.execution) ? metadata.execution : {};
    const run = isRecord(metadata.run) ? metadata.run : {};
    return (
      stringFromUnknown(execution.execution_mode).toLowerCase() === "fake" ||
      stringFromUnknown(run.execution_mode).toLowerCase() === "fake" ||
      stringFromUnknown(metadata.execution_mode).toLowerCase() === "fake"
    );
  });
}

export function taskOutputEvidence(outputs: AgentTeamTaskOutput[]) {
  return uniqueStrings(outputs.flatMap((output) => output.test_evidence ?? []));
}

export function taskOutputRisks(outputs: AgentTeamTaskOutput[]) {
  return uniqueStrings(outputs.flatMap((output) => output.risk_notes ?? []));
}
