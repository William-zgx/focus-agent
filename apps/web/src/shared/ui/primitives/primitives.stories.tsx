import {
	Badge,
	Button,
	Card,
	EmptyState,
	IconButton,
	Input,
	Modal,
	Select,
	Skeleton,
	Surface,
	Tabs,
	Textarea,
	Toast,
} from ".";

export function PrimitiveCatalog() {
	return (
		<Surface className="grid gap-6 p-6" tone="section">
			<Card
				tone="elevated"
				header={<h2 className="m-0 text-[length:var(--fa-fs-xl)]">Buttons</h2>}
			>
				<div className="flex flex-wrap gap-3">
					<Button variant="primary">Primary</Button>
					<Button variant="secondary">Secondary</Button>
					<Button variant="ghost">Ghost</Button>
					<Button variant="danger">Danger</Button>
					<IconButton label="Refresh">↻</IconButton>
				</div>
			</Card>

			<Card header="Form controls">
				<div className="grid gap-3 md:grid-cols-3">
					<Input aria-label="Name" placeholder="Name" />
					<Select aria-label="Status" defaultValue="ready">
						<option value="ready">Ready</option>
						<option value="blocked">Blocked</option>
					</Select>
					<Textarea aria-label="Notes" placeholder="Notes" />
				</div>
			</Card>

			<Card header="Status language">
				<div className="flex flex-wrap gap-2">
					<Badge tone="status">Status</Badge>
					<Badge tone="role">Planner</Badge>
					<Badge tone="info">Info</Badge>
					<Badge tone="warning">Warning</Badge>
					<Badge tone="danger">Danger</Badge>
					<Badge tone="success">Success</Badge>
				</div>
			</Card>

			<Tabs
				activeId="overview"
				onChange={() => undefined}
				items={[
					{ id: "overview", label: "Overview", panel: <Skeleton lines={3} /> },
					{
						id: "details",
						label: "Details",
						panel: <EmptyState title="No details" />,
					},
				]}
			/>

			<Toast tone="info">Toast and inline notification styling.</Toast>
			<Modal open={false} title="Modal preview">
				Modal content
			</Modal>
		</Surface>
	);
}

export function Default() {
	return <PrimitiveCatalog />;
}

export function Disabled() {
	return (
		<Surface className="grid gap-4 p-6" tone="section">
			<Button disabled>Disabled</Button>
			<Input disabled placeholder="Disabled" />
			<IconButton disabled label="Disabled">
				-
			</IconButton>
		</Surface>
	);
}

export function Loading() {
	return (
		<Surface className="grid gap-4 p-6" tone="section">
			<Button aria-busy="true">Loading</Button>
			<Skeleton lines={4} />
			<Toast tone="info">Loading latest state</Toast>
		</Surface>
	);
}
