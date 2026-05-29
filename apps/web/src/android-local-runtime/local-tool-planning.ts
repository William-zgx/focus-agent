import type { ThreadStateResponse } from "@focus-agent/web-sdk";
import { LOCAL_USER_ID } from "./constants";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { afterCue, containsAny, quotedText } from "./local-text";
import { ANDROID_LOCAL_SKILLS } from "./skills";

export function localAppToolPlan(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	message: string,
): Array<{ name: string; args: Record<string, unknown> }> {
	const normalized = message.toLowerCase();
	const tools: Array<{ name: string; args: Record<string, unknown> }> = [];
	const push = (name: string, args: Record<string, unknown>) => {
		if (ctx.localToolEnabled(name)) tools.push({ name, args });
	};
	if (
		containsAny(normalized, [
			"save artifact",
			"write artifact",
			"write_text_artifact",
			"保存为产物",
			"写入产物",
			"保存产物",
		])
	) {
		const title =
			quotedText(message) ??
			afterCue(message, ["title:", "标题：", "标题:"]) ??
			message.slice(0, 48);
		const body =
			afterCue(message, ["body:", "content:", "正文：", "内容："]) ?? message;
		push("write_text_artifact", { title, body });
	}
	if (
		containsAny(normalized, [
			"list artifacts",
			"artifact list",
			"artifact_list",
			"列出产物",
			"产物列表",
		])
	) {
		push("artifact_list", {});
	}
	if (
		containsAny(normalized, [
			"read artifact",
			"artifact_read",
			"读取产物",
			"打开产物",
		])
	) {
		push("artifact_read", {
			artifact_id: ctx.localArtifactIdFromMessage(message),
		});
	}
	if (
		containsAny(normalized, [
			"update artifact",
			"append artifact",
			"artifact_update",
			"更新产物",
			"追加产物",
		])
	) {
		push("artifact_update", {
			artifact_id: ctx.localArtifactIdFromMessage(message),
			body:
				afterCue(message, ["body:", "content:", "追加：", "内容："]) ?? message,
			mode: containsAny(normalized, ["append", "追加"]) ? "append" : "replace",
		});
	}
	if (
		containsAny(normalized, [
			"remember",
			"save memory",
			"memory_save",
			"记住",
			"保存记忆",
		])
	) {
		push("memory_save", {
			content:
				afterCue(message, [
					"remember",
					"记住",
					"保存记忆",
					"content:",
					"内容：",
				]) ?? message,
			kind: "user_preference",
			scope: "user",
			user_id: LOCAL_USER_ID,
		});
	}
	if (
		containsAny(normalized, [
			"search memory",
			"memory_search",
			"搜索记忆",
			"查找记忆",
			"记忆里",
		])
	) {
		push("memory_search", {
			query:
				afterCue(message, [
					"search memory",
					"memory_search",
					"搜索记忆",
					"查找记忆",
				]) ?? message,
			user_id: LOCAL_USER_ID,
			root_thread_id: thread.root_thread_id,
		});
	}
	if (
		containsAny(normalized, [
			"forget memory",
			"memory_forget",
			"忘记",
			"遗忘记忆",
		])
	) {
		push("memory_forget", {
			memory_id: ctx.localMemoryIdFromMessage(message),
			user_id: LOCAL_USER_ID,
		});
	}
	if (
		containsAny(normalized, [
			"conversation summary",
			"conversation_summary",
			"summarize conversation",
			"会话摘要",
			"总结当前会话",
		])
	) {
		push("conversation_summary", { thread_id: thread.thread_id });
	}
	if (
		containsAny(normalized, [
			"list skills",
			"skills_list",
			"技能列表",
			"列出技能",
		])
	) {
		push("skills_list", {});
	}
	if (containsAny(normalized, ["skill sources", "skill_sources", "技能来源"])) {
		push("skill_sources", {});
	}
	if (
		containsAny(normalized, [
			"search skills",
			"skills_search",
			"搜索技能",
			"查找技能",
		])
	) {
		push("skills_search", {
			query:
				afterCue(message, ["search skills", "skills_search", "搜索技能"]) ??
				message,
			limit: 5,
		});
	}
	if (containsAny(normalized, ["skill_view", "view skill", "查看技能"])) {
		push("skill_view", {
			name:
				quotedText(message) ??
				afterCue(message, ["skill_view", "view skill", "查看技能"]) ??
				ANDROID_LOCAL_SKILLS[0]?.skill_id,
		});
	}
	if (containsAny(normalized, ["skill_install", "install skill", "安装技能"])) {
		push("skill_install", {
			skill_id:
				quotedText(message) ??
				afterCue(message, ["skill_install", "install skill", "安装技能"]) ??
				ANDROID_LOCAL_SKILLS[0]?.skill_id,
		});
	}
	if (
		containsAny(normalized, [
			"skills_refresh_index",
			"refresh skills",
			"刷新技能索引",
		])
	) {
		push("skills_refresh_index", {});
	}
	if (
		containsAny(normalized, [
			"list_files",
			"list files",
			"列出文件",
			"文件列表",
		])
	) {
		push("list_files", { path: ".", pattern: "**/*" });
	}
	if (
		containsAny(normalized, ["read_file", "read file", "读取文件", "查看文件"])
	) {
		push("read_file", {
			path: ctx.localWorkspacePathFromMessage(message) ?? "README.md",
		});
	}
	if (
		containsAny(normalized, [
			"search_code",
			"search code",
			"搜索代码",
			"代码搜索",
		])
	) {
		const rawQuery =
			afterCue(message, ["search_code", "search code", "搜索代码"]) ??
			"android";
		push("search_code", {
			query: rawQuery.split(/[，,。;\s]+/u).find(Boolean) ?? "android",
			path: ".",
			literal: true,
		});
	}
	if (
		containsAny(normalized, [
			"codebase_stats",
			"codebase stats",
			"代码库统计",
			"工作区统计",
		])
	) {
		push("codebase_stats", { path: "." });
	}
	if (
		containsAny(normalized, [
			"apply_patch",
			"apply patch",
			"应用补丁",
			"打补丁",
		])
	) {
		push("apply_patch", {
			patch: ctx.localPatchFromMessage(message),
		});
	}
	if (
		containsAny(normalized, [
			"run_workspace_command",
			"workspace command",
			"运行工作区命令",
			"执行命令",
		])
	) {
		push("run_workspace_command", {
			command: ctx.localCommandFromMessage(message),
			cwd: ".",
		});
	}
	if (containsAny(normalized, ["git_status", "git status", "git 状态"])) {
		push("git_status", {});
	}
	if (containsAny(normalized, ["git_diff", "git diff", "git 差异"])) {
		push("git_diff", {});
	}
	if (containsAny(normalized, ["git_log", "git log", "git 日志"])) {
		push("git_log", { limit: 5 });
	}
	return tools.slice(0, 8);
}

export function localArtifactIdFromMessage(
	ctx: LocalFocusAgentRuntime,
	message: string,
): string | null {
	const artifactId = message.match(/[\p{Letter}\p{Number}_-]+\.md/iu)?.[0];
	return artifactId ?? ctx.state.artifacts?.[0]?.artifact_id ?? null;
}

export function localMemoryIdFromMessage(
	ctx: LocalFocusAgentRuntime,
	message: string,
): string | null {
	const memoryId = message.match(/local-memory-\d+/i)?.[0];
	return (
		memoryId ??
		ctx.state.memories?.find((item) => !item.deleted_at)?.memory_id ??
		null
	);
}
