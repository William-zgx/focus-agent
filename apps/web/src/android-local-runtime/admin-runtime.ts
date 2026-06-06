import type {
	FocusAgentAdminConfig,
	FocusAgentCreateUserRequest,
	FocusAgentUpdateAdminModelConfigRequest,
	FocusAgentUpdateAdminPolicyConfigRequest,
	FocusAgentUpdateAdminSkillConfigRequest,
	FocusAgentUpdateAdminToolConfigRequest,
	FocusAgentUpdateUserRequest,
	FocusAgentUpdateUserRolesRequest,
	FocusAgentUpdateUserStatusRequest,
} from "@focus-agent/web-sdk";
import {
	ANDROID_LOCAL_TOOL_NAME_SET,
	ANDROID_LOCAL_TOOL_NAMES,
	DEFAULT_PROVIDER_BASE_URL,
	LOCAL_TENANT_ID,
	LOCAL_USER_ID,
} from "./constants";
import {
	errorResponse,
	isRecord,
	jsonResponse,
	normalizedUrl,
	nowIso,
	nullableString,
	parseJsonBody,
	stringArray,
	stringValue,
} from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { defaultAdminConfig, localUser } from "./state";

export async function handleAdmin(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	searchParams: URLSearchParams,
	init?: RequestInit,
): Promise<Response> {
	const [resource, userId, subresource, action] = segments;
	if (resource === "users") {
		return ctx.handleAdminUsers(
			method,
			userId,
			subresource,
			action,
			searchParams,
			init,
		);
	}
	if (resource === "audit-events" && method === "GET") {
		return jsonResponse(ctx.auditEvents(searchParams));
	}
	if (resource === "config") {
		return ctx.handleAdminConfig(method, userId, init);
	}
	return errorResponse(404, "Unsupported local admin route.");
}

export function handleAdminUsers(
	ctx: LocalFocusAgentRuntime,
	method: string,
	userId: string | undefined,
	subresource: string | undefined,
	action: string | undefined,
	searchParams: URLSearchParams,
	init?: RequestInit,
): Response {
	if (!userId && method === "GET") {
		return jsonResponse(ctx.userList(searchParams));
	}
	if (!userId && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentCreateUserRequest;
		const user = localUser({
			user_id:
				stringValue(body.user_id).trim() || ctx.nextId("session", "local-user"),
			username: nullableString(body.username),
			display_name: nullableString(body.display_name),
			email: nullableString(body.email),
			tenant_id: nullableString(body.tenant_id) ?? LOCAL_TENANT_ID,
			status: nullableString(body.status) ?? "active",
			roles: stringArray(body.roles),
			metadata: isRecord(body.metadata) ? body.metadata : {},
		});
		ctx.state.users.push(user);
		ctx.addAuditEvent("admin.user_create", "user", user.user_id);
		ctx.persist();
		return jsonResponse(user);
	}
	const user = ctx.state.users.find((item) => item.user_id === userId);
	if (!user) return errorResponse(404, "User not found.");
	if (!subresource && method === "GET") {
		return jsonResponse(user);
	}
	if (!subresource && method === "PATCH") {
		const body = parseJsonBody(init) as FocusAgentUpdateUserRequest;
		user.username = nullableString(body.username) ?? user.username;
		user.display_name = nullableString(body.display_name) ?? user.display_name;
		user.email = nullableString(body.email) ?? user.email;
		user.tenant_id = nullableString(body.tenant_id) ?? user.tenant_id;
		user.metadata = isRecord(body.metadata) ? body.metadata : user.metadata;
		user.updated_at = nowIso();
		ctx.addAuditEvent("admin.user_update", "user", user.user_id);
		ctx.persist();
		return jsonResponse(user);
	}
	if (subresource === "status" && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentUpdateUserStatusRequest;
		user.status = stringValue(body.status) || user.status;
		user.updated_at = nowIso();
		ctx.addAuditEvent("admin.user_status_update", "user", user.user_id);
		ctx.persist();
		return jsonResponse(user);
	}
	if (subresource === "roles" && method === "PUT") {
		const body = parseJsonBody(init) as FocusAgentUpdateUserRolesRequest;
		user.roles = stringArray(body.roles);
		user.updated_at = nowIso();
		ctx.addAuditEvent("admin.user_roles_update", "user", user.user_id);
		ctx.persist();
		return jsonResponse(user);
	}
	if (subresource === "password" && method === "POST") {
		user.password_updated_at = nowIso();
		user.updated_at = nowIso();
		ctx.addAuditEvent("admin.user_password_reset", "user", user.user_id);
		ctx.persist();
		return jsonResponse(user);
	}
	if (subresource === "sessions" && !action && method === "GET") {
		return jsonResponse(ctx.sessionList(user.user_id, searchParams));
	}
	if (subresource === "sessions" && action === "revoke" && method === "POST") {
		const body = parseJsonBody(init) as { session_id?: string };
		const session = ctx.state.sessions.find(
			(item) =>
				item.user_id === user.user_id && item.session_id === body.session_id,
		);
		if (!session) return errorResponse(404, "Session not found.");
		session.revoked_at = nowIso();
		session.current = false;
		ctx.addAuditEvent(
			"admin.user_session_revoke",
			"session",
			session.session_id,
		);
		ctx.persist();
		return jsonResponse(session);
	}
	return errorResponse(404, "Unsupported local admin user route.");
}

export async function handleAdminConfig(
	ctx: LocalFocusAgentRuntime,
	method: string,
	resource?: string,
	init?: RequestInit,
): Promise<Response> {
	if (!resource && method === "GET") {
		return jsonResponse(ctx.adminConfigResponse());
	}
	if (resource === "models" && method === "PATCH") {
		const body = parseJsonBody(init) as FocusAgentUpdateAdminModelConfigRequest;
		const models = ctx.state.adminConfig.models;
		models.default_model = body.default_model ?? models.default_model;
		models.helper_model = body.helper_model ?? models.helper_model;
		models.model_choices = body.model_choices ?? models.model_choices;
		if (body.providers) {
			const nextProviderIds = new Set<string>();
			models.providers = body.providers.map((provider) => {
				const id = provider.id.trim();
				nextProviderIds.add(id);
				const existing = models.providers.find((item) => item.id === id);
				const nextSecret = nullableString(provider.api_key_default);
				if (nextSecret) {
					ctx.modelSecrets[id] = { apiKey: nextSecret };
				}
				return {
					id,
					label: provider.label ?? existing?.label ?? id,
					backend_provider:
						provider.backend_provider ??
						existing?.backend_provider ??
						"openai-compatible",
					aliases: provider.aliases ?? existing?.aliases ?? [id],
					logo_slug: provider.logo_slug ?? existing?.logo_slug ?? null,
					logo_letter:
						provider.logo_letter ?? existing?.logo_letter ?? id[0] ?? null,
					base_url_env: provider.base_url_env ?? existing?.base_url_env ?? null,
					base_url_default:
						normalizedUrl(provider.base_url_default) ||
						existing?.base_url_default ||
						DEFAULT_PROVIDER_BASE_URL,
					base_url_configured: true,
					api_key_env: provider.api_key_env ?? existing?.api_key_env ?? null,
					api_key_configured: Boolean(
						(ctx.modelSecrets[id]?.apiKey ?? "").trim(),
					),
				};
			});
			for (const providerId of Object.keys(ctx.modelSecrets)) {
				if (!nextProviderIds.has(providerId)) {
					delete ctx.modelSecrets[providerId];
				}
			}
			await ctx.persistSecrets();
		}
		if (body.models) {
			models.models = body.models.map((item) => ({
				id: item.id,
				label: item.label ?? item.id,
				supports_thinking: item.supports_thinking ?? false,
				default_thinking_enabled: item.default_thinking_enabled ?? false,
				request_kwargs: item.request_kwargs ?? {},
				thinking_enabled_request_kwargs:
					item.thinking_enabled_request_kwargs ?? {},
				thinking_disabled_request_kwargs:
					item.thinking_disabled_request_kwargs ?? {},
				thinking_disabled_model_name: item.thinking_disabled_model_name ?? null,
				reasoning_effort: item.reasoning_effort ?? null,
				no_temperature: item.no_temperature ?? true,
				thinking_enable_extra_body_type:
					item.thinking_enable_extra_body_type ?? null,
				thinking_disable_extra_body_type:
					item.thinking_disable_extra_body_type ?? null,
				thinking_disable_switch_model:
					item.thinking_disable_switch_model ?? null,
			}));
		}
		ctx.touchAdminConfig("Admin model config updated locally.");
		ctx.persist();
		return jsonResponse(ctx.adminConfigResponse());
	}
	if (resource === "tools" && method === "PATCH") {
		const body = parseJsonBody(init) as FocusAgentUpdateAdminToolConfigRequest;
		if (body.tools) {
			const existingTools = ctx.state.adminConfig.tools.tools;
			const defaultTools = defaultAdminConfig().tools.tools;
			const incomingTools = body.tools
				.filter((tool) => ANDROID_LOCAL_TOOL_NAME_SET.has(tool.name))
				.map((tool) => {
					const existing =
						existingTools.find((item) => item.name === tool.name) ??
						defaultTools.find((item) => item.name === tool.name);
					return {
						name: tool.name,
						label: tool.label ?? existing?.label ?? tool.name,
						description: tool.description ?? existing?.description ?? "",
						enabled: tool.enabled ?? existing?.enabled ?? true,
						settings: tool.settings ?? existing?.settings ?? {},
						metadata: tool.metadata ?? existing?.metadata ?? {},
					};
				});
			ctx.state.adminConfig.tools.tools = ANDROID_LOCAL_TOOL_NAMES.map(
				(toolName) =>
					incomingTools.find((tool) => tool.name === toolName) ??
					existingTools.find((tool) => tool.name === toolName) ??
					defaultTools.find((tool) => tool.name === toolName),
			).filter(
				(tool): tool is FocusAgentAdminConfig["tools"]["tools"][number] =>
					Boolean(tool),
			);
		}
		if (body.providers) {
			ctx.state.adminConfig.tools.providers = body.providers.map(
				(provider) => ({
					id: provider.id,
					enabled: provider.enabled ?? true,
					order: provider.order ?? null,
					metadata: provider.metadata ?? {},
					overrides: provider.overrides ?? [],
				}),
			);
		}
		ctx.touchAdminConfig("Admin tool config updated locally.");
		ctx.persist();
		return jsonResponse(ctx.adminConfigResponse());
	}
	if (resource === "skills" && method === "PATCH") {
		const body = parseJsonBody(init) as FocusAgentUpdateAdminSkillConfigRequest;
		const skills = ctx.state.adminConfig.skills;
		if (body.enabled !== undefined && body.enabled !== null) {
			skills.enabled = body.enabled;
		}
		if (body.skills) {
			const enabledBySkillId = new Map(
				body.skills.map((skill) => [skill.skill_id, skill.enabled]),
			);
			skills.catalog = skills.catalog.map((skill) => {
				const enabled = enabledBySkillId.get(skill.skill_id);
				return enabled === undefined ? skill : { ...skill, enabled };
			});
			skills.disabled_skill_ids = skills.catalog
				.filter((skill) => !skill.enabled)
				.map((skill) => skill.skill_id);
		}
		if (body.disabled_skill_ids) {
			const disabledSkillIds = new Set(body.disabled_skill_ids);
			skills.disabled_skill_ids = [...disabledSkillIds];
			skills.catalog = skills.catalog.map((skill) => ({
				...skill,
				enabled: !disabledSkillIds.has(skill.skill_id),
			}));
		}
		skills.requires_restart = false;
		ctx.touchAdminConfig("Admin skill config updated locally.");
		ctx.persist();
		return jsonResponse(ctx.adminConfigResponse());
	}
	if (resource === "policies" && method === "PATCH") {
		const body = parseJsonBody(
			init,
		) as FocusAgentUpdateAdminPolicyConfigRequest;
		ctx.state.adminConfig.policies.items = Object.entries(
			body.values ?? {},
		).map(([key, value]) => ({
			key,
			env_key: null,
			label: key,
			value,
			value_type: typeof value,
			source: "local",
			editable: true,
			sensitive: false,
			configured: true,
			requires_restart: false,
			description: null,
			options: [],
		}));
		ctx.touchAdminConfig("Admin policy config updated locally.");
		ctx.persist();
		return jsonResponse(ctx.adminConfigResponse());
	}
	return errorResponse(404, "Unsupported local admin config route.");
}

export function touchAdminConfig(
	ctx: LocalFocusAgentRuntime,
	message: string,
): void {
	ctx.state.adminConfig.updated_at = nowIso();
	ctx.state.adminConfig.updated_by = LOCAL_USER_ID;
	ctx.state.adminConfig.message = message;
	ctx.addAuditEvent("admin.config_update", "config", "local-runtime", {
		message,
	});
}
