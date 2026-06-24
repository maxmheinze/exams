#!/usr/bin/env bash
# Populate frontend/vendor/ with the pinned third-party browser libraries.
# These are intentionally not committed to the repo. Requires npm.
set -euo pipefail
cd "$(dirname "$0")"
DEST="vendor"
mkdir -p "$DEST"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT
cd "$tmp"
npm pack pdfjs-dist@3.11.174 pdf-lib@1.17.1 jszip@3.10.1 codemirror@5.65.16 >/dev/null
for t in *.tgz; do tar xzf "$t"; mv package "${t%.tgz}"; done
cd - >/dev/null
cp "$tmp"/pdfjs-dist-3.11.174/build/pdf.min.js        "$DEST/pdf.min.js"
cp "$tmp"/pdfjs-dist-3.11.174/build/pdf.worker.min.js "$DEST/pdf.worker.min.js"
cp "$tmp"/pdf-lib-1.17.1/dist/pdf-lib.min.js          "$DEST/pdf-lib.min.js"
cp "$tmp"/jszip-3.10.1/dist/jszip.min.js              "$DEST/jszip.min.js"
cp "$tmp"/codemirror-5.65.16/lib/codemirror.js        "$DEST/codemirror.js"
cp "$tmp"/codemirror-5.65.16/lib/codemirror.css       "$DEST/codemirror.css"
cp "$tmp"/codemirror-5.65.16/mode/stex/stex.js        "$DEST/stex.js"
echo "Vendored libraries written to $DEST/"
