import asyncio
import hmac
import os
import time
from typing import Any, Literal

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

MPT_BASE_URL = os.getenv("MPT_BASE_URL", "http://moneyprinter-api:8080").rstrip("/")
BRIDGE_TOKEN = os.getenv("BRIDGE_TOKEN", "").strip()
DEFAULT_TIMEOUT = float(os.getenv("MPT_HTTP_TIMEOUT", "60"))

app = FastAPI(
    title="MoneyPrinterTurbo Bridge",
    version="1.0.0",
    description=(
        "Small authenticated adapter in front of MoneyPrinterTurbo's native API. "
        "It accepts a stable /request envelope and can optionally wait for task completion."
    ),
)


class BridgeRequest(BaseModel):
    action: Literal["video", "subtitle", "audio", "status", "tasks", "raw"] = "video"
    payload: dict[str, Any] = Field(default_factory=dict)
    task_id: str | None = None
    wait: bool = False
    wait_timeout_seconds: int = Field(default=900, ge=1, le=7200)
    poll_interval_seconds: float = Field(default=2.0, ge=0.25, le=30.0)
    method: Literal["GET", "POST", "DELETE"] = "GET"
    path: str | None = None


class BridgeResponse(BaseModel):
    ok: bool
    action: str
    task_id: str | None = None
    result: Any = None


def require_token(
    authorization: str | None = Header(default=None),
    x_bridge_token: str | None = Header(default=None),
) -> None:
    if not BRIDGE_TOKEN:
        return

    candidate = x_bridge_token or ""
    if authorization and authorization.lower().startswith("bearer "):
        candidate = authorization[7:].strip()

    if not candidate or not hmac.compare_digest(candidate, BRIDGE_TOKEN):
        raise HTTPException(status_code=401, detail="invalid bridge token")


async def mpt_call(method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
    if not path.startswith("/api/v1/"):
        raise HTTPException(status_code=400, detail="bridge only permits /api/v1/* paths")

    url = f"{MPT_BASE_URL}{path}"
    try:
        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.request(method, url, json=payload if method != "GET" else None)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=502, detail=f"MoneyPrinterTurbo unavailable: {exc}") from exc

    content_type = response.headers.get("content-type", "")
    try:
        data: Any = response.json() if "json" in content_type else response.text
    except ValueError:
        data = response.text

    if response.is_error:
        raise HTTPException(status_code=response.status_code, detail=data)
    return data


def extract_task_id(result: Any) -> str | None:
    if isinstance(result, dict):
        data = result.get("data")
        if isinstance(data, dict):
            task_id = data.get("task_id")
            if isinstance(task_id, str) and task_id:
                return task_id
    return None


async def wait_for_task(task_id: str, timeout_seconds: int, interval_seconds: float) -> Any:
    deadline = time.monotonic() + timeout_seconds
    last: Any = None
    while time.monotonic() < deadline:
        last = await mpt_call("GET", f"/api/v1/tasks/{task_id}")
        task = last.get("data", {}) if isinstance(last, dict) else {}
        state = task.get("state") if isinstance(task, dict) else None
        # MoneyPrinterTurbo constants: complete=1, failed=-1, processing=4.
        if state in (1, -1):
            return last
        await asyncio.sleep(interval_seconds)

    raise HTTPException(
        status_code=504,
        detail={"message": "timed out waiting for task", "task_id": task_id, "last": last},
    )


@app.get("/health")
async def health(_: None = Depends(require_token)) -> dict[str, Any]:
    backend_ok = True
    backend_error: str | None = None
    try:
        await mpt_call("GET", "/api/v1/tasks")
    except HTTPException as exc:
        backend_ok = False
        backend_error = str(exc.detail)
    return {
        "ok": backend_ok,
        "bridge": "moneyprinterturbo",
        "backend": MPT_BASE_URL,
        "backend_error": backend_error,
    }


@app.post("/request", response_model=BridgeResponse)
async def request_bridge(body: BridgeRequest, _: None = Depends(require_token)) -> BridgeResponse:
    if body.action == "status":
        if not body.task_id:
            raise HTTPException(status_code=400, detail="task_id is required for status")
        result = await mpt_call("GET", f"/api/v1/tasks/{body.task_id}")
        return BridgeResponse(ok=True, action=body.action, task_id=body.task_id, result=result)

    if body.action == "tasks":
        result = await mpt_call("GET", "/api/v1/tasks")
        return BridgeResponse(ok=True, action=body.action, result=result)

    if body.action == "raw":
        if not body.path:
            raise HTTPException(status_code=400, detail="path is required for raw action")
        result = await mpt_call(body.method, body.path, body.payload or None)
        return BridgeResponse(ok=True, action=body.action, task_id=extract_task_id(result), result=result)

    payload = dict(body.payload)
    # Convenience input: {"prompt": "..."} becomes MoneyPrinterTurbo video_subject.
    if body.action == "video" and "video_subject" not in payload and "prompt" in payload:
        payload["video_subject"] = payload.pop("prompt")

    path_by_action = {
        "video": "/api/v1/videos",
        "subtitle": "/api/v1/subtitle",
        "audio": "/api/v1/audio",
    }
    result = await mpt_call("POST", path_by_action[body.action], payload)
    task_id = extract_task_id(result)

    if body.wait and task_id:
        result = await wait_for_task(task_id, body.wait_timeout_seconds, body.poll_interval_seconds)

    return BridgeResponse(ok=True, action=body.action, task_id=task_id, result=result)
