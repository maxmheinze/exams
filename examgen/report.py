r"""
Exam results report — a Python port of exam_results_report.Rmd.

Reproduces the same sections (individual wide table; overall total-points stats
with histogram + density; per-question-type stats + histogram; per type-variant
stats + histogram) using matplotlib for the figures and the existing hardened
LaTeX toolchain (examgen.security) for the PDF — so no R / tidyverse install.

Input:  points_by_question.csv (the gradeable rows, with `points` filled).
Output: report.pdf in the job dir.
"""

import csv
import os
import subprocess

from . import security


class ReportError(Exception):
    pass


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return 0.0


def _fmt(v):
    import math
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "--"
    return f"{round(float(v), 2):g}"


def _esc(s):
    s = str(s)
    for a, b in (("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"),
                 ("$", r"\$"), ("#", r"\#"), ("_", r"\_"), ("{", r"\{"),
                 ("}", r"\}"), ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")):
        s = s.replace(a, b)
    return s


def _stats(values):
    import numpy as np
    a = np.asarray(values, dtype=float)
    n = a.size
    return {
        "N": n,
        "Mean": float(a.mean()) if n else float("nan"),
        "SD": float(a.std(ddof=1)) if n > 1 else float("nan"),
        "Median": float(np.median(a)) if n else float("nan"),
        "Min": float(a.min()) if n else float("nan"),
        "Max": float(a.max()) if n else float("nan"),
        "Q1": float(np.percentile(a, 25)) if n else float("nan"),
        "Q3": float(np.percentile(a, 75)) if n else float("nan"),
    }


def _stats_table(st):
    rows = "\n".join(
        rf"{k} & {_fmt(st[k])} \\" for k in
        ("N", "Mean", "SD", "Median", "Min", "Max", "Q1", "Q3"))
    return (r"\begin{tabular}{lr}\toprule Statistic & Value \\\midrule"
            + "\n" + rows + "\n" + r"\bottomrule\end{tabular}")


def _hist(values, title, path):
    import numpy as np
    import matplotlib.pyplot as plt
    a = np.asarray(values, float)
    hi = a.max() if a.size else 1.0
    edges = np.arange(-0.25, hi + 0.5, 0.5)
    if edges.size < 2:
        edges = np.array([-0.25, 0.25])
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.hist(a, bins=edges, color="#4682b4", edgecolor="black", alpha=0.75)
    ax.set_xlim(edges[0], edges[-1])
    ax.set_title(title, fontweight="bold")
    ax.set_xlabel("Points"); ax.set_ylabel("Frequency")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def _density(values, title, path):
    import numpy as np
    import matplotlib.pyplot as plt
    a = np.asarray(values, float)
    n = a.size
    sd = a.std(ddof=1) if n > 1 else 0.0
    if n < 2 or sd <= 0:
        return False
    h = 1.06 * sd * n ** (-0.2)             # Silverman's rule of thumb
    grid = np.linspace(0, a.max() + 3 * h, 256)
    dens = np.zeros_like(grid)
    for x in a:
        dens += np.exp(-0.5 * ((grid - x) / h) ** 2)
    dens /= (n * h * np.sqrt(2 * np.pi))
    fig, ax = plt.subplots(figsize=(7.2, 4.0))
    ax.fill_between(grid, dens, color="#4682b4", alpha=0.5)
    ax.plot(grid, dens, color="black", linewidth=1)
    ax.set_xlim(left=0)
    ax.set_title(title, fontweight="bold")
    ax.set_xlabel("Total Points"); ax.set_ylabel("Density")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)
    return True


def _wide_table(exams, types, by_exam_type, totals):
    # Split into chunks of <=4 types so the table never overflows the page width
    # (Exam + 4*(Var,Pts) + Total = 10 columns, matching the original report).
    chunk = 4
    parts = []
    groups = [types[i:i + chunk] for i in range(0, len(types), chunk)] or [[]]
    for gi, group in enumerate(groups):
        last = gi == len(groups) - 1
        ncol = 1 + 2 * len(group) + (1 if last else 0)
        colspec = "l" + "rr" * len(group) + ("r" if last else "")
        head = [r"\textbf{Exam}"]
        for t in group:
            head += [rf"\textbf{{Q{_esc(t)} Var}}", rf"\textbf{{Q{_esc(t)} Pts}}"]
        if last:
            head.append(r"\textbf{Total}")
        lines = [r"\begin{center}\footnotesize",
                 r"\rowcolors{2}{gray!12}{white}",
                 rf"\begin{{longtable}}{{{colspec}}}\toprule",
                 " & ".join(head) + r" \\\midrule\endhead"]
        for e in exams:
            cells = [rf"\textbf{{{_esc(e)}}}"]
            for t in group:
                var, pts = by_exam_type.get((e, t), ("", None))
                cells += [_esc(var), "" if pts is None else _fmt(pts)]
            if last:
                cells.append(rf"\textbf{{{_fmt(totals.get(e, 0.0))}}}")
            lines.append(" & ".join(cells) + r" \\")
        lines += [r"\bottomrule\end{longtable}\end{center}"]
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def build_report(points_csv, job_dir):
    """Build report.pdf in job_dir from points_by_question.csv; return its path."""
    import matplotlib
    matplotlib.use("Agg")

    with open(points_csv, newline="") as fh:
        rows = [r for r in csv.DictReader(fh)]
    rows = [r for r in rows
            if (r.get("question_type") or "") not in ("00", "99", "N/A", "")]
    if not rows:
        raise ReportError("No graded questions found in the CSV.")

    exams = sorted({r["exam_number"] for r in rows})
    types = sorted({r["question_type"] for r in rows})
    by_exam_type = {}
    totals = {e: 0.0 for e in exams}
    for r in rows:
        e, t = r["exam_number"], r["question_type"]
        p = _f(r.get("points"))
        by_exam_type[(e, t)] = (r.get("within_type_id", ""), p)
        totals[e] = totals.get(e, 0.0) + p

    total_vals = [totals[e] for e in exams]

    body = [_wide_table(exams, types, by_exam_type, totals), r"\newpage",
            r"\section{Summary Statistics — Total Points by Exam}",
            _stats_table(_stats(total_vals)), ""]

    _hist(total_vals, "Distribution of Total Exam Points", os.path.join(job_dir, "fig_total_hist.pdf"))
    body.append(r"\begin{center}\includegraphics[width=.85\textwidth]{fig_total_hist.pdf}\end{center}")
    if _density(total_vals, "Density of Total Exam Points", os.path.join(job_dir, "fig_total_dens.pdf")):
        body.append(r"\begin{center}\includegraphics[width=.85\textwidth]{fig_total_dens.pdf}\end{center}")
    body.append(r"\newpage")

    # Per question type
    body.append(r"\section{Summary Statistics by Question Type}")
    for t in types:
        per_exam = {}
        for r in rows:
            if r["question_type"] == t:
                per_exam[r["exam_number"]] = per_exam.get(r["exam_number"], 0.0) + _f(r.get("points"))
        vals = list(per_exam.values())
        body.append(rf"\subsection{{Question Type {_esc(t)}}}")
        body.append(_stats_table(_stats(vals)))
        fp = os.path.join(job_dir, f"fig_type_{t}.pdf")
        _hist(vals, f"Distribution of Points — Question Type {t}", fp)
        body.append(rf"\begin{{center}}\includegraphics[width=.8\textwidth]{{fig_type_{t}.pdf}}\end{{center}}")
        body.append(r"\newpage")

    # Per type-variant
    body.append(r"\section{Summary Statistics by Question Type and Variant}")
    combos = sorted({(r["question_type"], r["within_type_id"]) for r in rows})
    for i, (t, v) in enumerate(combos):
        vals = [_f(r.get("points")) for r in rows
                if r["question_type"] == t and r["within_type_id"] == v]
        body.append(rf"\subsection{{Question Type {_esc(t)} — Variant {_esc(v)}}}")
        body.append(_stats_table(_stats(vals)))
        if len(vals) > 2:
            fp = os.path.join(job_dir, f"fig_var_{t}_{v}.pdf")
            _hist(vals, f"Distribution — Q{t} Variant {v}", fp)
            body.append(rf"\begin{{center}}\includegraphics[width=.75\textwidth]{{fig_var_{t}_{v}.pdf}}\end{{center}}")
        else:
            body.append(rf"\emph{{Too few observations (N={len(vals)}) for a distribution plot.}}")
        if i % 2 == 1:
            body.append(r"\newpage")

    tex = r"""\documentclass[11pt]{article}
\usepackage[T1]{fontenc}
\usepackage[a4paper,margin=1in]{geometry}
\usepackage{booktabs}
\usepackage[table]{xcolor}
\usepackage{longtable}
\usepackage{graphicx}
\usepackage{float}
\floatplacement{figure}{H}
\setcounter{secnumdepth}{3}
\setcounter{tocdepth}{2}
\title{\textbf{Exam Results Report}}
\date{\today}
\begin{document}
\maketitle
\tableofcontents
\newpage
\section{Individual Exam Results}
""" + "\n".join(body) + "\n\\end{document}\n"

    with open(os.path.join(job_dir, "report.tex"), "w") as fh:
        fh.write(tex)

    with security.COMPILE_SEMAPHORE:
        cmd = security.latexmk_cmd("report.tex", "report", job_dir)
        res = _run(cmd, job_dir)
        if res.returncode != 0 and cmd and cmd[0] == "bwrap" and "bwrap:" in (res.stderr or ""):
            res = _run(security._base_latexmk("report.tex", "report"), job_dir)

    pdf = os.path.join(job_dir, "report.pdf")
    if res.returncode != 0 or not os.path.exists(pdf):
        tail = "\n".join((res.stdout or "").splitlines()[-15:])
        raise ReportError("Report compilation failed.\n" + tail)
    return pdf


def _run(cmd, job_dir):
    try:
        return subprocess.run(
            cmd, cwd=job_dir, env=security.compile_env(job_dir),
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=security.WALL_TIMEOUT_SECONDS,
            text=True, encoding="latin-1", errors="replace",
            preexec_fn=security.apply_rlimits,
        )
    except subprocess.TimeoutExpired:
        raise ReportError("Report compilation timed out.")
