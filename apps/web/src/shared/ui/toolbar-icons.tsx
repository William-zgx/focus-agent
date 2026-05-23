import type { ReactNode, SVGProps } from "react";

type ToolbarIconProps = Omit<SVGProps<SVGSVGElement>, "children">;

function ToolbarIcon({
	children,
	...props
}: ToolbarIconProps & { children: ReactNode }) {
	return (
		<svg
			aria-hidden="true"
			fill="none"
			stroke="currentColor"
			strokeLinecap="round"
			strokeLinejoin="round"
			strokeWidth="1.85"
			viewBox="0 0 24 24"
			{...props}
		>
			{children}
		</svg>
	);
}

export function BranchFocusIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M8 5.4v13.2" />
			<path d="M8 10.4h3.6c2.9 0 4.8 1.9 4.8 4.8" />
			<circle cx="8" cy="5.4" r="1.3" />
			<circle cx="8" cy="18.6" r="1.3" />
			<circle cx="16.4" cy="15.2" r="2.05" />
			<circle cx="16.4" cy="15.2" r="0.48" fill="currentColor" stroke="none" />
		</ToolbarIcon>
	);
}

export function BranchPlusIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M8 5.2v13.6" />
			<path d="M8 10.2h3.4c2.8 0 4.5 1.7 4.5 4.5V17" />
			<circle cx="8" cy="5.2" r="1.35" />
			<circle cx="8" cy="18.8" r="1.35" />
			<path d="M17.2 4.6v5.2" />
			<path d="M14.6 7.2h5.2" />
		</ToolbarIcon>
	);
}

export function NewConversationIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M12 5v14" />
			<path d="M5 12h14" />
		</ToolbarIcon>
	);
}

export function ConversationActionsIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<circle cx="6.6" cy="12" r="1.25" fill="currentColor" stroke="none" />
			<circle cx="12" cy="12" r="1.25" fill="currentColor" stroke="none" />
			<circle cx="17.4" cy="12" r="1.25" fill="currentColor" stroke="none" />
		</ToolbarIcon>
	);
}

export function ConclusionDraftIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M7 3.5h6.2L18 8.3V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1.5-1.5Z" />
			<path d="M13 3.8V8h4.2" />
			<path d="M9 13h3.2" />
			<path d="M9 17h5" />
			<path d="m16.5 11 .6 1.2 1.3.6-1.3.6-.6 1.3-.6-1.3-1.3-.6 1.3-.6.6-1.2Z" />
		</ToolbarIcon>
	);
}

export function ConclusionReadyIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M7 3.5h6.2L18 8.3V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1.5-1.5Z" />
			<path d="M13 3.8V8h4.2" />
			<path d="m9 14.2 2 2 4-4.4" />
		</ToolbarIcon>
	);
}

export function RefreshConclusionIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M7 3.5h6.2L18 8.3V20a1.5 1.5 0 0 1-1.5 1.5h-9A1.5 1.5 0 0 1 6 20V5a1.5 1.5 0 0 1 1.5-1.5Z" />
			<path d="M13 3.8V8h4.2" />
			<path d="M15 14a3.2 3.2 0 0 1-5.5 2.2" />
			<path d="M9 14a3.2 3.2 0 0 1 5.5-2.2" />
			<path d="M14.7 9.8v2.2h-2.2" />
			<path d="M9.3 18.2V16h2.2" />
		</ToolbarIcon>
	);
}

export function BackToThreadIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M11 6 5 12l6 6" />
			<path d="M6 12h9a4 4 0 0 1 4 4v1" />
		</ToolbarIcon>
	);
}

export function BackToMainIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="m4 11 8-7 8 7" />
			<path d="M6.5 10.2V20h11v-9.8" />
			<path d="M10 20v-5h4v5" />
		</ToolbarIcon>
	);
}

export function BackToParentIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M9 7 4 12l5 5" />
			<path d="M5 12h8a5 5 0 0 1 5 5v1" />
			<circle cx="18" cy="6" r="2" />
		</ToolbarIcon>
	);
}

export function AgentTeamIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<circle cx="9" cy="8" r="3" />
			<path d="M4.5 19c.6-3 2.1-4.5 4.5-4.5s3.9 1.5 4.5 4.5" />
			<path d="M15.5 11.5a2.5 2.5 0 1 0-1.1-4.7" />
			<path d="M15.5 14.5c2 .2 3.3 1.5 4 4" />
		</ToolbarIcon>
	);
}

export function ProductivityIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M7.2 4.5h9.6A1.7 1.7 0 0 1 18.5 6.2v11.6a1.7 1.7 0 0 1-1.7 1.7H7.2a1.7 1.7 0 0 1-1.7-1.7V6.2a1.7 1.7 0 0 1 1.7-1.7Z" />
			<path d="M9 8h6" />
			<path d="M9 12h6" />
			<path d="M9 16h3.4" />
			<path d="m14.1 15.8 1.1 1.1 2-2.4" />
		</ToolbarIcon>
	);
}

export function ChatBubbleIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M5.5 5.5h13v8.8a2 2 0 0 1-2 2H10l-4 3v-3H5.5a2 2 0 0 1-2-2V7.5a2 2 0 0 1 2-2Z" />
			<path d="M7.5 9.2h7" />
			<path d="M7.5 12.4h4.8" />
		</ToolbarIcon>
	);
}

export function AdminConsoleIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M12 3.5 18 6v5.2c0 3.6-2.3 6.9-6 9.1-3.7-2.2-6-5.5-6-9.1V6l6-2.5Z" />
			<path d="M9 11.5h6" />
			<path d="M12 8.5v6" />
		</ToolbarIcon>
	);
}

export function SessionExitIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M10 5H6.5A1.5 1.5 0 0 0 5 6.5v11A1.5 1.5 0 0 0 6.5 19H10" />
			<path d="M13 8.2 16.8 12 13 15.8" />
			<path d="M8.5 12h8" />
		</ToolbarIcon>
	);
}

export function TokenUsageIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M4 19V5" />
			<path d="M4 19h16" />
			<rect x="7" y="12" width="2.8" height="4" rx="0.8" />
			<rect x="11.2" y="9" width="2.8" height="7" rx="0.8" />
			<rect x="15.4" y="6" width="2.8" height="10" rx="0.8" />
		</ToolbarIcon>
	);
}

export function ArchiveIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M4 6h16v4H4z" />
			<path d="M6 10v8.5A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V10" />
			<path d="M9.5 14h5" />
		</ToolbarIcon>
	);
}

export function ArchiveRestoreIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M4 6h16v4H4z" />
			<path d="M6 10v8.5A1.5 1.5 0 0 0 7.5 20h9a1.5 1.5 0 0 0 1.5-1.5V10" />
			<path d="M12 17v-5" />
			<path d="m9.8 14.2 2.2-2.2 2.2 2.2" />
		</ToolbarIcon>
	);
}

export function RenameConversationIcon(props: ToolbarIconProps) {
	return (
		<ToolbarIcon {...props}>
			<path d="M5 19h14" />
			<path d="M7.2 15.8 15.9 7.1a1.6 1.6 0 0 1 2.3 2.3l-8.7 8.7-3.2.9.9-3.2Z" />
			<path d="m14.6 8.4 2.3 2.3" />
		</ToolbarIcon>
	);
}
