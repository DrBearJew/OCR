from __future__ import annotations

import json
import os
import ipaddress
import shlex
import socket
import subprocess
from urllib.parse import urlparse
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Document, HookKind, HookStage, IngestionJob, ProcessingHook
from app.config import get_settings
from app.services.events import record_event


def execute_hooks(
    db: Session,
    stage: HookStage,
    *,
    document: Document | None = None,
    ingestion_job: IngestionJob | None = None,
    context: dict[str, Any] | None = None,
) -> None:
    hooks = db.scalars(
        select(ProcessingHook)
        .where(ProcessingHook.stage == stage)
        .where(ProcessingHook.enabled.is_(True))
        .order_by(ProcessingHook.created_at.asc())
    ).all()
    for hook in hooks:
        try:
            result = execute_hook(hook, document=document, ingestion_job=ingestion_job, context=context or {})
            if document is not None:
                record_event(db, document, f"{stage.value}_hook_done", f"Hook {hook.name} completed", metadata=result)
        except Exception as exc:  # noqa: BLE001
            if document is not None:
                record_event(db, document, f"{stage.value}_hook_failed", f"Hook {hook.name} failed: {exc}", metadata={"blocking": hook.blocking})
            if hook.blocking:
                raise


def execute_hook(
    hook: ProcessingHook,
    *,
    document: Document | None = None,
    ingestion_job: IngestionJob | None = None,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    payload = {
        "hook": hook.name,
        "stage": hook.stage.value,
        "document_id": str(document.id) if document else None,
        "record_id": str(document.record_id) if document else None,
        "filename": document.original_filename if document else None,
        "ingestion_job_id": str(ingestion_job.id) if ingestion_job else None,
        "source_path": ingestion_job.discovered_path if ingestion_job else None,
        "context": context or {},
    }
    if hook.hook_kind == HookKind.webhook:
        if not hook.webhook_url:
            raise ValueError("Webhook hook missing webhook_url")
        _validate_webhook_url(hook.webhook_url, settings.hook_webhook_allowed_hosts_set)
        response = httpx.post(hook.webhook_url, json=payload, timeout=hook.timeout_seconds)
        response.raise_for_status()
        return {"kind": "webhook", "status_code": response.status_code}
    if not settings.command_hooks_enabled:
        raise ValueError("Command hooks are disabled; set COMMAND_HOOKS_ENABLED=true to allow local command execution")
    if not hook.command:
        raise ValueError("Command hook missing command")
    env = {**os.environ, **{str(k): str(v) for k, v in (hook.env_json or {}).items()}}
    env["DOKOCR_HOOK_PAYLOAD"] = json.dumps(payload)
    argv = _command_argv(hook.command, settings.command_hooks_allowed_commands_set)
    completed = subprocess.run(
        argv,
        shell=False,
        capture_output=True,
        text=True,
        timeout=hook.timeout_seconds,
        env=env,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError((completed.stderr or completed.stdout or f"exit {completed.returncode}").strip())
    return {"kind": "command", "returncode": completed.returncode, "stdout": completed.stdout[-500:]}


def _command_argv(command: str, allowed_commands: set[str]) -> list[str]:
    if not allowed_commands:
        raise ValueError("Command hooks require COMMAND_HOOKS_ALLOWED_COMMANDS to be non-empty")
    if any(token in command for token in [";", "&", "|", "`", "$(", ">", "<", "\n", "\r"]):
        raise ValueError("Command hook contains shell metacharacters")
    argv = shlex.split(command, posix=True)
    if not argv:
        raise ValueError("Command hook missing command")
    executable = os.path.basename(argv[0]).lower()
    if executable.endswith(".exe"):
        executable = executable[:-4]
    if executable not in allowed_commands:
        raise ValueError(f"Command hook executable is not allowlisted: {executable}")
    if executable.startswith("python") and any(arg in {"-c", "-m"} for arg in argv[1:]):
        raise ValueError("Python command hooks may not use -c or -m")
    return argv


def _validate_webhook_url(url: str, allowed_hosts: set[str]) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Webhook URL must use http or https")
    host = (parsed.hostname or "").lower()
    if not allowed_hosts:
        raise ValueError("Webhook hooks require HOOK_WEBHOOK_ALLOWED_HOSTS")
    if host not in allowed_hosts:
        raise ValueError(f"Webhook hook host is not allowed: {host}")
    try:
        infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError(f"Webhook hook host could not be resolved: {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified:
            raise ValueError(f"Webhook hook resolved to a blocked address: {ip}")
