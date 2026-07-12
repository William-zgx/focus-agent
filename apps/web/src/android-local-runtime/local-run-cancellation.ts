interface LocalRunCancellationRegistration {
	controller: AbortController;
	detachRequestSignal: () => void;
	threadId: string;
}

export class LocalRunCancellationRegistry {
	private readonly registrations = new Map<
		string,
		LocalRunCancellationRegistration
	>();
	private readonly runIdsByThread = new Map<string, Set<string>>();

	get size(): number {
		return this.registrations.size;
	}

	runIds(): string[] {
		return [...this.registrations.keys()];
	}

	register(
		runId: string,
		threadId: string,
		requestSignal?: AbortSignal,
	): AbortSignal {
		const controller = new AbortController();
		const forwardRequestAbort = () => {
			if (!controller.signal.aborted) {
				controller.abort(
					requestSignal?.reason ?? new DOMException("Aborted", "AbortError"),
				);
			}
		};
		let detachRequestSignal = () => {};
		if (requestSignal) {
			if (requestSignal.aborted) {
				forwardRequestAbort();
			} else {
				requestSignal.addEventListener("abort", forwardRequestAbort, {
					once: true,
				});
				detachRequestSignal = () =>
					requestSignal.removeEventListener("abort", forwardRequestAbort);
			}
		}
		this.registrations.set(runId, {
			controller,
			detachRequestSignal,
			threadId,
		});
		const threadRunIds = this.runIdsByThread.get(threadId) ?? new Set<string>();
		threadRunIds.add(runId);
		this.runIdsByThread.set(threadId, threadRunIds);
		return controller.signal;
	}

	release(runId: string): void {
		const registration = this.registrations.get(runId);
		if (!registration) return;
		registration.detachRequestSignal();
		this.registrations.delete(runId);
		const threadRunIds = this.runIdsByThread.get(registration.threadId);
		threadRunIds?.delete(runId);
		if (threadRunIds?.size === 0) {
			this.runIdsByThread.delete(registration.threadId);
		}
	}

	cancel(runId: string, action: "interrupt" | "rollback"): boolean {
		const registration = this.registrations.get(runId);
		if (!registration) return false;
		if (!registration.controller.signal.aborted) {
			registration.controller.abort(
				new DOMException(`Run ${action} requested.`, "AbortError"),
			);
		}
		return true;
	}

	cancelThread(threadId: string, action: "interrupt" | "rollback"): string[] {
		const runIds = [...(this.runIdsByThread.get(threadId) ?? [])];
		return runIds.filter((runId) => this.cancel(runId, action));
	}
}
