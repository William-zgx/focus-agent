import type {
	ThreadActiveSkillResponse,
	ThreadStateResponse,
} from "@focus-agent/web-sdk";
import { LOCAL_USER_ID } from "./constants";
import { nowIso, nullableString, stringArray, stringValue } from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { slugifyArtifactTitle, textWords } from "./local-text";
import {
	ANDROID_LOCAL_SKILLS,
	localSkillMatchedTerms,
	localSkillScore,
	localSkillSearchTerms,
} from "./skills";
import { defaultGitCommits } from "./state";
import type {
	LocalArtifact,
	LocalMemory,
	LocalSkill,
	LocalToolExecution,
} from "./types";

export function localArtifactsForThread(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): LocalArtifact[] {
	return (ctx.state.artifacts ?? [])
		.filter(
			(artifact) =>
				artifact.root_thread_id === thread.root_thread_id ||
				artifact.thread_id === thread.thread_id,
		)
		.sort((left, right) => right.updated_at.localeCompare(left.updated_at));
}

export function localSkillPayload(
	_ctx: LocalFocusAgentRuntime,
	skill: LocalSkill,
): Record<string, unknown> {
	return {
		skill_id: skill.skill_id,
		name: skill.name,
		description: skill.description,
		triggers: skill.triggers,
		aliases: skill.aliases ?? [],
		localized_triggers: skill.localized_triggers ?? [],
		domains: skill.domains ?? [],
		intents: skill.intents ?? [],
		when_to_use: skill.when_to_use,
		primary_tools: skill.primary_tools ?? [],
		recommended_tools: skill.recommended_tools,
		prompt_mode: skill.prompt_mode,
		source_id: skill.source_id,
		installed: true,
	};
}

export function syncLocalThreadActiveSkills(
	_ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
): void {
	const seen = new Set<string>();
	thread.active_skill_ids = stringArray(thread.active_skill_ids).filter(
		(skillId) => {
			if (seen.has(skillId)) return false;
			seen.add(skillId);
			return true;
		},
	);
	thread.active_skills = thread.active_skill_ids.map((skillId) => {
		const skill = ANDROID_LOCAL_SKILLS.find(
			(item) => item.skill_id === skillId || item.name === skillId,
		);
		if (!skill) {
			return {
				skill_id: skillId,
				name: skillId,
				description: "",
				enabled: true,
				triggers: [],
				aliases: [],
				primary_tools: [],
				recommended_tools: [],
				prompt_mode: null,
				source_id: "android-local",
				source_type: "builtin",
				version: null,
				trust_level: "trusted",
				install_state: "installed",
			} satisfies ThreadActiveSkillResponse;
		}
		return {
			skill_id: skill.skill_id,
			name: skill.name,
			description: skill.description,
			enabled: true,
			triggers: skill.triggers,
			aliases: skill.aliases ?? [],
			primary_tools: skill.primary_tools ?? [],
			recommended_tools: skill.recommended_tools,
			prompt_mode: skill.prompt_mode,
			source_id: skill.source_id,
			source_type: "builtin",
			version: null,
			trust_level: "trusted",
			install_state: "installed",
		} satisfies ThreadActiveSkillResponse;
	});
}

function resolveLocalSkill(requested: string): LocalSkill | undefined {
	const normalized = requested.trim().toLowerCase();
	if (!normalized) return ANDROID_LOCAL_SKILLS[0];
	return ANDROID_LOCAL_SKILLS.find(
		(item) =>
			item.skill_id === normalized ||
			item.name.toLowerCase() === normalized ||
			normalized.includes(item.skill_id) ||
			normalized.includes(item.name.toLowerCase()) ||
			localSkillSearchTerms(item).some((term) =>
				normalized.includes(term.toLowerCase()),
			),
	);
}

export function executeLocalAppTool(
	ctx: LocalFocusAgentRuntime,
	thread: ThreadStateResponse,
	name: string,
	args: Record<string, unknown>,
): LocalToolExecution {
	const timestamp = nowIso();
	let output: unknown;
	let message = `${name} completed.`;
	if (name === "write_text_artifact") {
		const title = stringValue(args.title).trim() || "Android local artifact";
		const body = stringValue(args.body) || stringValue(args.content);
		const artifactId = slugifyArtifactTitle(title);
		const artifact: LocalArtifact = {
			artifact_id: artifactId,
			title,
			content: `# ${title}\n\n${body}\n`,
			content_type: "text/markdown",
			created_at: timestamp,
			updated_at: timestamp,
			root_thread_id: thread.root_thread_id,
			thread_id: thread.thread_id,
		};
		ctx.state.artifacts = [
			artifact,
			...(ctx.state.artifacts ?? []).filter(
				(item) => item.artifact_id !== artifactId,
			),
		];
		message = `artifact_saved:app-local/artifacts/${artifactId}`;
		output = {
			success: true,
			saved: true,
			artifact_id: artifactId,
			title,
			path: `app-local/artifacts/${artifactId}`,
			result: message,
		};
	} else if (name === "artifact_list") {
		const artifacts = ctx.localArtifactsForThread(thread).map((artifact) => ({
			artifact_id: artifact.artifact_id,
			title: artifact.title,
			content_type: artifact.content_type,
			size: artifact.content.length,
			created_at: artifact.created_at,
			updated_at: artifact.updated_at,
			thread_id: artifact.thread_id,
			root_thread_id: artifact.root_thread_id,
		}));
		output = { artifacts, count: artifacts.length };
		message = `${artifacts.length} local artifacts.`;
	} else if (name === "artifact_read") {
		const artifactId = nullableString(args.artifact_id);
		const artifact = ctx
			.localArtifactsForThread(thread)
			.find((item) => item.artifact_id === artifactId);
		output = artifact
			? { success: true, ...artifact }
			: {
					success: false,
					error: "artifact_not_found",
					artifact_id: artifactId,
				};
		message = artifact ? artifact.title : "Artifact not found.";
	} else if (name === "artifact_update") {
		const artifactId = nullableString(args.artifact_id);
		const artifact = ctx
			.localArtifactsForThread(thread)
			.find((item) => item.artifact_id === artifactId);
		const body = stringValue(args.body) || stringValue(args.content);
		const mode = stringValue(args.mode) === "append" ? "append" : "replace";
		if (artifact) {
			artifact.content =
				mode === "append" ? `${artifact.content.trimEnd()}\n\n${body}\n` : body;
			artifact.updated_at = timestamp;
			output = {
				success: true,
				artifact_id: artifact.artifact_id,
				title: artifact.title,
				mode,
				updated_at: artifact.updated_at,
			};
			message = `artifact_updated:${artifact.artifact_id}`;
		} else {
			output = {
				success: false,
				error: "artifact_not_found",
				artifact_id: artifactId,
			};
			message = "Artifact not found.";
		}
	} else if (name === "memory_save") {
		const content = stringValue(args.content).trim();
		const scope =
			stringValue(args.scope) === "conversation" ||
			stringValue(args.scope) === "root_thread"
				? "root_thread"
				: "user";
		const memory: LocalMemory = {
			memory_id: ctx.nextId("memory", "local-memory"),
			content,
			kind: stringValue(args.kind) || "fact",
			scope,
			visibility: "shared",
			user_id: scope === "user" ? LOCAL_USER_ID : null,
			root_thread_id: scope === "root_thread" ? thread.root_thread_id : null,
			tags: stringArray(args.tags),
			created_at: timestamp,
			updated_at: timestamp,
			deleted_at: null,
		};
		ctx.state.memories = [memory, ...(ctx.state.memories ?? [])];
		output = {
			saved: true,
			action: "written",
			memory_id: memory.memory_id,
			scope: memory.scope,
			visibility: memory.visibility,
			namespace:
				memory.scope === "root_thread"
					? ["conversation", thread.root_thread_id, "main"]
					: ["user", LOCAL_USER_ID, "profile"],
		};
		message = `memory_saved:${memory.memory_id}`;
	} else if (name === "memory_search") {
		const queryWords = textWords(stringValue(args.query));
		const results = (ctx.state.memories ?? [])
			.filter((memory) => !memory.deleted_at)
			.map((memory) => {
				const memoryWords = new Set(textWords(memory.content));
				const overlap = queryWords.filter((word) =>
					memoryWords.has(word),
				).length;
				const score = queryWords.length ? overlap / queryWords.length : 1;
				return { memory, score };
			})
			.filter((item) => item.score > 0 || queryWords.length === 0)
			.sort((left, right) => right.score - left.score)
			.slice(0, Number(args.limit ?? 5))
			.map(({ memory, score }) => ({
				memory_id: memory.memory_id,
				content: memory.content,
				kind: memory.kind,
				scope: memory.scope,
				visibility: memory.visibility,
				score,
				updated_at: memory.updated_at,
			}));
		output = { results, count: results.length };
		message = `${results.length} local memories matched.`;
	} else if (name === "memory_forget") {
		const memoryId = nullableString(args.memory_id);
		const memory = (ctx.state.memories ?? []).find(
			(item) => item.memory_id === memoryId && !item.deleted_at,
		);
		if (memory) {
			memory.deleted_at = timestamp;
			memory.updated_at = timestamp;
		}
		ctx.state.forgottenMemoryIds = [
			...(ctx.state.forgottenMemoryIds ?? []),
			...(memoryId ? [memoryId] : []),
		];
		output = { deleted: Boolean(memory), memory_id: memoryId };
		message = memory ? `memory_deleted:${memoryId}` : "Memory not found.";
	} else if (name === "conversation_summary") {
		const recentMessages = thread.messages.slice(-8).map((item) => ({
			type: item.type,
			content: String(item.content ?? "").slice(0, 500),
			created_at: item.created_at,
		}));
		output = {
			thread_id: thread.thread_id,
			root_thread_id: thread.root_thread_id,
			rolling_summary: thread.rolling_summary ?? "",
			active_skill_ids: thread.active_skill_ids ?? [],
			recent_messages: recentMessages,
		};
		message = "conversation_summary completed.";
	} else if (name === "skills_list") {
		output = {
			success: true,
			skills: ANDROID_LOCAL_SKILLS.map((skill) => ctx.localSkillPayload(skill)),
			count: ANDROID_LOCAL_SKILLS.length,
		};
		message = `${ANDROID_LOCAL_SKILLS.length} local skills.`;
	} else if (name === "skill_sources") {
		output = {
			success: true,
			sources: [
				{
					source_id: "android-local",
					label: "Android local built-ins",
					installed: true,
					count: ANDROID_LOCAL_SKILLS.length,
				},
			],
		};
		message = "skill_sources completed.";
	} else if (name === "skills_search") {
		const query = stringValue(args.query);
		const queryWords = textWords(query);
		const limit = Number(args.limit ?? 5);
		const results = ANDROID_LOCAL_SKILLS.map((skill) => {
			const matchedTerms = localSkillMatchedTerms(skill, query);
			return {
				...ctx.localSkillPayload(skill),
				score: localSkillScore(skill, query),
				matched_terms: matchedTerms,
			};
		})
			.filter((item) => item.score > 0 || queryWords.length === 0)
			.sort((left, right) => right.score - left.score)
			.slice(0, limit);
		output = { success: true, results, count: results.length };
		message = `${results.length} local skills matched.`;
	} else if (name === "skill_view") {
		const requested = stringValue(args.name) || stringValue(args.skill_id);
		const skill = requested
			? resolveLocalSkill(requested)
			: ANDROID_LOCAL_SKILLS[0];
		output = skill
			? {
					success: true,
					...ctx.localSkillPayload(skill),
					content: skill.content,
				}
			: { success: false, error: "skill_not_found", name: requested };
		message = skill ? skill.name : "Skill not found.";
	} else if (name === "skill_install") {
		const requested = stringValue(args.skill_id) || stringValue(args.name);
		const skill = resolveLocalSkill(requested);
		if (skill && !thread.active_skill_ids.includes(skill.skill_id)) {
			thread.active_skill_ids = [...thread.active_skill_ids, skill.skill_id];
		}
		if (skill) syncLocalThreadActiveSkills(ctx, thread);
		output = skill
			? {
					success: true,
					installed: true,
					...ctx.localSkillPayload(skill),
				}
			: { success: false, error: "skill_not_found", skill_id: requested };
		message = skill ? `skill_installed:${skill.skill_id}` : "Skill not found.";
	} else if (name === "skills_refresh_index") {
		output = {
			success: true,
			refreshed: true,
			indexed_count: ANDROID_LOCAL_SKILLS.length,
			source_ids: ["android-local"],
		};
		message = `skills_index_refreshed:${ANDROID_LOCAL_SKILLS.length}`;
	} else if (name === "list_files") {
		const maxResults = Math.min(Number(args.max_results ?? 100), 500);
		const results = ctx
			.workspaceFileEntries(args.path)
			.map(([path]) => path)
			.slice(0, maxResults);
		output = {
			results,
			count: results.length,
			truncated: ctx.workspaceFileEntries(args.path).length > results.length,
			root: "app-local://workspace",
		};
		message = `${results.length} workspace files.`;
	} else if (name === "read_file") {
		const path = ctx.normalizeWorkspacePath(args.path);
		const content = path ? ctx.workspaceFiles()[path] : undefined;
		if (!path || content === undefined) {
			output = { success: false, error: "file_not_found", path };
			message = "File not found.";
		} else {
			const startLine = Math.max(1, Number(args.start_line ?? 1));
			const maxEndLine = Number(args.end_line ?? startLine + 200);
			const lines = content.split("\n");
			const endLine = Math.min(lines.length, maxEndLine);
			const rendered = lines
				.slice(startLine - 1, endLine)
				.map((line, index) => `${startLine + index} | ${line}`)
				.join("\n");
			output = {
				success: true,
				path,
				start_line: startLine,
				end_line: endLine,
				content: rendered,
			};
			message = path;
		}
	} else if (name === "search_code") {
		const query = stringValue(args.query);
		const literal = args.literal !== false;
		const maxResults = Math.min(Number(args.max_results ?? 20), 100);
		const matcher = literal
			? (line: string) => line.toLowerCase().includes(query.toLowerCase())
			: (line: string) => new RegExp(query, "i").test(line);
		const results = ctx
			.workspaceFileEntries(args.path)
			.flatMap(([path, content]) =>
				content.split("\n").flatMap((line, index, lines) => {
					if (!query || !matcher(line)) return [];
					return [
						{
							path,
							line_number: index + 1,
							line,
							context: lines
								.slice(Math.max(0, index - 2), index + 3)
								.join("\n"),
						},
					];
				}),
			)
			.slice(0, maxResults);
		output = {
			results,
			count: results.length,
			truncated: results.length === maxResults,
		};
		message = `${results.length} search results.`;
	} else if (name === "codebase_stats") {
		const entries = ctx.workspaceFileEntries(args.path);
		const breakdown = new Map<string, { files: number; bytes: number }>();
		for (const [path, content] of entries) {
			const language = ctx.languageForPath(path);
			const current = breakdown.get(language) ?? { files: 0, bytes: 0 };
			current.files += 1;
			current.bytes += content.length;
			breakdown.set(language, current);
		}
		output = {
			files_scanned: entries.length,
			total_bytes: entries.reduce(
				(total, [, content]) => total + content.length,
				0,
			),
			language_breakdown: [...breakdown.entries()].map(([language, stats]) => ({
				language,
				...stats,
			})),
		};
		message = `${entries.length} workspace files scanned.`;
	} else if (name === "apply_patch") {
		try {
			const changedFiles = ctx.applyPatchToWorkspace(stringValue(args.patch));
			output = { applied: true, changed_files: changedFiles };
			message = `patch_applied:${changedFiles.join(",")}`;
		} catch (error) {
			output = {
				applied: false,
				error: error instanceof Error ? error.message : String(error),
			};
			message = "Patch failed.";
		}
	} else if (name === "run_workspace_command") {
		const command = Array.isArray(args.command)
			? args.command.map(String)
			: stringValue(args.command).split(/\s+/).filter(Boolean);
		const [program, ...rest] = command;
		let stdout = "";
		let stderr = "";
		let exitCode = 0;
		if (!program) {
			exitCode = 2;
			stderr = "Missing command.";
		} else if (program === "pwd") {
			stdout = "app-local://workspace\n";
		} else if (program === "ls") {
			const target = rest.find((item) => !item.startsWith("-")) ?? ".";
			stdout = `${ctx
				.workspaceFileEntries(target)
				.map(([path]) => path)
				.join("\n")}\n`;
		} else if (program === "cat") {
			const path = ctx.normalizeWorkspacePath(rest[0]);
			stdout = path ? (ctx.workspaceFiles()[path] ?? "") : "";
			if (!stdout) {
				exitCode = 1;
				stderr = "File not found.";
			}
		} else if (program === "rg") {
			const query = rest.find((item) => !item.startsWith("-")) ?? "";
			const matches = ctx
				.workspaceFileEntries(".")
				.flatMap(([path, content]) =>
					content
						.split("\n")
						.flatMap((line, index) =>
							line.toLowerCase().includes(query.toLowerCase())
								? [`${path}:${index + 1}:${line}`]
								: [],
						),
				);
			stdout = `${matches.join("\n")}\n`;
			exitCode = matches.length ? 0 : 1;
		} else if (program === "git" && rest[0] === "status") {
			stdout = `${ctx.workspaceStatusEntries().join("\n") || "clean"}\n`;
		} else if (program === "git" && rest[0] === "diff") {
			stdout = ctx.workspaceDiff(rest[1]) || "";
		} else {
			exitCode = 127;
			stderr =
				"Android local runtime supports only pwd, ls, cat, rg, git status, and git diff.";
		}
		output = {
			command,
			cwd: ".",
			exit_code: exitCode,
			stdout,
			stderr,
			truncated: false,
		};
		message = `command_exit:${exitCode}`;
	} else if (name === "git_status") {
		const entries = ctx.workspaceStatusEntries();
		output = {
			branch: "android-local",
			entries,
			clean: entries.length === 0,
			porcelain: entries.join("\n"),
		};
		message = entries.length ? `${entries.length} changed files.` : "clean";
	} else if (name === "git_diff") {
		const diff = ctx.workspaceDiff(args.pathspec);
		output = {
			diff,
			truncated: false,
		};
		message = diff ? "git_diff completed." : "No local diff.";
	} else if (name === "git_log") {
		const limit = Math.min(Number(args.limit ?? 10), 50);
		const commits = (ctx.state.gitCommits ?? defaultGitCommits())
			.slice(0, limit)
			.map((commit) => ({ ...commit }));
		output = { commits, count: commits.length };
		message = `${commits.length} commits.`;
	} else {
		output = { success: false, error: "unsupported_local_tool", name };
		message = `Unsupported local tool: ${name}`;
	}
	return { name, args, message, output };
}
