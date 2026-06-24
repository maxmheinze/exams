# Frontend

A dependency-free, single-page vanilla-JS app. There is **no build step**: the three
files here (`index.html`, `style.css`, `app.js`) are served as-is. All state lives in
memory; the app talks to the backend only under `/api/`.

## Vendored libraries

The app loads several third-party browser libraries as plain `<script>` / `<link>`
tags from `vendor/`. They are **not committed** to the repo. Fetch the pinned versions
with:

```
./fetch-vendor.sh        # requires npm
```

This writes:

| File                      | Package / version          | Global       | Used for                            |
|---------------------------|----------------------------|--------------|-------------------------------------|
| `vendor/pdf.min.js`       | `pdfjs-dist@3.11.174` (UMD)| `pdfjsLib`   | rendering question previews         |
| `vendor/pdf.worker.min.js`| `pdfjs-dist@3.11.174`      | —            | pdf.js worker                       |
| `vendor/pdf-lib.min.js`   | `pdf-lib@1.17.1`           | `PDFLib`     | splitting the sorted PDF by exam    |
| `vendor/jszip.min.js`     | `jszip@3.10.1`             | `JSZip`      | zipping downloads and per-exam PDFs |
| `vendor/codemirror.js`    | `codemirror@5.65.16`       | `CodeMirror` | the LaTeX snippet editors           |
| `vendor/codemirror.css`   | `codemirror@5.65.16`       | —            | editor styling                      |
| `vendor/stex.js`          | `codemirror@5.65.16`       | —            | CodeMirror's LaTeX (stex) mode      |

`codemirror.js` must load before `stex.js`, and both before `app.js` (see `index.html`).
If a library is missing, the editors degrade gracefully to plain `<textarea>`s.

If you bump a version, update `fetch-vendor.sh`, the tags in `index.html`, and (for
pdf.js) the worker path in `app.js` (`pdfjsLib.GlobalWorkerOptions.workerSrc`).

## How it fits together

- The generate flow posts a JSON spec (plus any asset files) to `/api/generate` and
  downloads the returned ZIP. If a compile fails, the error response carries the
  failing `.tex` and its log, and the UI offers them as a single ZIP download.
- The grade flow streams progress from `/api/grade/read`, fetches the sorted PDF and
  page list, renders previews and collects points in the browser, posts the points CSV
  to `/api/grade/report` for the report PDF, and splits the PDF locally with `pdf-lib`.
- Multi-file outputs are bundled into a single ZIP per step so nothing opens in a tab.
