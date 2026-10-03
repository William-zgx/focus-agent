# User systemd service

Run these commands from the deployed checkout that contains the existing
`.focus_agent/local.env` and data, not from a review worktree. The checked-in
user unit runs the already-built application. It uses `make api`, so starting
or restarting the service never rebuilds the Web bundle. Build once before
the first start and whenever frontend sources change:

```bash
make web-build
```

Install the unit under a separate name and record the repository path outside
the unit file. This leaves any existing `focus-agent.service` file untouched:

```bash
test -f .focus_agent/local.env
mkdir -p "$HOME/.config/focus-agent" "$HOME/.config/systemd/user"
printf 'FOCUS_AGENT_ROOT=%s\nAPI_HOST=127.0.0.1\nAPI_PORT=8000\nWEB_APP_DEV_SERVER_URL=\n' "$PWD" \
  >"$HOME/.config/focus-agent/service.env"
install -m 0644 deploy/systemd/focus-agent-prod.service \
  "$HOME/.config/systemd/user/focus-agent-prod.service"
systemctl --user daemon-reload
```

The unit checks for `apps/web/dist/index.html` before starting. It also clears
`WEB_APP_DEV_SERVER_URL` so the API serves that static bundle even if the local
configuration contains a Vite development URL. The runtime still loads
`.focus_agent/local.env` from `FOCUS_AGENT_ROOT`, so existing database paths
and other local settings remain in place. Installing the unit does not migrate
or replace application data.

Before the first start, inspect any older Focus Agent units using the same
port. Stop the old transient unit, and disable an older enabled unit only if
it belongs to this deployment; retain its unit file for rollback. Then enable
and start the new unit. Do not run two units on port 8000 at once.

Use these entry points for routine operation:

```bash
systemctl --user enable --now focus-agent-prod.service
systemctl --user restart focus-agent-prod.service
systemctl --user status focus-agent-prod.service
journalctl --user -u focus-agent-prod.service -f
```

After a start or restart, verify both the API readiness response and the served
Web application:

```bash
curl --fail --show-error http://127.0.0.1:8000/readyz
curl --fail --show-error --output /dev/null http://127.0.0.1:8000/app
```
