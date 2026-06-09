r"""
Builds the exam LaTeX from editable fields, reproducing exam_template.tex.

Differences from the original file-based template:
  * The five editable regions (title, subject, course-no, date, rules block)
    are parameters. An empty course-no omits that line (covers the mock layout;
    "Mock Exam" is simply typed into the date field).
  * Manual-sorting headers (-m) are always on, so the fancyhdr machinery and the
    coloured \sethdr header codes are baked in unconditionally.
  * Per-exam substitution uses @@TOKENS@@ that cannot occur in user content,
    rather than bare strings like XN, and question text is injected last.
  * Fixed (non-editable) strings — the page-header labels and cover-page captions
    — are language-aware (English / German). The editable fields are untouched.
"""

# Fixed, non-editable wording per language. The editable fields (title, subject,
# course-no, date, rules) are supplied by the user and are not translated here.
LANGUAGES = {
    "en": {
        "exam": "Exam",
        "question": "Question",
        "points": "Points",
        "point": "Point",
        "addpaper": "Add. Paper",
        "examno": "Exam No.",
        "donotwrite": "Please do not write on this page.",
        "bonus": "Bonus",
    },
    "de": {
        "exam": "Prüfung",
        "question": "Aufgabe",
        "points": "Punkte",
        "point": "Punkt",
        "addpaper": "Zusatzblatt",
        "examno": "Prüfung Nr.",
        "donotwrite": "Bitte diese Seite nicht beschreiben.",
        "bonus": "Bonus",
    },
}


def labels(language: str) -> dict:
    """Fixed-string wording for a language code, falling back to English."""
    return LANGUAGES.get(language, LANGUAGES["en"])


# ---- coloured human-readable header code (the \colorbox row, -m mode) --------
# Order matches the original: exam | question_type | within_type_id | page.
def manual_header_code(exam2: str, qtype: str, within: str, page: str) -> str:
    return (
        f"\\colorbox{{white}}{{\\textcolor{{black}}{{{exam2}}}}}\\quad"
        f"\\colorbox{{black}}{{\\textcolor{{white}}{{{qtype}}}}}\\quad"
        f"\\colorbox{{white}}{{\\textcolor{{black}}{{{within}}}}}\\quad"
        f"\\colorbox{{black}}{{\\textcolor{{white}}{{{page}}}}}"
    )


# ---- per-question block (two pages: question page + blank answer page) --------
# @@HDR1@@/@@HDR2@@ -> \sethdr{...}; @@CODE@@ -> header barcode includegraphics;
# @@QNUM@@ -> printed number (or "Bonus"); @@PTS@@ -> points; @@QTEXT@@ -> text
# (@@QTEXT@@ is always substituted LAST so question text is never re-scanned).
QUESTION_BLOCK = r"""
@@HDR1@@
    \begin{tabularx}{\textwidth}{>{\centering\arraybackslash}m{1cm}|
        >{\centering\arraybackslash}m{1cm}|
        >{\centering\arraybackslash}m{1cm}|X|
        >{\centering\arraybackslash}m{2cm}}
        \hline
        \vspace{5pt}\includegraphics{@@CODE@@} & {\footnotesize @@EXAMLBL@@} \textbf{@@EXAM2@@} & {\footnotesize @@QLBL@@} \textbf{@@QNUM@@} & & \bfseries @@PTS@@ @@PTSLBL@@ \\
        \hline
        \multicolumn{5}{l}{
          \begin{minipage}[t]{0.975\textwidth}
            @@QTEXT@@
          \end{minipage}\vspace{2mm}} \\
        \hline
        \end{tabularx}
        \newpage
@@HDR2@@
    \begin{tabularx}{\textwidth}{>{\centering\arraybackslash}m{1cm}|
        >{\centering\arraybackslash}m{1cm}|
        >{\centering\arraybackslash}m{1cm}|X|
        >{\centering\arraybackslash}m{2cm}}
        \hline
        \vspace{5pt}\includegraphics{@@CODE@@} & {\footnotesize @@EXAMLBL@@} \textbf{@@EXAM2@@} & {\footnotesize @@QLBL@@} \textbf{@@QNUM@@} & &  \\
        \hline
        \end{tabularx}
        \newpage
"""

# ---- extra (overflow) page ---------------------------------------------------
EXTRA_PAGE_BLOCK = r"""
@@HDRX@@
    \begin{tabularx}{\textwidth}{>{\centering\arraybackslash}m{1cm}|
        >{\centering\arraybackslash}m{1cm}|
        >{\centering\arraybackslash}m{1cm}|X|
        >{\centering\arraybackslash}m{2cm}}
        \hline
        \vspace{5pt}\includegraphics{@@CODE@@} & {\footnotesize @@EXAMLBL@@} \textbf{@@EXAM2@@} & {\footnotesize @@ADDPAPER@@} & &  \\
        \hline
        \end{tabularx}
        \newpage
"""

# Default field values (lifted from exam_template.tex).
DEFAULT_FIELDS = {
    "exam_title": "Midterm Exam",
    "subject": "Econometrics III / Applied Econometrics",
    "course_no": "(Courses No. 4352 and 5913)",
    "date": "May 21, 2026",
    "rules_latex": r"""Please be aware of the following \textbf{rules} for this exam:

    \begin{itemize}
      \item You have \textbf{100 Minutes} to answer the questions.
      \item You can receive up to \textbf{40 points}.
      \item There are 11 differently weighted questions in this exam. You should aim not to use more than 2 minutes per point in order to have 20 minutes to check your answers. The order of questions is randomized and they can be answered independently.
      \item Your exam is marked with an ID number on every page. \textbf{Please do neither write your name nor your student ID number anywhere on this exam}, so that we can guarantee fairness and anonymity while grading. Name and exam number are matched on a separate attendance sheet.
      \item You are only allowed to answer the questions in \textbf{English}.
      \item The following \textbf{aids} are allowed:
      \begin{itemize}
        \item A calculator.
        \item The cheat sheet that was created by your Cheat Sheet Group.
        \item Empty sheets for taking notes (which cannot be handed in).
        \item A bilingual dictionary (English and your native language).
        \item Coffee.
      \end{itemize}
    \end{itemize}""",
}

# Fixed preamble + always-on fancyhdr machinery (verbatim from the original,
# with the -m header block merged in so it is unconditional).
_PREAMBLE = r"""\documentclass[a4paper]{article}
\usepackage[margin=2cm]{geometry}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{graphicx}
\usepackage{amsmath}
\usepackage{tgheros}
\renewcommand*\familydefault{\sfdefault}
\usepackage{tabularx}
\usepackage{array}
\setlength{\parindent}{0em}
\usepackage{listings}
\lstset{
  basicstyle=\ttfamily
}

\usepackage{tikz}
\usepackage{enumitem}
\usepackage{background}
\usetikzlibrary{calc}
\backgroundsetup{
  pages=all,
  angle=0,
  scale=1,
  vshift=0ex,
  contents={%
    \tikz[overlay, remember picture]
      \draw [line width=1pt, color=black]
             ($(current page.north west)+(2cm,-2cm)$)
             rectangle ($(current page.south east)+(-2cm,2cm)$);
  }
}

\pagestyle{empty}
\usepackage{everypage}
\AddEverypageHook{\BgThispage}

\tikzset{
  nodeSolid/.style={draw,circle,inner sep=0pt,minimum size=14mm, align=center},
  nodeDashed/.style={nodeSolid,dashed},
  edge/.style={line width=1.4pt,->},
  edgeDashed/.style={edge,dashed}
}

\usepackage{fancyhdr}
\usepackage{xcolor}
\pagestyle{fancy}
\fancyhf{}
\renewcommand{\headrulewidth}{0pt}
\newcommand{\hdrcode}{}
\newcommand{\sethdr}[1]{\gdef\hdrcode{#1}}
\fancyhead[R]{\Large\textbf{\hdrcode}}

\begin{document}
"""


def build_skeleton(fields: dict, language: str = "en") -> str:
    """Assemble the full template with editable fields baked in.

    Returns a string still containing per-exam tokens:
      @@EXAM2@@  @@CODE@@ (x2 header + per-question/extra)  @@EXAMNO@@
      @@HDR1@@ @@HDR2@@ @@HDRX@@  @@QUESTIONS@@  @@EXTRAPAGES@@
    """
    f = {**DEFAULT_FIELDS, **{k: v for k, v in (fields or {}).items() if v is not None}}
    L = labels(language)

    # Centered title block; each line is its own paragraph (blank-line separated).
    # Course-no line is omitted entirely when empty -> mock layout.
    title_lines = [r"\Large\bfseries " + f["exam_title"], "", f["subject"]]
    if str(f.get("course_no", "")).strip():
        title_lines += ["", f["course_no"]]
    title_lines += ["", f["date"]]
    title_block = "\n      ".join(title_lines)

    # Header sethdr for the two cover pages (type 00, pages 01/02).
    hdr1 = "\\sethdr{" + manual_header_code("@@EXAM2@@", "00", "00", "01") + "}"
    hdr2 = "\\sethdr{" + manual_header_code("@@EXAM2@@", "00", "00", "02") + "}"

    body = (
        _PREAMBLE
        + r"""
\renewcommand{\arraystretch}{1.5}
\centering
  \begin{tabularx}{\textwidth}{|>{\centering\arraybackslash}m{1cm}|
  >{\centering\arraybackslash}m{2cm}
  X|
  >{\centering\arraybackslash}m{2cm}|}
  \hline
  """ + hdr1 + r"""
  \vspace{5pt}\includegraphics{@@CODE@@} &   & &  \\
  \hline
  \end{tabularx}
\begin{minipage}{0.95\textwidth}
    \vspace{1em}
    \begin{center}
      """ + title_block + r"""
    \end{center}

    """ + f["rules_latex"] + r"""

    \begin{tabularx}{\textwidth}{|>{\centering\arraybackslash}m{1cm}|
      >{\centering\arraybackslash}m{2cm}
      X|
      >{\centering\arraybackslash}m{2cm}|}
      \hline
      \rule{0pt}{1cm}& {\textbf{""" + L["examno"] + r"""}}  & & \bfseries\Huge @@EXAMNO@@ \\
      \hline
      \end{tabularx}

  \end{minipage}

  \newpage

  \begin{minipage}{\textwidth}
    \begin{tabularx}{\textwidth}{|>{\centering\arraybackslash}m{1cm}|
      X
      >{\centering\arraybackslash}m{2cm}|}
      \hline
      """ + hdr2 + r"""
      \vspace{5pt}\includegraphics{@@CODE@@} & {\textbf{""" + L["donotwrite"] + r"""}}  &\\
      \hline
      \end{tabularx}
  \end{minipage}

  \newpage

@@QUESTIONS@@

@@EXTRAPAGES@@

\end{document}
"""
    )
    return body
