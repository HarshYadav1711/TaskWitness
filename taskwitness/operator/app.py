"""TaskWitness operator FastAPI application."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from taskwitness.operator.runtime import OperatorError, OperatorRuntime

STATIC_DIR = Path(__file__).resolve().parent / "static"


class StartRunBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Optional[str] = None
    mode: str = Field(default="natural_language")


class ApprovalBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision: str


def create_app(runtime: OperatorRuntime | None = None) -> FastAPI:
    rt = runtime or OperatorRuntime()
    app = FastAPI(title="TaskWitness Operator", docs_url=None, redoc_url=None)
    app.state.runtime = rt

    if STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/operator", response_class=HTMLResponse)
    @app.get("/", response_class=HTMLResponse)
    def operator_page() -> HTMLResponse:
        html_path = STATIC_DIR / "operator.html"
        return HTMLResponse(html_path.read_text(encoding="utf-8"))

    @app.get("/api/config")
    def api_config() -> dict[str, Any]:
        return rt.config_snapshot()

    @app.get("/api/runs/active")
    def api_active() -> dict[str, Any]:
        snap = rt.current_active_snapshot()
        return {"run": snap}

    @app.post("/api/runs")
    def api_start(body: StartRunBody) -> dict[str, Any]:
        try:
            return rt.start_run(goal=body.goal, mode=body.mode)
        except OperatorError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.get("/api/runs/{run_id}")
    def api_get_run(run_id: str) -> dict[str, Any]:
        try:
            return rt.snapshot(run_id)
        except OperatorError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/pause")
    def api_pause(run_id: str) -> dict[str, Any]:
        try:
            return rt.pause(run_id)
        except OperatorError as exc:
            code = 404 if "not found" in str(exc).lower() else 400
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/resume")
    def api_resume(run_id: str) -> dict[str, Any]:
        try:
            return rt.resume(run_id)
        except OperatorError as exc:
            code = 404 if "not found" in str(exc).lower() else 400
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.post("/api/runs/{run_id}/approvals/{approval_id}")
    def api_approval(run_id: str, approval_id: str, body: ApprovalBody) -> dict[str, Any]:
        try:
            return rt.resolve_approval(run_id, approval_id, body.decision)
        except OperatorError as exc:
            code = 404 if "not found" in str(exc).lower() else 400
            raise HTTPException(status_code=code, detail=str(exc)) from exc

    @app.exception_handler(HTTPException)
    async def http_exc(_request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    return app
