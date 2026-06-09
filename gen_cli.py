#!/usr/bin/env python3
r"""
CLI harness for the exam generation engine — for testing on the VPS before the
web layer exists. The web app (Phase 2b) will call examgen.generate_exams()
directly; this just exercises the same function from the command line.

Examples:
  # zero-dependency smoke test (built-in 2-question pool, no images needed):
  python gen_cli.py --selftest

  # real pool, subset of types, type 11 as bonus, with image/text assets:
  python gen_cli.py -p question_pool_31.json -n 3 -q 01 02 05 11 \
      --bonus 11 --assets ./assets -e 2 -o exams.zip
"""
import argparse, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from examgen import generate_exams, GenerationError

_SELFTEST_POOL = [
    {"question_type": "01", "within_type_id": "01", "points": 4,
     "question_text": r"Compute $\int_0^1 x^2\,dx$ and \textbf{show your work}."},
    {"question_type": "02", "within_type_id": "01", "points": 3,
     "question_text": r"State the Gauss--Markov assumptions."},
]

def main():
    ap = argparse.ArgumentParser(description="Generate exams (test harness).")
    ap.add_argument("-p", "--pool", help="question pool JSON")
    ap.add_argument("-n", type=int, default=1, help="number of exams")
    ap.add_argument("-e", "--extra", type=int, default=0, choices=[0,2,4,6,8])
    ap.add_argument("-q", "--qtypes", nargs="+", help="question types to draw")
    ap.add_argument("--bonus", nargs="*", default=[], help="question types to mark as Bonus")
    ap.add_argument("-d", "--demo", action="store_true", help="demo: all questions, sorted")
    ap.add_argument("-f", "--fixed", action="store_true", help="fixed: one set reused, reshuffled")
    ap.add_argument("--assets", help="directory of image/txt assets referenced by questions")
    ap.add_argument("--title"); ap.add_argument("--subject")
    ap.add_argument("--course-no", dest="course_no")
    ap.add_argument("--date"); ap.add_argument("--rules-file")
    ap.add_argument("--seed", type=int)
    ap.add_argument("--work", default="/home/exams/work", help="ephemeral work root")
    ap.add_argument("-o", "--out", default="exams.zip")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()

    if a.selftest:
        pool = _SELFTEST_POOL
    elif a.pool:
        pool = json.load(open(a.pool, encoding="utf-8"))
    else:
        ap.error("provide -p POOL or --selftest")

    assets = {}
    if a.assets:
        for fn in os.listdir(a.assets):
            fp = os.path.join(a.assets, fn)
            if os.path.isfile(fp):
                assets[fn] = open(fp, "rb").read()

    fields = {k: v for k, v in {
        "exam_title": a.title, "subject": a.subject, "course_no": a.course_no,
        "date": a.date,
        "rules_latex": open(a.rules_file, encoding="utf-8").read() if a.rules_file else None,
    }.items() if v is not None}

    try:
        zip_bytes = generate_exams(
            pool, fields=fields, n=a.n, extra_pages=a.extra,
            q_types=a.qtypes, bonus_types=set(a.bonus),
            demo=a.demo, fixed=a.fixed, assets=assets, seed=a.seed,
            work_root=a.work,
        )
    except GenerationError as e:
        print(f"GenerationError: {e}", file=sys.stderr); sys.exit(1)

    with open(a.out, "wb") as fh:
        fh.write(zip_bytes)
    print(f"Wrote {a.out} ({len(zip_bytes)} bytes).")

if __name__ == "__main__":
    main()
