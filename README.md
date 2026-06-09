# exams

_**Note:** This Readme file was written by generative AI. My reasoning was that it would be most comprehensive this way._

A self-hosted web app for **generating randomized exams** from a question pool and
**grading scanned exams** semi-automatically. Live at
[exams.maxheinze.eu](https://exams.maxheinze.eu).

Each generated exam page carries a DataMatrix barcode encoding its exam number,
question, type, variant, points, and page. After the exams are written and scanned
back in, the grader reads those barcodes to sort the pages, lets you enter points
per question, and produces individual graded PDFs plus a statistics report.

## What it does

**Generate.** From a pool of question types and variants, build *N* randomized exams
(one variant drawn per type per exam, order shuffled). Each question spans a question
page and a blank answer page; optional extra blank pages can be appended. Output is a
ZIP of per-exam PDFs. Cover text (title, subject, date, rules) is editable; fixed
wording is available in English and German. Question text is plain LaTeX — the
preamble provides `graphicx`, `amsmath`, `listings`, `tikz`, `enumitem`, and more.

**Grade**, in three steps:

1. **Read & sort** (server) — scanned PDFs are merged, each page's DataMatrix code is
   decoded, and the pages are reordered into a canonical sort. Produces `sorted.pdf`,
   a `pagelist.csv`, and (when present) `extrasheets.pdf` / `nocode.pdf`.
2. **Grade** (browser) — `pdf.js` renders a preview of each question; you enter points.
3. **Graded PDFs & report** — points are written to CSVs and a results report PDF is
   compiled (server); the sorted PDF is split into one PDF per exam (browser).

Heavy, per-page PDF work in steps 2–3 runs **client-side** so the small server only
ever does the lightweight barcode decode and a short report compile.

## Architecture

- **Backend**: Python + [FastAPI](https://fastapi.tiangolo.com/) on `uvicorn`.
  - `examgen/template.py` — builds the exam LaTeX from editable fields (EN/DE labels).
  - `examgen/barcode.py` — DataMatrix barcodes via `zint`.
  - `examgen/generate.py` — assembles and compiles exams; returns a ZIP.
  - `examgen/grading.py` — reads/sorts scanned PDFs (poppler + `pylibdmtx`).
  - `examgen/report.py` — results report (statistics + `matplotlib` figures + LaTeX).
  - `examgen/security.py` — the hardened-compile machinery (see below).
  - `app.py` — HTTP API; `gen_cli.py` — a command-line generator.
- **Frontend**: a dependency-free vanilla-JS single-page app in `frontend/` (no build
  step). It uses three vendored browser libraries — `pdf.js`, `pdf-lib`, `JSZip` —
  which are **not committed**; run `frontend/fetch-vendor.sh` to populate
  `frontend/vendor/`. See [`frontend/README.md`](frontend/README.md).

## Security model

User-supplied LaTeX (question text, rules, cover fields) is compiled on the server, so
the compile is sandboxed in `examgen/security.py`:

- `pdflatex` only, invoked `-no-shell-escape`; kpathsea flags `shell_escape=f`,
  `openin_any=p`, `openout_any=p` (no `\write18`, reads/writes confined to the job dir).
- `HOME`/`TEXMF*` redirected into the job dir; per-process `RLIMIT` caps on CPU,
  address space, and output size; a wall-clock timeout; one compile at a time.
- An optional `bubblewrap` namespace layer when the kernel permits, with automatic
  fallback to the env+rlimit hardening otherwise.
- Stateless: each request works in a `job_*` dir that is wiped afterward, with an
  hourly sweep of any orphans.

## Quick start (development)

System packages (Debian/Ubuntu names):

```
sudo apt install texlive-latex-recommended texlive-latex-extra texlive-fonts-recommended \
                 latexmk poppler-utils libdmtx0t64 zint bubblewrap
```

Python:

```
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
```

Frontend libraries (needed for the grading UI):

```
./frontend/fetch-vendor.sh
```

Run the API and serve the frontend (any static server works for the latter):

```
EXAMS_WORK_ROOT=$PWD/work uvicorn app:app --host 127.0.0.1 --port 8003
python3 -m http.server --directory frontend 8080   # then open http://localhost:8080
```

In production the frontend is served by nginx and `/api/` is reverse-proxied to
uvicorn. See [`docs/DEPLOY.md`](docs/DEPLOY.md) for the full VPS setup (service user,
systemd unit, nginx, TLS, rate limiting).

## Repository layout

```
app.py              FastAPI app (HTTP API)
gen_cli.py          command-line exam generator
exams.service       systemd unit (reference)
requirements.txt    Python dependencies
examgen/            backend package (see modules above)
frontend/           vanilla-JS SPA (vendored libs fetched, not committed)
docs/DEPLOY.md      production deployment guide
```

## Deploy after changes to the repo

Deploy:

```bash
sudo /home/exams/app/deploy.sh
```

This pulls the latest commit, syncs the frontend to nginx's web root, restarts the
service, and verifies it came back up. Hard-refresh the browser after a frontend change
to clear the cache.
