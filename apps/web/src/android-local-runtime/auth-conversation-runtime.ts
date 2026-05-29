import type {
	FocusAgentAuditEventListResponse,
	FocusAgentConversationListResponse,
	FocusAgentConversationSummary,
	FocusAgentCreateConversationRequest,
	FocusAgentCreateUserRequest,
	FocusAgentLoginRequest,
	FocusAgentSessionListResponse,
	FocusAgentUpdateConversationRequest,
	FocusAgentUserListResponse,
} from "@focus-agent/web-sdk";
import { LOCAL_USER_ID } from "./constants";
import {
	emptyResponse,
	errorResponse,
	jsonResponse,
	nowIso,
	nullableString,
	parseJsonBody,
	stringValue,
} from "./helpers";
import type { LocalFocusAgentRuntime } from "./local-focus-agent-runtime";
import { authResponse, newThreadState, principal } from "./state";

export function handleAuth(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	init?: RequestInit,
): Response {
	const [resource, idOrAction, action] = segments;
	if (resource === "me" && method === "GET") {
		return jsonResponse(principal(ctx.currentUser()));
	}
	if (resource === "refresh" && method === "POST") {
		return jsonResponse(authResponse(ctx.currentUser()));
	}
	if (resource === "demo-token" && method === "POST") {
		return jsonResponse({
			access_token: "android-local-token",
			token_type: "bearer",
			expires_in_seconds: 86400,
			issuer: "focus-agent-android-local-runtime",
		});
	}
	if (resource === "login" && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentLoginRequest;
		const username = stringValue(body.username).trim();
		if (username) {
			ctx.currentUser().username = username;
			ctx.currentUser().display_name = username;
			ctx.persist();
		}
		return jsonResponse(authResponse(ctx.currentUser()));
	}
	if (resource === "register" && method === "POST") {
		const body = parseJsonBody(init) as Partial<FocusAgentCreateUserRequest>;
		const user = ctx.currentUser();
		user.username = nullableString(body.username) ?? user.username;
		user.display_name = nullableString(body.display_name) ?? user.display_name;
		user.tenant_id = nullableString(body.tenant_id) ?? user.tenant_id;
		user.updated_at = nowIso();
		ctx.persist();
		return jsonResponse(authResponse(user));
	}
	if (resource === "logout" && method === "POST") {
		return emptyResponse({ status: 204 });
	}
	if (resource === "change-password" && method === "POST") {
		ctx.currentUser().password_updated_at = nowIso();
		ctx.addAuditEvent("auth.change_password", "user", LOCAL_USER_ID);
		ctx.persist();
		return emptyResponse({ status: 204 });
	}
	if (resource === "sessions" && method === "GET") {
		return jsonResponse(ctx.sessionList(ctx.currentUser().user_id));
	}
	if (resource === "sessions" && action === "revoke" && method === "POST") {
		const session = ctx.state.sessions.find(
			(item) => item.session_id === idOrAction,
		);
		if (!session) return errorResponse(404, "Session not found.");
		session.revoked_at = nowIso();
		session.current = false;
		ctx.addAuditEvent("auth.session_revoke", "session", session.session_id);
		ctx.persist();
		return jsonResponse(session);
	}
	return errorResponse(404, "Unsupported local auth route.");
}

export function handleConversations(
	ctx: LocalFocusAgentRuntime,
	method: string,
	segments: string[],
	init?: RequestInit,
): Response {
	const [rootThreadId, action] = segments;
	if (!rootThreadId && method === "GET") {
		return jsonResponse({
			conversations: ctx.state.conversations,
		} satisfies FocusAgentConversationListResponse);
	}
	if (!rootThreadId && method === "POST") {
		const body = parseJsonBody(init) as FocusAgentCreateConversationRequest;
		const timestamp = nowIso();
		const threadId = ctx.nextId("thread", "local-thread");
		const title = nullableString(body.title) ?? "New local chat";
		ctx.state.threads[threadId] = newThreadState(threadId, threadId);
		const conversation: FocusAgentConversationSummary = {
			root_thread_id: threadId,
			title,
			is_archived: false,
			archived_at: null,
			created_at: timestamp,
			updated_at: timestamp,
		};
		ctx.state.conversations.unshift(conversation);
		ctx.persist();
		return jsonResponse(conversation);
	}
	const conversation = ctx.state.conversations.find(
		(item) => item.root_thread_id === rootThreadId,
	);
	if (!conversation) return errorResponse(404, "Conversation not found.");
	if (!action && method === "PATCH") {
		const body = parseJsonBody(init) as FocusAgentUpdateConversationRequest;
		conversation.title = stringValue(body.title).trim() || conversation.title;
		conversation.updated_at = nowIso();
		ctx.persist();
		return jsonResponse(conversation);
	}
	if (action === "archive" && method === "POST") {
		conversation.is_archived = true;
		conversation.archived_at = nowIso();
		conversation.updated_at = nowIso();
		ctx.persist();
		return jsonResponse(conversation);
	}
	if (action === "activate" && method === "POST") {
		conversation.is_archived = false;
		conversation.archived_at = null;
		conversation.updated_at = nowIso();
		ctx.persist();
		return jsonResponse(conversation);
	}
	return errorResponse(404, "Unsupported local conversation route.");
}

export function sessionList(
	ctx: LocalFocusAgentRuntime,
	userId: string,
	searchParams: URLSearchParams = new URLSearchParams(),
): FocusAgentSessionListResponse {
	const includeRevoked = searchParams.get("include_revoked") === "true";
	const items = ctx.state.sessions.filter(
		(session) =>
			session.user_id === userId && (includeRevoked || !session.revoked_at),
	);
	return { items, count: items.length };
}

export function userList(
	ctx: LocalFocusAgentRuntime,
	searchParams: URLSearchParams,
): FocusAgentUserListResponse {
	const query = (searchParams.get("query") ?? "").toLowerCase();
	const status = searchParams.getAll("status").filter(Boolean);
	const role = searchParams.getAll("role").filter(Boolean);
	const tenantId = searchParams.get("tenant_id");
	const limit = Number(searchParams.get("limit") ?? 50);
	const offset = Number(searchParams.get("offset") ?? 0);
	const items = ctx.state.users.filter((user) => {
		const text = [user.user_id, user.username, user.display_name, user.email]
			.join(" ")
			.toLowerCase();
		return (
			(!query || text.includes(query)) &&
			(!tenantId || user.tenant_id === tenantId) &&
			(status.length === 0 || status.includes(user.status)) &&
			(role.length === 0 || role.some((item) => user.roles.includes(item)))
		);
	});
	return {
		items: items.slice(offset, offset + limit),
		count: items.length,
		limit,
		offset,
	};
}

export function auditEvents(
	ctx: LocalFocusAgentRuntime,
	searchParams: URLSearchParams,
): FocusAgentAuditEventListResponse {
	const actor = searchParams.get("actor_user_id");
	const resourceType = searchParams.get("resource_type");
	const resourceId = searchParams.get("resource_id");
	const decision = searchParams.get("decision");
	const limit = Number(searchParams.get("limit") ?? 50);
	const offset = Number(searchParams.get("offset") ?? 0);
	const items = ctx.state.auditEvents.filter(
		(event) =>
			(!actor || event.actor_user_id === actor) &&
			(!resourceType || event.resource_type === resourceType) &&
			(!resourceId || event.resource_id === resourceId) &&
			(!decision || event.decision === decision),
	);
	return {
		items: items.slice(offset, offset + limit),
		count: items.length,
		limit,
		offset,
	};
}

export function touchConversation(
	ctx: LocalFocusAgentRuntime,
	rootThreadId: string,
	message: string,
): void {
	const conversation = ctx.state.conversations.find(
		(item) => item.root_thread_id === rootThreadId,
	);
	if (!conversation) return;
	conversation.updated_at = nowIso();
	if (
		message.trim() &&
		(!conversation.title || conversation.title === "New local chat")
	) {
		conversation.title = message.trim().slice(0, 48);
	}
}
