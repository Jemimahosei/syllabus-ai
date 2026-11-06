"""SyllabusAI service — FastAPI.

Endpoints:
  GET  /api/health         liveness + which parser engine is active
  GET  /api/sample         the fictional sample syllabus text
  POST /api/analyze        {text} -> parsed syllabus + findings + verdict
  POST /api/analyze-file   multipart file (.pdf/.txt/.md) -> same
  POST /api/canvas         {token, course, base_url?} -> fetch from Canvas
                           (token used for this one fetch only, never stored)
                           -> same analysis

In production the built frontend is served from ./frontend_dist at /.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app import canvas_client, parser as syllabus_parser, rules

BASE_DIR = Path(__file__).resolve().parent.parent
SAMPLE_PATH = BASE_DIR / "app" / "sample_syllabus.txt"
FRONTEND_DIST = BASE_DIR / "frontend_dist"

app = FastAPI(title="SyllabusAI")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_parser_engine = "unknown"


@app.on_event("startup")
def _startup():
    global _parser_engine
    binary = syllabus_parser._binary_path()
    _parser_engine = "cpp" if binary else "python-fallback"
    print(f"[syllabus-ai] parser engine: {_parser_engine}"
          + (f" ({binary})" if binary else ""))


def _analyze(text: str, source: str) -> dict:
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="No syllabus text provided.")
    if len(text) > 200_000:
        raise HTTPException(status_code=400,
                            detail="Syllabus text is too long (200,000 character limit).")
    parsed, engine = syllabus_parser.parse(text)
    findings = rules.run_rules(parsed)
    return {
        "source": source,
        "parser_engine": engine,
        "course": parsed.get("course", {}),
        "ai_policy": parsed.get("ai_policy", {}),
        "grading": parsed.get("grading", {}),
        "slip_days": parsed.get("slip_days", {}),
        "late_policy": parsed.get("late_policy", {}),
        "deadlines": parsed.get("deadlines", []),
        "materials": parsed.get("materials", []),
        "findings": findings,
        "verdict": rules.verdict(findings),
    }


@app.get("/api/health")
def health():
    return {"ok": True, "parser_engine": _parser_engine}


@app.get("/api/sample")
def sample():
    return {"text": SAMPLE_PATH.read_text(encoding="utf-8")}


class AnalyzeRequest(BaseModel):
    text: str


@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    return _analyze(req.text, "pasted text")


@app.post("/api/analyze-file")
async def analyze_file(file: UploadFile = File(...)):
    name = (file.filename or "").lower()
    data = await file.read()
    if len(data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File is too large (5 MB limit).")
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(data))
            parts = [(page.extract_text() or "") for page in reader.pages]
            text = "\n".join(parts)
        elif name.endswith((".txt", ".md", ".markdown")):
            text = data.decode("utf-8", errors="replace")
        else:
            raise HTTPException(
                status_code=400,
                detail="Unsupported file type. Upload a .pdf, .txt, or .md file.")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400,
                            detail=f"Could not read that file: {exc}") from exc
    if not text.strip():
        raise HTTPException(status_code=400,
                            detail="No text could be read from that file.")
    return _analyze(text, f"uploaded file ({file.filename})")


class CanvasRequest(BaseModel):
    token: str
    course: str
    base_url: str | None = None


@app.post("/api/canvas")
async def analyze_canvas(req: CanvasRequest):
    try:
        fetched = await canvas_client.fetch_syllabus(
            req.token, req.course, req.base_url or canvas_client.DEFAULT_BASE_URL)
    except canvas_client.CanvasError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    result = _analyze(fetched["text"], "Canvas")
    result["course"]["name_from_canvas"] = fetched["course_name"]
    return result


# Serve the built frontend (single-service deploy). In local dev the Vite
# dev server proxies /api to this service instead.
if FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def serve_frontend(full_path: str):
        if full_path.startswith("api/"):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        candidate = FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(FRONTEND_DIST / "index.html")
