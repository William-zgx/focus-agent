import { FocusAgentRequestError } from "@focus-agent/web-sdk";

export const THREAD_BUSY_RETRY_ATTEMPTS = 80;
export const THREAD_BUSY_RETRY_DELAY_MS = 500;

export class ThreadBranchActionRetryCancelled extends Error {
	constructor() {
		super("Branch action request was cancelled.");
		this.name = "ThreadBranchActionRetryCancelled";
	}
}

function isThreadBusyConflict(error: unknown): boolean {
	if (!(error instanceof FocusAgentRequestError) || error.status !== 409) {
		return false;
	}
	const text = [error.message, JSON.stringify(error.data ?? {})]
		.join(" ")
		.toLowerCase();
	return text.includes("still processing") || text.includes("previous turn");
}

function delay(ms: number) {
	return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function retryThreadBusyConflict<T>(
	operation: () => Promise<T>,
	shouldContinue: () => boolean = () => true,
): Promise<T> {
	let lastError: unknown;
	for (let attempt = 0; attempt < THREAD_BUSY_RETRY_ATTEMPTS; attempt += 1) {
		if (!shouldContinue()) {
			throw new ThreadBranchActionRetryCancelled();
		}
		try {
			const result = await operation();
			if (!shouldContinue()) {
				throw new ThreadBranchActionRetryCancelled();
			}
			return result;
		} catch (error) {
			lastError = error;
			if (error instanceof ThreadBranchActionRetryCancelled) {
				throw error;
			}
			if (!isThreadBusyConflict(error)) {
				throw error;
			}
			await delay(THREAD_BUSY_RETRY_DELAY_MS);
		}
	}
	throw lastError;
}
