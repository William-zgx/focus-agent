export type MissionPreset = {
	id: string;
	title: string;
	titleEn: string;
	description: string;
	descriptionEn: string;
	goal: string;
	goalEn: string;
};

export type MissionCollaborationMode = {
	id: string;
	title: string;
	titleEn: string;
	description: string;
	descriptionEn: string;
	granularity: "coarse" | "balanced" | "detailed";
	focus: "implementation" | "verification" | "auto";
	maxTasks: number;
};

export const MISSION_PRESETS: MissionPreset[] = [
	{
		id: "ship",
		title: "做功能",
		titleEn: "Build feature",
		description: "描述目标，自动拆成交付 DAG。",
		descriptionEn: "Describe the goal; Agent Team compiles the delivery DAG.",
		goal: "想达成什么：\n最终需要什么结果：\n已有上下文、约束或风险：",
		goalEn:
			"What to achieve:\nFinal result needed:\nKnown context, constraints, or risks:",
	},
	{
		id: "diagnose",
		title: "查问题",
		titleEn: "Find issue",
		description: "说明现象，自动安排定位与验证。",
		descriptionEn:
			"Describe the symptom; Agent Team plans investigation and verification.",
		goal: "现象：\n已知线索：\n希望得到的结论：",
		goalEn: "Symptom:\nKnown clues:\nDecision needed:",
	},
	{
		id: "review",
		title: "看改动",
		titleEn: "Review changes",
		description: "给出对象，自动拆风险和证据检查。",
		descriptionEn:
			"Provide the target; Agent Team splits risk and evidence checks.",
		goal: "审查对象：\n重点风险：\n希望输出：",
		goalEn: "Review target:\nKey risks:\nExpected output:",
	},
	{
		id: "research",
		title: "做调研",
		titleEn: "Research",
		description: "提出问题，自动拆比较与建议。",
		descriptionEn:
			"Ask the question; Agent Team splits comparison and recommendation work.",
		goal: "要决策的问题：\n约束条件：\n需要比较或验证的方向：",
		goalEn:
			"Decision to make:\nConstraints:\nOptions or assumptions to compare:",
	},
];

export const COLLABORATION_MODES: MissionCollaborationMode[] = [
	{
		id: "fast",
		title: "快一点",
		titleEn: "Fast",
		description: "少拆任务，尽快给结果。",
		descriptionEn:
			"Fewer agents, optimized for implementation and quick closure.",
		granularity: "coarse",
		focus: "implementation",
		maxTasks: 4,
	},
	{
		id: "balanced",
		title: "稳一点",
		titleEn: "Balanced",
		description: "兼顾执行和检查。",
		descriptionEn: "Balanced implementation and verification for most changes.",
		granularity: "balanced",
		focus: "verification",
		maxTasks: 6,
	},
	{
		id: "detailed",
		title: "细一点",
		titleEn: "Detailed",
		description: "拆得更细，检查更多。",
		descriptionEn: "More agents with finer-grained split and acceptance.",
		granularity: "detailed",
		focus: "auto",
		maxTasks: 8,
	},
];
