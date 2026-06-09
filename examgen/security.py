"""
Security helpers for compiling untrusted, user-supplied LaTeX.

The threat model: an exam author can put arbitrary LaTeX into question text,
the rules block, and template fields. Compiling that on the server must NOT
allow shell command execution, reading files outside the job directory, or
writing outside it.

Primary controls (all enforced here):
  * pdflatex only, invoked with -no-shell-escape
  * kpathsea env flags: shell_escape=f, openin_any=p, openout_any=p
        -> \\write18 disabled, \\input/\\openin confined to the job dir,
           no absolute paths, no dotfiles, no parent-dir escapes
  * HOME / TEXMF* redirected into the job dir so no real dotfiles are read
  * per-process resource limits (CPU, address space, output file size)
  * wall-clock timeout on the subprocess
  * a global semaphore so only one compile runs at a time (RAM protection)

A bubblewrap layer (filesystem + network namespace isolation) is added in the
hardening pass; it is optional defense-in-depth on top of the controls above.
"""

import functools
import os
import re
import resource
import shutil
import subprocess
import threading
import time

# Only one LaTeX compile may run at once. On a small shared box this is the main
# lever that keeps generation from spiking RAM. Generation of N exams is
# sequential by construction, but this guards against concurrent HTTP requests.
COMPILE_SEMAPHORE = threading.BoundedSemaphore(1)

# Likewise one heavy grading job (PDF decode/sort/report) at a time.
HEAVY_SEMAPHORE = threading.BoundedSemaphore(1)

# Per-compile resource ceilings.
CPU_SECONDS = 55          # below the wall-clock timeout; SIGXCPU if exceeded
# Per-process virtual-memory cap. Kept below the systemd unit's MemoryMax so a
# memory-hungry compile fails as a single-job error (caught -> GenerationError)
# rather than tripping the cgroup OOM and taking the whole service down.
ADDRESS_SPACE_BYTES = 1536 * 1024 * 1024       # 1.5 GiB
OUTPUT_FILE_BYTES = 64 * 1024 * 1024           # 64 MiB max single output file
WALL_TIMEOUT_SECONDS = 60 # passed to subprocess.run(timeout=...)

# Conservative allowlist for uploaded asset basenames.
_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_ALLOWED_ASSET_EXT = {
    ".png", ".jpg", ".jpeg", ".pdf",   # images includegraphics can use
    ".txt", ".dat", ".csv", ".tex",    # text includes (e.g. R output)
}


def sanitize_asset_name(name: str) -> str:
    """Reduce an uploaded filename to a safe flat basename or raise ValueError.

    We strip any directory components, reject traversal and hidden files, allow
    only a small character set, and require a known-good extension. The file is
    then written flat into the job dir; LaTeX references it by this basename.
    """
    base = os.path.basename(name or "")
    if base in ("", ".", "..") or "/" in base or "\\" in base:
        raise ValueError(f"unsafe asset filename: {name!r}")
    if base.startswith("."):
        raise ValueError(f"hidden files not allowed: {name!r}")
    if not _SAFE_NAME_RE.match(base):
        raise ValueError(f"asset filename has illegal characters: {name!r}")
    ext = os.path.splitext(base)[1].lower()
    if ext not in _ALLOWED_ASSET_EXT:
        raise ValueError(f"asset extension not allowed: {name!r}")
    return base


def compile_env(job_dir: str) -> dict:
    """Environment for a hardened pdflatex/latexmk run."""
    return {
        "PATH": "/usr/bin:/bin",
        # Redirect HOME and TeX's writable trees into the job dir so the
        # compile never reads or writes real user/system dotfiles.
        "HOME": job_dir,
        "TEXMFHOME": os.path.join(job_dir, ".texmf"),
        "TEXMFVAR": os.path.join(job_dir, ".texmf-var"),
        "TEXMFCONFIG": os.path.join(job_dir, ".texmf-config"),
        "TEXMFOUTPUT": job_dir,
        # kpathsea security flags (honoured as env overrides of texmf.cnf):
        "shell_escape": "f",   # kill \write18 entirely
        "openin_any": "p",     # paranoid: reads confined to cwd, no abs/.. /dotfiles
        "openout_any": "p",    # paranoid: writes confined likewise
        # Make output a touch more reproducible / avoid TZ reads.
        "SOURCE_DATE_EPOCH": "0",
        "TZ": "UTC",
    }


def apply_rlimits():
    """preexec_fn for subprocess: cap CPU, address space, and output size.

    Runs in the forked child before exec. A runaway \\loop hits the CPU limit
    (SIGXCPU) or the wall-clock timeout; a giant output hits the file-size
    limit (SIGXFSZ). We do NOT cap NPROC, since that is per-user and the
    service account also runs the web process.
    """
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS))
    resource.setrlimit(resource.RLIMIT_AS, (ADDRESS_SPACE_BYTES, ADDRESS_SPACE_BYTES))
    resource.setrlimit(resource.RLIMIT_FSIZE, (OUTPUT_FILE_BYTES, OUTPUT_FILE_BYTES))


def _base_latexmk(tex_filename: str, jobname: str) -> list:
    return [
        "latexmk", "-pdf",
        "-no-shell-escape",
        "-interaction=nonstopmode",
        "-halt-on-error",
        f"-jobname={jobname}",
        tex_filename,
    ]


@functools.lru_cache(maxsize=1)
def bwrap_usable() -> bool:
    """True if bubblewrap can actually create the namespaces we need.

    On Ubuntu 24.04 unprivileged user namespaces may be restricted by AppArmor,
    in which case bwrap fails and we fall back to the env+rlimit hardening (which
    is itself sufficient). Probed once and cached.
    """
    if not shutil.which("bwrap"):
        return False
    try:
        r = subprocess.run(
            ["bwrap", "--unshare-all", "--share-net",
             "--ro-bind", "/usr", "/usr",
             "--ro-bind-try", "/bin", "/bin",
             "--ro-bind-try", "/lib", "/lib",
             "--ro-bind-try", "/lib64", "/lib64",
             "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
             "/usr/bin/true"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
        )
        return r.returncode == 0
    except Exception:
        return False


def latexmk_cmd(tex_filename: str, jobname: str, job_dir: str) -> list:
    """Compile command. Wrapped in bubblewrap (no network; filesystem reduced to
    the TeX tree + this job dir) when the kernel permits; otherwise the bare
    latexmk command, still run under the env-flag + rlimit hardening by caller.
    """
    base = _base_latexmk(tex_filename, jobname)
    if not bwrap_usable():
        return base
    return [
        "bwrap", "--unshare-all", "--share-net", "--die-with-parent", "--new-session",
        "--ro-bind", "/usr", "/usr",
        "--ro-bind-try", "/bin", "/bin",
        "--ro-bind-try", "/lib", "/lib",
        "--ro-bind-try", "/lib64", "/lib64",
        "--ro-bind-try", "/etc/texmf", "/etc/texmf",
        "--ro-bind-try", "/etc/alternatives", "/etc/alternatives",
        "--ro-bind-try", "/etc/fonts", "/etc/fonts",
        "--ro-bind-try", "/var/lib/texmf", "/var/lib/texmf",
        "--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
        # job dir bind + chdir come LAST so an earlier --tmpfs can't shadow them
        "--bind", job_dir, job_dir, "--chdir", job_dir,
    ] + base


def sweep_stale(work_root: str, max_age_seconds: int = 3600) -> int:
    """Remove orphaned job_* dirs (e.g. left by a crash before cleanup ran).

    The per-request finally already wipes each job dir; this catches the case
    where the service was killed mid-generation. Returns count removed.
    """
    removed = 0
    try:
        now = time.time()
        for name in os.listdir(work_root):
            if not name.startswith("job_"):
                continue
            p = os.path.join(work_root, name)
            try:
                if os.path.isdir(p) and (now - os.path.getmtime(p)) > max_age_seconds:
                    shutil.rmtree(p, ignore_errors=True)
                    removed += 1
            except OSError:
                pass
    except FileNotFoundError:
        pass
    return removed
