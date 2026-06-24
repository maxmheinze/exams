r"""
Core exam-generation engine (web-facing refactor of generate_exams.py).

Public entry point: generate_exams(...) -> bytes (a .zip of exam PDFs).

Behavioural parity with the CLI, with these intentional changes:
  * -m (manual sorting headers) is always on.
  * -t/-p are gone (template comes from fields; pool is passed in).
  * Bonus question types: their drawn question is placed at the very end (before
    extra pages) and printed as "Bonus" instead of a number; the DataMatrix still
    carries the real running number so grading can locate the page.
  * Auxiliary assets (images, .txt R-output, etc.) are written into the compile
    directory under sanitized basenames; questions reference them by basename.
  * Each compile is hardened (see security.py) and the whole job runs in an
    ephemeral directory that is removed afterwards -> nothing is retained.
"""

import io
import os
import random
import shutil
import subprocess
import tempfile
import zipfile

from . import security
from .barcode import generate_barcode
from .template import (
    build_skeleton,
    labels,
    manual_header_code,
    QUESTION_BLOCK,
    EXTRA_PAGE_BLOCK,
)

ALLOWED_EXTRA_PAGES = {0, 2, 4, 6, 8}


class GenerationError(Exception):
    """Raised for bad input or a failed compile (message is user-safe)."""


def _detok(filename: str) -> str:
    return f"\\detokenize{{{filename}}}"


def _validate_pool(questions):
    if not isinstance(questions, list) or not questions:
        raise GenerationError("Question pool is empty.")
    for idx, q in enumerate(questions):
        for key in ("question_type", "within_type_id", "question_text"):
            if key not in q:
                raise GenerationError(f"Question {idx} is missing '{key}'.")
        if not (isinstance(q["question_type"], str) and q["question_type"].isdigit()
                and len(q["question_type"]) == 2):
            raise GenerationError(f"Question {idx}: question_type must be 2 digits.")
        if not (isinstance(q["within_type_id"], str) and q["within_type_id"].isdigit()
                and len(q["within_type_id"]) == 2):
            raise GenerationError(f"Question {idx}: within_type_id must be 2 digits.")
        try:
            pts = int(q["points"])
        except (KeyError, TypeError, ValueError):
            raise GenerationError(f"Question {idx}: points must be an integer.")
        if not (0 < pts < 100):
            raise GenerationError(f"Question {idx}: points must be 1-99.")


def _select_for_exam(question_types, q_types, fixed, base_questions, bonus_types):
    """Return the ordered question list for one exam (non-bonus first, bonus last)."""
    if fixed:
        drawn = list(base_questions)
    else:
        drawn = [random.choice(question_types[qt]) for qt in q_types]
    non_bonus = [q for q in drawn if q["question_type"] not in bonus_types]
    bonus = [q for q in drawn if q["question_type"] in bonus_types]
    random.shuffle(non_bonus)
    random.shuffle(bonus)
    return non_bonus + bonus


def _render_questions(questions_for_exam, exam_code, bonus_types, job_dir, made_files, lab):
    out = ""
    for i, q in enumerate(questions_for_exam, start=1):
        qnum2 = f"{i:02d}"
        pts = f"{int(q['points']):02d}"
        dp = pts.lstrip("0") or "0"
        qtype, within = q["question_type"], q["within_type_id"]
        base = f"{exam_code}{qnum2}{qtype}{within}{pts}"

        f1 = f"bc_{exam_code}_q{qnum2}_1.png"
        f2 = f"bc_{exam_code}_q{qnum2}_2.png"
        generate_barcode(base + "1", os.path.join(job_dir, f1)); made_files.append(f1)
        generate_barcode(base + "2", os.path.join(job_dir, f2)); made_files.append(f2)

        is_bonus = qtype in bonus_types
        printed = lab["bonus"] if is_bonus else str(i)
        h1 = "\\sethdr{" + manual_header_code(exam_code, qtype, within, "01") + "}"
        h2 = "\\sethdr{" + manual_header_code(exam_code, qtype, within, "02") + "}"

        block = QUESTION_BLOCK
        block = block.replace("@@HDR1@@", h1, 1).replace("@@HDR2@@", h2, 1)
        block = block.replace("@@CODE@@", _detok(f1), 1).replace("@@CODE@@", _detok(f2), 1)
        block = block.replace("@@EXAM2@@", exam_code)
        block = block.replace("@@EXAMLBL@@", lab["exam"]).replace("@@QLBL@@", lab["question"])
        ptslbl = lab["point"] if int(q["points"]) == 1 else lab["points"]
        block = block.replace("@@PTSLBL@@", ptslbl)
        block = block.replace("@@QNUM@@", printed)
        block = block.replace("@@PTS@@", dp)
        block = block.replace("@@QTEXT@@", q["question_text"])  # injected last
        out += block
    return out


def _render_extra_pages(num_extra, exam_code, job_dir, made_files, lab):
    out = ""
    for i in range(1, num_extra + 1):
        code = f"{exam_code}99990000{i}"
        fname = f"bc_{exam_code}_extra{i}.png"
        generate_barcode(code, os.path.join(job_dir, fname)); made_files.append(fname)
        hx = "\\sethdr{" + manual_header_code(exam_code, "99", "00", f"{i:02d}") + "}"
        block = EXTRA_PAGE_BLOCK
        block = block.replace("@@HDRX@@", hx, 1)
        block = block.replace("@@CODE@@", _detok(fname), 1)
        block = block.replace("@@EXAM2@@", exam_code)
        block = block.replace("@@EXAMLBL@@", lab["exam"]).replace("@@ADDPAPER@@", lab["addpaper"])
        out += block
    return out


def _run(cmd, job_dir, jobname):
    try:
        return subprocess.run(
            cmd,
            cwd=job_dir,
            env=security.compile_env(job_dir),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=security.WALL_TIMEOUT_SECONDS,
            text=True, encoding="latin-1", errors="replace",
            preexec_fn=security.apply_rlimits,
        )
    except subprocess.TimeoutExpired:
        raise GenerationError(f"{jobname}: compilation timed out.")


def _compile(job_dir, tex_filename, jobname):
    """Run the hardened compile under the global one-at-a-time semaphore.

    If the command is bwrap-wrapped and bwrap's *sandbox setup* fails (as opposed
    to a LaTeX error), degrade once to the direct command, which is still run with
    shell-escape off, paranoid file access, and resource limits.
    """
    with security.COMPILE_SEMAPHORE:
        cmd = security.latexmk_cmd(tex_filename, jobname, job_dir)
        result = _run(cmd, job_dir, jobname)
        if (result.returncode != 0 and cmd and cmd[0] == "bwrap"
                and "bwrap:" in (result.stderr or "")):
            result = _run(security._base_latexmk(tex_filename, jobname), job_dir, jobname)
    return result


def generate_exams(
    questions,
    *,
    fields=None,
    n=1,
    extra_pages=0,
    q_types=None,
    bonus_types=None,
    demo=False,
    fixed=False,
    assets=None,
    seed=None,
    language="en",
    work_root="/home/exams/work",
):
    """Generate exams and return a zip (bytes) of the PDFs. Cleans up after itself."""
    _validate_pool(questions)
    if not isinstance(n, int) or not (1 <= n <= 200):
        raise GenerationError("Number of exams must be between 1 and 200.")
    if extra_pages not in ALLOWED_EXTRA_PAGES:
        raise GenerationError("Extra pages must be one of 0, 2, 4, 6, 8.")
    bonus_types = set(bonus_types or [])
    if seed is not None:
        random.seed(seed)

    question_types = {}
    for q in questions:
        question_types.setdefault(q["question_type"], []).append(q)

    if demo:
        selected_global = sorted(questions, key=lambda q: (q["question_type"], q["within_type_id"]))
    else:
        if q_types is None:
            q_types = sorted(question_types.keys())
        if len(set(q_types)) != len(q_types):
            raise GenerationError("Duplicate question types selected.")
        for qt in q_types:
            if qt not in question_types:
                raise GenerationError(f"Question type {qt} is not in the pool.")
        if not q_types:
            raise GenerationError("Select at least one question type.")
        base_questions = ([random.choice(question_types[qt]) for qt in q_types]
                          if fixed else None)

    # Sanitize asset names up front (fail fast before any compile).
    safe_assets = {}
    for name, content in (assets or {}).items():
        safe_assets[security.sanitize_asset_name(name)] = content

    lab = labels(language)
    skeleton = build_skeleton(fields or {}, language)

    os.makedirs(work_root, exist_ok=True)
    security.sweep_stale(work_root)
    job_dir = tempfile.mkdtemp(prefix="job_", dir=work_root)
    pdfs = []
    try:
        # Assets are identical across exams; write them once.
        for name, content in safe_assets.items():
            with open(os.path.join(job_dir, name), "wb") as fh:
                fh.write(content)

        for exam_num in range(1, n + 1):
            exam_code = f"{exam_num:02d}"
            made = []

            h1 = f"bc_{exam_code}_header1.png"
            h2 = f"bc_{exam_code}_header2.png"
            generate_barcode(f"{exam_code}000000001", os.path.join(job_dir, h1)); made.append(h1)
            generate_barcode(f"{exam_code}000000002", os.path.join(job_dir, h2)); made.append(h2)

            if demo:
                questions_for_exam = selected_global
            else:
                questions_for_exam = _select_for_exam(
                    question_types, q_types, fixed, base_questions, bonus_types)

            q_content = _render_questions(questions_for_exam, exam_code,
                                          set() if demo else bonus_types, job_dir, made, lab)
            e_content = _render_extra_pages(extra_pages, exam_code, job_dir, made, lab)

            doc = skeleton
            doc = doc.replace("@@CODE@@", _detok(h1), 1).replace("@@CODE@@", _detok(h2), 1)
            doc = doc.replace("@@EXAM2@@", exam_code)
            doc = doc.replace("@@EXAMNO@@", exam_code)
            doc = doc.replace("@@QUESTIONS@@", q_content)
            doc = doc.replace("@@EXTRAPAGES@@", e_content)

            jobname = f"exam_{exam_code}"
            tex_filename = f"{jobname}.tex"
            with open(os.path.join(job_dir, tex_filename), "w", encoding="utf-8") as fh:
                fh.write(doc)

            result = _compile(job_dir, tex_filename, jobname)
            pdf_path = os.path.join(job_dir, f"{jobname}.pdf")
            if result.returncode != 0 or not os.path.exists(pdf_path):
                tail = (result.stdout or "")[-1500:]
                try:
                    with open(os.path.join(job_dir, f"{jobname}.log"),
                              "r", encoding="latin-1", errors="replace") as lf:
                        log_text = lf.read()
                except OSError:
                    log_text = result.stdout or ""
                err = GenerationError(
                    f"LaTeX failed for {jobname}. Check the question/template "
                    f"LaTeX. Compiler tail:\n{tail}")
                err.tex = doc          # the exact source we tried to compile
                err.log = log_text     # the pdflatex log
                err.jobname = jobname
                raise err
            pdfs.append((f"{jobname}.pdf", open(pdf_path, "rb").read()))

            # Drop this exam's intermediates to keep the job dir small.
            subprocess.run(["latexmk", "-c", tex_filename], cwd=job_dir,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            for fn in made + [tex_filename, f"{jobname}.pdf",
                              f"{jobname}.aux", f"{jobname}.log", f"{jobname}.fls"]:
                p = os.path.join(job_dir, fn)
                if os.path.exists(p):
                    os.remove(p)

        if not pdfs:
            raise GenerationError("No exams were generated.")

        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in pdfs:
                zf.writestr(name, data)
        return buf.getvalue()
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)
