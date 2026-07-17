import type {
	FocusAgentAskUserQuestionAnswer,
	FocusAgentAskUserQuestionInterrupt,
} from "@focus-agent/web-sdk";
import { useMemo, useState } from "react";

const OTHER_LABEL = "Other";

interface AskUserQuestionCardProps {
	interrupt: FocusAgentAskUserQuestionInterrupt;
	isBusy?: boolean;
	isChineseUi?: boolean;
	isReadOnly?: boolean;
	errorMessage?: string;
	onSubmit?: (
		interrupt: FocusAgentAskUserQuestionInterrupt,
		answers: FocusAgentAskUserQuestionAnswer[],
	) => void;
}

type DraftState = Record<
	string,
	{
		selected: string[];
		otherText: string;
		useOther: boolean;
	}
>;

function buildInitialDraft(
	interrupt: FocusAgentAskUserQuestionInterrupt,
): DraftState {
	const draft: DraftState = {};
	for (const question of interrupt.questions) {
		draft[question.id] = {
			selected: [],
			otherText: "",
			useOther: false,
		};
	}
	return draft;
}

export function AskUserQuestionCard({
	interrupt,
	isBusy = false,
	isChineseUi = false,
	isReadOnly = false,
	errorMessage,
	onSubmit,
}: AskUserQuestionCardProps) {
	const [draft, setDraft] = useState<DraftState>(() =>
		buildInitialDraft(interrupt),
	);
	const [localError, setLocalError] = useState("");

	const canAct = Boolean(onSubmit) && !isReadOnly && !isBusy;
	const title = isChineseUi
		? "需要你确认几个选择"
		: "A few choices need your input";
	const subtitle = isChineseUi
		? "回答后运行会继续。每题可选 Other 填写自定义内容。"
		: "The run pauses until you answer. Use Other for custom text.";

	const validationMessage = useMemo(() => {
		for (const question of interrupt.questions) {
			const row = draft[question.id];
			if (!row)
				return isChineseUi
					? "请完成所有问题。"
					: "Please complete every question.";
			const selectedCount =
				row.selected.length + (row.useOther && row.otherText.trim() ? 1 : 0);
			if (question.multi_select) {
				if (selectedCount < 1) {
					return isChineseUi
						? `请为「${question.header}」至少选择一项。`
						: `Select at least one option for "${question.header}".`;
				}
			} else if (selectedCount !== 1) {
				return isChineseUi
					? `请为「${question.header}」选择一项。`
					: `Select exactly one option for "${question.header}".`;
			}
			if (row.useOther && !row.otherText.trim()) {
				return isChineseUi
					? `请为「${question.header}」填写 Other 内容。`
					: `Enter custom text for Other on "${question.header}".`;
			}
		}
		return "";
	}, [draft, interrupt.questions, isChineseUi]);

	function toggleSingle(questionId: string, label: string) {
		setDraft((current) => ({
			...current,
			[questionId]: {
				selected: [label],
				otherText: current[questionId]?.otherText ?? "",
				useOther: false,
			},
		}));
		setLocalError("");
	}

	function toggleMulti(questionId: string, label: string) {
		setDraft((current) => {
			const row = current[questionId] ?? {
				selected: [],
				otherText: "",
				useOther: false,
			};
			const exists = row.selected.includes(label);
			return {
				...current,
				[questionId]: {
					...row,
					selected: exists
						? row.selected.filter((item) => item !== label)
						: [...row.selected, label],
				},
			};
		});
		setLocalError("");
	}

	function toggleOther(questionId: string, multiSelect: boolean) {
		setDraft((current) => {
			const row = current[questionId] ?? {
				selected: [],
				otherText: "",
				useOther: false,
			};
			const nextUseOther = !row.useOther;
			return {
				...current,
				[questionId]: {
					selected: multiSelect ? row.selected : [],
					otherText: row.otherText,
					useOther: nextUseOther,
				},
			};
		});
		setLocalError("");
	}

	function handleSubmit() {
		if (validationMessage) {
			setLocalError(validationMessage);
			return;
		}
		const answers: FocusAgentAskUserQuestionAnswer[] = interrupt.questions.map(
			(question) => {
				const row = draft[question.id];
				const selected_labels = [...(row?.selected ?? [])];
				if (row?.useOther) {
					selected_labels.push(OTHER_LABEL);
				}
				return {
					question_id: question.id,
					selected_labels,
					other_text: row?.useOther ? row.otherText.trim() : null,
				};
			},
		);
		onSubmit?.(interrupt, answers);
	}

	return (
		<article className="fa-ask-user-question-card">
			<div className="fa-ask-user-question-card-header">
				<div>
					<div className="fa-ask-user-question-card-title">{title}</div>
					<div className="fa-ask-user-question-card-subtitle">{subtitle}</div>
					<div className="fa-ask-user-question-card-meta">
						<code>{interrupt.tool_name}</code>
						<span>{interrupt.interrupt_id}</span>
					</div>
				</div>
				<span className="fa-ask-user-question-card-badge">
					{isChineseUi ? "等待回答" : "Awaiting answers"}
				</span>
			</div>

			<div className="fa-ask-user-question-card-body">
				{interrupt.questions.map((question) => {
					const row = draft[question.id] ?? {
						selected: [],
						otherText: "",
						useOther: false,
					};
					return (
						<section
							key={question.id}
							className="fa-ask-user-question-item"
							aria-labelledby={`ask-q-${interrupt.tool_call_id}-${question.id}`}
						>
							<div className="fa-ask-user-question-item-header">
								<span className="fa-ask-user-question-item-tag">
									{question.header}
								</span>
								{question.multi_select ? (
									<span className="fa-ask-user-question-item-mode">
										{isChineseUi ? "多选" : "Multi-select"}
									</span>
								) : null}
							</div>
							<p
								className="fa-ask-user-question-item-question"
								id={`ask-q-${interrupt.tool_call_id}-${question.id}`}
							>
								{question.question}
							</p>
							<fieldset className="fa-ask-user-question-options">
								{question.options.map((option) => {
									const checked = row.selected.includes(option.label);
									const inputId = `${interrupt.tool_call_id}-${question.id}-${option.label}`;
									return (
										<label
											key={option.label}
											className={`fa-ask-user-question-option${checked ? " is-selected" : ""}`}
											htmlFor={inputId}
										>
											<input
												checked={checked}
												disabled={!canAct}
												id={inputId}
												name={`${interrupt.tool_call_id}-${question.id}`}
												type={question.multi_select ? "checkbox" : "radio"}
												onChange={() =>
													question.multi_select
														? toggleMulti(question.id, option.label)
														: toggleSingle(question.id, option.label)
												}
											/>
											<span className="fa-ask-user-question-option-copy">
												<span className="fa-ask-user-question-option-label">
													{option.label}
												</span>
												{option.description ? (
													<span className="fa-ask-user-question-option-description">
														{option.description}
													</span>
												) : null}
												{option.preview ? (
													<span className="fa-ask-user-question-option-preview">
														{option.preview}
													</span>
												) : null}
											</span>
										</label>
									);
								})}
								<label
									className={`fa-ask-user-question-option${row.useOther ? " is-selected" : ""}`}
									htmlFor={`${interrupt.tool_call_id}-${question.id}-other`}
								>
									<input
										checked={row.useOther}
										disabled={!canAct}
										id={`${interrupt.tool_call_id}-${question.id}-other`}
										name={`${interrupt.tool_call_id}-${question.id}`}
										type={question.multi_select ? "checkbox" : "radio"}
										onChange={() =>
											toggleOther(question.id, question.multi_select)
										}
									/>
									<span className="fa-ask-user-question-option-copy">
										<span className="fa-ask-user-question-option-label">
											{isChineseUi ? "其他" : OTHER_LABEL}
										</span>
										<span className="fa-ask-user-question-option-description">
											{isChineseUi
												? "用自定义文本回答"
												: "Provide a custom free-text answer"}
										</span>
									</span>
								</label>
								{row.useOther ? (
									<input
										className="fa-ask-user-question-other-input"
										disabled={!canAct}
										placeholder={
											isChineseUi
												? "输入自定义答案…"
												: "Type your custom answer…"
										}
										type="text"
										value={row.otherText}
										onChange={(event) => {
											const value = event.target.value;
											setDraft((current) => ({
												...current,
												[question.id]: {
													...(current[question.id] ?? {
														selected: [],
														otherText: "",
														useOther: true,
													}),
													otherText: value,
													useOther: true,
												},
											}));
											setLocalError("");
										}}
									/>
								) : null}
							</fieldset>
						</section>
					);
				})}
			</div>

			{localError || errorMessage ? (
				<div className="fa-ask-user-question-card-error">
					{localError || errorMessage}
				</div>
			) : null}

			<div className="fa-ask-user-question-card-actions">
				<button
					className="fa-branch-action-button is-primary"
					disabled={!canAct}
					type="button"
					onClick={handleSubmit}
				>
					{isBusy
						? isChineseUi
							? "提交中…"
							: "Submitting…"
						: isChineseUi
							? "提交答案并继续"
							: "Submit answers"}
				</button>
			</div>
		</article>
	);
}
