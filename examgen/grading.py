r"""
Grading step 1 — read scanned exam pages and sort them.

Memory strategy (this is the whole point):
  * pages are rasterized ONE AT A TIME, and only the top-left 6.5x6.5 cm crop
    where the DataMatrix sits, via `pdftoppm -x -y -W -H -singlefile`. Peak RAM
    is a single page's decode, independent of page count.
  * the sorted / split PDFs are assembled with pikepdf by copying page objects
    (no rasterization), so output assembly is structural, not pixel-based.
  * one heavy job at a time (caller holds security.HEAVY_SEMAPHORE).

Outputs (in job_dir):
  sorted.pdf      pages reordered: gradeable questions (by type, variant, exam,
                  page), then cover pages (type 00), then unreadable pages.
  pagelist.csv    one row per page: new position + decoded fields + empty points.
  extrasheets.pdf only written if any type-99 pages exist.
  nocode.pdf      only written if any unreadable pages exist.
"""

import csv
import os
import subprocess

from PIL import Image, ImageOps
from pylibdmtx.pylibdmtx import decode
import pikepdf


class GradingError(Exception):
    """User-safe error for the grading pipeline."""


CROP_CM = 6.5
DECODE_DPI = 300
_CROP_PX = round(CROP_CM / 2.54 * DECODE_DPI)   # 768 px at 300 dpi


def try_decode(img):
    """Decode a DataMatrix with progressively more aggressive fallbacks."""
    r = decode(img, timeout=1000, max_count=1)
    if r:
        return r
    gray = ImageOps.autocontrast(ImageOps.grayscale(img))
    bw = gray.point(lambda p: 255 if p > 128 else 0, mode="L")
    r = decode(bw, timeout=1500, max_count=1)
    if r:
        return r
    up = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    r = decode(up, timeout=2000, max_count=1)
    if r:
        return r
    up_bw = ImageOps.autocontrast(ImageOps.grayscale(up)).point(
        lambda p: 255 if p > 128 else 0, mode="L")
    r = decode(up_bw, timeout=2500, max_count=1)
    return r or []


def _decode_page(merged_pdf, page_num, job_dir):
    """Rasterize only the top-left crop of one page and decode it."""
    prefix = os.path.join(job_dir, "crop")
    crop_png = prefix + ".png"
    subprocess.run(
        ["pdftoppm", "-png", "-singlefile", "-r", str(DECODE_DPI),
         "-x", "0", "-y", "0", "-W", str(_CROP_PX), "-H", str(_CROP_PX),
         "-f", str(page_num), "-l", str(page_num), merged_pdf, prefix],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    try:
        with Image.open(crop_png) as im:
            im.load()
            decoded = try_decode(im)
    finally:
        if os.path.exists(crop_png):
            os.remove(crop_png)

    if decoded:
        v = decoded[0].data.decode("utf-8", "replace")
        return (v, v[0:2], v[2:4], v[4:6], v[6:8], v[8:10], v[10:])
    return ("No DataMatrix found", "N/A", "N/A", "N/A", "N/A", "N/A", "N/A")


def _merge(pdf_paths, job_dir):
    """Concatenate one or more uploaded PDFs into merged.pdf; return its path."""
    if len(pdf_paths) == 1:
        return pdf_paths[0]
    merged_path = os.path.join(job_dir, "merged.pdf")
    out = pikepdf.Pdf.new()
    srcs = []
    try:
        for p in pdf_paths:
            s = pikepdf.Pdf.open(p)
            srcs.append(s)
            out.pages.extend(s.pages)
        out.save(merged_path)
    finally:
        for s in srcs:
            s.close()
        out.close()
    return merged_path


def read_and_sort(pdf_paths, job_dir, progress=None, max_pages=2500):
    """Decode + sort. `progress(done, total)` is called per page. Returns a summary."""
    merged = _merge(pdf_paths, job_dir)

    with pikepdf.Pdf.open(merged) as pdf:
        num_pages = len(pdf.pages)
    if num_pages == 0:
        raise GradingError("The uploaded PDF has no pages.")
    if num_pages > max_pages:
        raise GradingError(f"{num_pages} pages exceeds the limit of {max_pages}.")

    # Phase 1 — decode (one page in memory at a time)
    rows = []   # (orig_page, code, exam, qnum, qtype, within, maxpts, page_within)
    for n in range(1, num_pages + 1):
        code, exam, qnum, qtype, within, maxpts, pw = _decode_page(merged, n, job_dir)
        rows.append((n, code, exam, qnum, qtype, within, maxpts, pw))
        if progress:
            progress(n, num_pages)

    # Phase 2 — sort: gradeable (type, variant, exam, page), then 00, then N/A
    rows.sort(key=lambda x: (x[4] if x[4] not in ("00", "N/A") else "99", x[5], x[2], x[7]))
    rows.sort(key=lambda x: (x[4] == "N/A", x[4] == "00"))

    # Phase 3 — assemble PDFs structurally (no rasterization)
    sorted_path = os.path.join(job_dir, "sorted.pdf")
    extras_path = os.path.join(job_dir, "extrasheets.pdf")
    nocode_path = os.path.join(job_dir, "nocode.pdf")
    n_extra = n_nocode = 0

    with pikepdf.Pdf.open(merged) as src:
        out = pikepdf.Pdf.new()
        out_99 = pikepdf.Pdf.new()
        out_na = pikepdf.Pdf.new()
        for r in rows:
            page = src.pages[r[0] - 1]
            out.pages.append(page)
            if r[4] == "99":
                out_99.pages.append(page); n_extra += 1
            elif r[4] == "N/A":
                out_na.pages.append(page); n_nocode += 1
        out.save(sorted_path); out.close()
        if n_extra:
            out_99.save(extras_path)
        out_99.close()
        if n_nocode:
            out_na.save(nocode_path)
        out_na.close()

    # Phase 4 — pagelist.csv
    csv_path = os.path.join(job_dir, "pagelist.csv")
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["new_page_number", "datamatrix_code", "exam_number",
                    "question_number", "question_type", "within_type_id",
                    "max_points", "page_within_question", "points"])
        for i, r in enumerate(rows, start=1):
            w.writerow([i, r[1], r[2], r[3], r[4], r[5], r[6], r[7], ""])

    gradeable = sum(1 for r in rows
                    if r[7] == "1" and r[4] not in ("00", "99", "N/A"))
    return {
        "total_pages": num_pages,
        "gradeable_questions": gradeable,
        "extrasheets": n_extra,
        "nocode": n_nocode,
        "has_extrasheets": bool(n_extra),
        "has_nocode": bool(n_nocode),
        "sorted_pdf": "sorted.pdf",
        "pagelist_csv": "pagelist.csv",
    }
