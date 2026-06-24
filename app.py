r"""
FastAPI layer for exams.maxheinze.eu.

Surface is intentionally tiny (smaller attack surface, fully stateless):
  GET  /api/health             -> liveness probe for systemd/nginx/curl
  POST /api/generate           -> multipart: a JSON `spec` field + 0..N `assets`
                                  files; returns exams.zip (application/zip)

Pool editing, the "save JSON" download, and template/option selection all happen
client-side; the server is only invoked to compile, and retains nothing (the
engine works in an ephemeral dir wiped after each request).

Run: uvicorn app:app --host 127.0.0.1 --port 8003
"""

import asyncio
import json
import os
import shutil
import tempfile
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, Response, StreamingResponse
from pydantic import BaseModel, Field, ValidationError
from starlette.background import BackgroundTask

from examgen import generate_exams, GenerationError
from examgen import security
from examgen.security import sweep_stale, bwrap_usable
from examgen.grading import read_and_sort, GradingError
from examgen.report import build_report, ReportError

WORK_ROOT = os.environ.get("EXAMS_WORK_ROOT", "/home/exams/work")
# matplotlib needs a writable cache dir; HOME is read-only under the systemd unit.
try:
    _mpl = os.path.join(WORK_ROOT, ".mplcache")
    os.makedirs(_mpl, exist_ok=True)
    os.environ.setdefault("MPLCONFIGDIR", _mpl)
except OSError:
    pass
MAX_SPEC_BYTES = 5 * 1024 * 1024            # 5 MiB of JSON spec
MAX_ASSETS = 50
MAX_TOTAL_ASSET_BYTES = 25 * 1024 * 1024    # 25 MiB of uploaded assets
MAX_PDF_BYTES = 250 * 1024 * 1024           # 250 MiB of scanned PDFs
MAX_PAGES = 2500
MAX_CSV_BYTES = 10 * 1024 * 1024            # 10 MiB of points CSV
_GRADE_FILES = {
    "sorted.pdf": "application/pdf",
    "pagelist.csv": "text/csv",
    "extrasheets.pdf": "application/pdf",
    "nocode.pdf": "application/pdf",
}


def _safe_job(job: str) -> bool:
    return job.startswith("job_") and "/" not in job and ".." not in job


@asynccontextmanager
async def lifespan(app):
    # On boot, clear any job dirs orphaned by a previous crash/restart.
    sweep_stale(WORK_ROOT)
    yield


app = FastAPI(title="exams.maxheinze.eu", docs_url=None, redoc_url=None, lifespan=lifespan)


class Question(BaseModel):
    question_type: str
    within_type_id: str
    points: int
    question_text: str


class TemplateFields(BaseModel):
    exam_title: Optional[str] = None
    subject: Optional[str] = None
    course_no: Optional[str] = None
    date: Optional[str] = None
    rules_latex: Optional[str] = None


class GenerateSpec(BaseModel):
    questions: List[Question]
    fields: TemplateFields = Field(default_factory=TemplateFields)
    n: int = 1
    extra_pages: int = 0
    q_types: Optional[List[str]] = None
    bonus_types: List[str] = Field(default_factory=list)
    demo: bool = False
    fixed: bool = False
    language: str = "en"


@app.get("/api/health")
async def health():
    return {"status": "ok", "sandbox": "bwrap" if bwrap_usable() else "fallback"}


@app.post("/api/generate")
async def generate(
    spec: str = Form(...),
    assets: List[UploadFile] = File(default=[]),
):
    if len(spec) > MAX_SPEC_BYTES:
        raise HTTPException(status_code=413, detail="Spec payload too large.")
    try:
        parsed = GenerateSpec.model_validate(json.loads(spec))
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Spec is not valid JSON.")
    except ValidationError as e:
        raise HTTPException(status_code=400, detail=f"Invalid spec: {e.errors()}")

    if len(assets) > MAX_ASSETS:
        raise HTTPException(status_code=413, detail="Too many asset files.")
    asset_map = {}
    total = 0
    for up in assets:
        content = await up.read()
        total += len(content)
        if total > MAX_TOTAL_ASSET_BYTES:
            raise HTTPException(status_code=413, detail="Assets exceed total size limit.")
        asset_map[up.filename or ""] = content

    try:
        zip_bytes = await run_in_threadpool(
            generate_exams,
            [q.model_dump() for q in parsed.questions],
            fields=parsed.fields.model_dump(),
            n=parsed.n,
            extra_pages=parsed.extra_pages,
            q_types=parsed.q_types,
            bonus_types=set(parsed.bonus_types),
            demo=parsed.demo,
            fixed=parsed.fixed,
            assets=asset_map,
            language=parsed.language,
            work_root=WORK_ROOT,
        )
    except (GenerationError, ValueError) as e:
        # user-fixable problems (bad LaTeX, bad asset name, bad options)
        tex = getattr(e, "tex", None)
        if tex is not None:
            raise HTTPException(status_code=422, detail={
                "message": str(e),
                "tex": tex,
                "log": getattr(e, "log", "") or "",
                "jobname": getattr(e, "jobname", "exam"),
            })
        raise HTTPException(status_code=400, detail=str(e))

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="exams.zip"'},
    )

# ---------------------------------------------------------------------------
# Grading step 1 — read & sort scanned exams (server-side, memory-light).
# Steps 2 (grade) and 3 (split) run in the browser; the server only does this
# decode/sort and (later) the report compile.
# ---------------------------------------------------------------------------

@app.post("/api/grade/read")
async def grade_read(pdfs: List[UploadFile] = File(...)):
    """Stream newline-delimited JSON progress while decoding/sorting the scan.

    Emits {"progress":k,"total":N} per page, then a final
    {"done":true,"job":<id>,"summary":{...}} (or {"error":...}). Result files
    are then fetched from /api/grade/result/<job>/<name>.
    """
    os.makedirs(WORK_ROOT, exist_ok=True)
    sweep_stale(WORK_ROOT)
    job_dir = tempfile.mkdtemp(prefix="job_", dir=WORK_ROOT)
    job_id = os.path.basename(job_dir)

    paths, total = [], 0
    try:
        for up in pdfs:
            dest = os.path.join(job_dir, f"in_{len(paths):03d}.pdf")
            with open(dest, "wb") as fh:
                while True:
                    chunk = await up.read(1024 * 1024)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > MAX_PDF_BYTES:
                        shutil.rmtree(job_dir, ignore_errors=True)
                        raise HTTPException(status_code=413,
                                            detail="Scanned PDFs exceed the size limit.")
                    fh.write(chunk)
            paths.append(dest)
    except HTTPException:
        raise
    if not paths:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=400, detail="No PDF uploaded.")

    async def streamer():
        queue: asyncio.Queue = asyncio.Queue()
        loop = asyncio.get_running_loop()
        result = {}

        def progress(done, tot):
            loop.call_soon_threadsafe(queue.put_nowait, {"progress": done, "total": tot})

        def work():
            with security.HEAVY_SEMAPHORE:
                return read_and_sort(paths, job_dir, progress=progress, max_pages=MAX_PAGES)

        async def run():
            try:
                result["summary"] = await run_in_threadpool(work)
            except GradingError as e:
                result["error"] = str(e)
            except Exception as e:  # unexpected; keep message generic
                result["error"] = f"Reading failed: {e}"
            loop.call_soon_threadsafe(queue.put_nowait, None)

        asyncio.create_task(run())
        while True:
            item = await queue.get()
            if item is None:
                break
            yield json.dumps(item) + "\n"
        if "error" in result:
            shutil.rmtree(job_dir, ignore_errors=True)
            yield json.dumps({"error": result["error"]}) + "\n"
        else:
            yield json.dumps({"done": True, "job": job_id, "summary": result["summary"]}) + "\n"

    return StreamingResponse(streamer(), media_type="application/x-ndjson")


@app.get("/api/grade/result/{job}/{name}")
async def grade_result(job: str, name: str):
    if name not in _GRADE_FILES or not _safe_job(job):
        raise HTTPException(status_code=404, detail="Not found.")
    path = os.path.join(WORK_ROOT, job, name)
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path, media_type=_GRADE_FILES[name], filename=name)


@app.post("/api/grade/cleanup/{job}")
async def grade_cleanup(job: str):
    if _safe_job(job):
        shutil.rmtree(os.path.join(WORK_ROOT, job), ignore_errors=True)
    return {"ok": True}


@app.post("/api/grade/report")
async def grade_report(points: UploadFile = File(...)):
    """Compile the results report PDF from points_by_question.csv (small input)."""
    os.makedirs(WORK_ROOT, exist_ok=True)
    sweep_stale(WORK_ROOT)
    job_dir = tempfile.mkdtemp(prefix="job_", dir=WORK_ROOT)
    dest = os.path.join(job_dir, "points_by_question.csv")
    total = 0
    with open(dest, "wb") as fh:
        while True:
            chunk = await points.read(256 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_CSV_BYTES:
                shutil.rmtree(job_dir, ignore_errors=True)
                raise HTTPException(status_code=413, detail="CSV exceeds the size limit.")
            fh.write(chunk)

    def work():
        with security.HEAVY_SEMAPHORE:
            return build_report(dest, job_dir)

    try:
        pdf_path = await run_in_threadpool(work)
    except ReportError as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        tex = getattr(e, "tex", None)
        if tex is not None:
            raise HTTPException(status_code=422, detail={
                "message": str(e).splitlines()[0],
                "tex": tex,
                "log": getattr(e, "log", "") or "",
                "jobname": "report",
            })
        raise HTTPException(status_code=400, detail=str(e).splitlines()[0])
    except Exception:
        shutil.rmtree(job_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail="Report generation failed.")

    return FileResponse(
        pdf_path, media_type="application/pdf",
        filename="exam_results_report.pdf",
        background=BackgroundTask(shutil.rmtree, job_dir, True),
    )
