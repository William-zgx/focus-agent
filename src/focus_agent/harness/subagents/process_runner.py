"""Process-isolated subagent runner.

Spawns an independent OS process via :mod:`asyncio.subprocess` to execute a
task with the ``focus-agent`` CLI. This provides hard isolation (separate
memory space, separate event loop, killable on timeout) and is inspired by
pi's subagent extension pattern.

The runner communicates with the child over stdin/stdout. The child is
expected to accept a ``--task`` (or ``task run``) command that emits a
JSON result on stdout; stderr is captured for diagnostics. On timeout the
child receives SIGTERM first, then SIGKILL after
``graceful_shutdown_seconds``.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("focus_agent.harness.subagents.process_runner")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProcessSubagentConfig:
    """Configuration for a single process-isolated subagent invocation."""

    model: str
    system_prompt: str
    tools_allowed: list[str] = field(default_factory=lambda: ["*"])
    max_output_chars: int = 50_000
    timeout_seconds: float = 300.0
    graceful_shutdown_seconds: float = 5.0


@dataclass
class ProcessSubagentResult:
    """Result of a completed (or failed) process subagent run."""

    success: bool
    output: str
    error: str | None
    return_code: int
    duration_seconds: float
    token_usage: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


class ProcessSubagentRunner:
    """Run subagent tasks in isolated OS processes.

    Parameters
    ----------
    cli_entry_point:
        The CLI executable name (resolved on ``$PATH``) or absolute path to
        the focus-agent binary. Defaults to ``"focus-agent"``.
    """

    def __init__(self, cli_entry_point: str = "focus-agent") -> None:
        self._cli_entry_point = cli_entry_point

    async def run(
        self,
        config: ProcessSubagentConfig,
        task: str,
        thread_id: str,
    ) -> ProcessSubagentResult:
        """Execute ``task`` in a child process and return its result.

        On timeout the child is sent SIGTERM; if it does not exit within
        ``config.graceful_shutdown_seconds`` it receives SIGKILL. Stdout is
        parsed for a JSON result envelope; if parsing fails the raw output
        is returned verbatim.
        """
        command = self._build_command(config, task, thread_id)
        started = time.monotonic()
        logger.info(
            "ProcessSubagentRunner: spawning thread=%s model=%s cmd=%s",
            thread_id,
            config.model,
            " ".join(command),
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *command,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "FOCUS_AGENT_SUBAGENT": "1"},
            )
        except FileNotFoundError as exc:
            duration = time.monotonic() - started
            logger.error("ProcessSubagentRunner: CLI binary not found: %s", exc)
            return ProcessSubagentResult(
                success=False,
                output="",
                error=f"CLI entry point not found: {self._cli_entry_point}",
                return_code=-1,
                duration_seconds=duration,
            )

        return_code, stdout_bytes, stderr_bytes = await self._wait_with_output(
            proc,
            timeout=config.timeout_seconds,
            graceful=config.graceful_shutdown_seconds,
        )
        duration = time.monotonic() - started

        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")

        if len(stdout_text) > config.max_output_chars:
            truncated_note = f"\n\n[truncated: output exceeded {config.max_output_chars} chars]"
            stdout_text = stdout_text[: config.max_output_chars] + truncated_note

        output, token_usage, parse_error = self._parse_output(stdout_text)
        success = return_code == 0 and parse_error is None
        error_msg: str | None = None
        if not success:
            parts = []
            if return_code != 0:
                parts.append(f"process exited with code {return_code}")
            if stderr_text.strip():
                parts.append(f"stderr: {stderr_text.strip()[-2000:]}")
            if parse_error:
                parts.append(f"parse error: {parse_error}")
            error_msg = "; ".join(parts) if parts else "unknown error"

        logger.info(
            "ProcessSubagentRunner: finished thread=%s rc=%s success=%s dur=%.2fs",
            thread_id,
            return_code,
            success,
            duration,
        )

        return ProcessSubagentResult(
            success=success,
            output=output,
            error=error_msg,
            return_code=return_code,
            duration_seconds=duration,
            token_usage=token_usage,
        )

    # -- helpers -----------------------------------------------------------

    def _build_command(
        self,
        config: ProcessSubagentConfig,
        task: str,
        thread_id: str,
    ) -> list[str]:
        """Build the CLI argument list for the child process."""
        cmd: list[str] = [
            self._cli_entry_point,
            "task",
            "run",
            "--thread-id",
            thread_id,
            "--model",
            config.model,
        ]
        if config.system_prompt:
            cmd.extend(["--system-prompt", config.system_prompt])
        if config.tools_allowed and "*" not in config.tools_allowed:
            cmd.extend(["--tools", ",".join(config.tools_allowed)])
        cmd.append("--task")
        cmd.append(task)
        return cmd

    async def _wait_with_output(
        self,
        proc: asyncio.subprocess.Process,
        timeout: float,
        graceful: float,
    ) -> tuple[int, bytes, bytes]:
        """Wait for ``proc`` to exit, enforcing timeout + graceful shutdown.

        Captures stdout/stderr via :meth:`asyncio.subprocess.Process.communicate`
        so no bytes are lost even when the child is killed mid-flight.

        Returns ``(return_code, stdout_bytes, stderr_bytes)``.
        """
        comm_task: asyncio.Task[tuple[bytes, bytes]] | None = None
        try:
            comm_task = asyncio.create_task(proc.communicate())
            stdout_bytes, stderr_bytes = await asyncio.wait_for(comm_task, timeout=timeout)
            return proc.returncode or 0, stdout_bytes, stderr_bytes
        except TimeoutError:
            logger.warning(
                "ProcessSubagentRunner: timeout after %.1fs; sending SIGTERM (pid=%s)",
                timeout,
                proc.pid,
            )
            if comm_task is not None:
                comm_task.cancel()
            # Terminate and give it a grace period.
            if proc.returncode is None:
                try:
                    proc.terminate()
                except ProcessLookupError:
                    return proc.returncode or -signal.SIGTERM, b"", b""
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(), timeout=graceful
                )
                return proc.returncode or -signal.SIGTERM, stdout_bytes, stderr_bytes
            except TimeoutError:
                logger.warning(
                    "ProcessSubagentRunner: graceful shutdown expired; sending SIGKILL (pid=%s)",
                    proc.pid,
                )
                try:
                    proc.kill()
                except ProcessLookupError:
                    return proc.returncode or -signal.SIGKILL, b"", b""
                try:
                    stdout_bytes, stderr_bytes = await proc.communicate()
                except Exception:  # noqa: BLE001
                    stdout_bytes, stderr_bytes = b"", b""
                return -signal.SIGKILL, stdout_bytes, stderr_bytes
        except Exception:  # noqa: BLE001
            logger.exception("ProcessSubagentRunner: unexpected error waiting for child")
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
            return -1, b"", b""

    @staticmethod
    def _parse_output(raw: str) -> tuple[str, dict[str, Any] | None, str | None]:
        """Parse child stdout into ``(output_text, token_usage, error)``.

        Supports two output modes:
        - A trailing JSON line ``{"result": "...", "token_usage": {...}}``
        - Plain text output (returned verbatim, no token usage)
        """
        text = raw.strip()
        if not text:
            return "", None, None
        # Try to locate a JSON envelope at the tail of the output.
        # We scan from the last newline to allow log lines above the envelope.
        candidate = text
        for sep in ("\n", "\r\n"):
            if sep in text:
                candidate = text.rsplit(sep, 1)[-1].strip()
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                output = str(parsed.get("result") or parsed.get("output") or text)
                usage = (
                    parsed.get("token_usage")
                    if isinstance(parsed.get("token_usage"), dict)
                    else None
                )
                return output, usage, None
        except (json.JSONDecodeError, ValueError):
            pass
        # No JSON envelope found; treat entire output as the result.
        return text, None, None


__all__ = [
    "ProcessSubagentConfig",
    "ProcessSubagentResult",
    "ProcessSubagentRunner",
    "ProcessSubagentTaskRunner",
]


# ---------------------------------------------------------------------------
# SubagentTaskRunner protocol adapter
# ---------------------------------------------------------------------------


class ProcessSubagentTaskRunner:
    """Adapter that exposes :class:`ProcessSubagentRunner` through the
    ``SubagentTaskRunner`` Protocol used by :class:`SubagentExecutor`.

    Translates a ``SubagentTaskRequest`` into a ``ProcessSubagentConfig``
    plus task text, invokes the process runner, and maps the result back
    to a ``SubagentTaskResult``. The model/system prompt/tools/timeout are
    read from ``request.metadata`` / ``request.input`` and fall back to
    sensible defaults.
    """

    def __init__(
        self,
        cli_entry_point: str = "focus-agent",
        default_timeout_seconds: float = 300.0,
        graceful_shutdown_seconds: float = 5.0,
    ) -> None:
        self._runner = ProcessSubagentRunner(cli_entry_point=cli_entry_point)
        self._default_timeout = float(default_timeout_seconds)
        self._graceful = float(graceful_shutdown_seconds)

    async def run(
        self,
        request: Any,
        *,
        run_record: Any,
    ) -> Any:
        # Local imports to avoid a cycle between executor <-> process_runner.
        from .executor import SubagentTaskResult

        model = str(request.metadata.get("model") or request.input.get("model") or "default")
        system_prompt = str(
            request.metadata.get("system_prompt") or request.input.get("system_prompt") or ""
        )
        tools_allowed_raw = (
            request.metadata.get("tools_allowed") or request.input.get("tools_allowed") or ["*"]
        )
        if isinstance(tools_allowed_raw, str):
            tools_allowed = [tool.strip() for tool in tools_allowed_raw.split(",") if tool.strip()]
        else:
            try:
                tools_allowed = [str(tool) for tool in tools_allowed_raw]
            except TypeError:
                tools_allowed = ["*"]
        try:
            timeout = float(
                request.metadata.get("timeout_seconds")
                or request.input.get("timeout_seconds")
                or self._default_timeout
            )
        except (TypeError, ValueError):
            timeout = self._default_timeout

        config = ProcessSubagentConfig(
            model=model,
            system_prompt=system_prompt,
            tools_allowed=tools_allowed,
            timeout_seconds=timeout,
            graceful_shutdown_seconds=self._graceful,
        )
        thread_id = request.thread_id or getattr(run_record, "thread_id", "")
        result = await self._runner.run(
            config=config,
            task=request.instruction,
            thread_id=thread_id,
        )
        return SubagentTaskResult(
            content=result.output,
            metadata={
                "runner": "process",
                "success": result.success,
                "return_code": result.return_code,
                "duration_seconds": result.duration_seconds,
                "error": result.error,
            },
            artifact={
                "process_run": {
                    "success": result.success,
                    "return_code": result.return_code,
                    "duration_seconds": result.duration_seconds,
                    "error": result.error,
                    "token_usage": result.token_usage,
                    "cli_entry_point": self._runner._cli_entry_point,
                }
            },
        )
