"""Document conversions: Markdown -> PDF/Word (pandoc + LaTeX), .tex -> PDF (latexmk),
Word/ODT/RTF/HTML -> editable Markdown, Office files -> PDF preview, table previews."""
import asyncio
import hashlib
import re
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Optional

from .config import ROOT, TMP, agent_env
from .workspace_manager import unique_path

TEMPLATES = Path(__file__).resolve().parent / "templates"
BUILD_TIMEOUT = 240

MARKDOWN_EXT = {".md", ".markdown", ".txt"}
TEX_EXT = {".tex"}
IMPORTABLE_EXT = {".docx", ".odt", ".rtf", ".html", ".htm", ".epub"}
OFFICE_PREVIEW_EXT = {".docx", ".doc", ".odt", ".rtf", ".pptx", ".ppt", ".odp"}
TABLE_EXT = {".csv", ".tsv", ".xlsx", ".xls", ".ods"}

_locks: dict[str, asyncio.Lock] = {}


def _lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


class BuildError(Exception):
    def __init__(self, message: str, log: str = ""):
        super().__init__(message)
        self.message = message
        self.log = log


async def _run(cmd: list, cwd: Path, env: dict, timeout: int = BUILD_TIMEOUT) -> tuple[int, str]:
    proc = await asyncio.create_subprocess_exec(
        *cmd, cwd=str(cwd), env=env,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        stdin=asyncio.subprocess.DEVNULL, start_new_session=True,
    )
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise BuildError("Creating the document took too long and was stopped.")
    return proc.returncode, out.decode("utf-8", "replace")


@lru_cache(maxsize=1)
def _font_families() -> frozenset:
    try:
        out = subprocess.run(["fc-list", ":", "family"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return frozenset()
    fams = set()
    for line in out.splitlines():
        for f in line.split(","):
            fams.add(f.strip())
    return frozenset(fams)


def _pick(*candidates: str) -> Optional[str]:
    fams = _font_families()
    for c in candidates:
        if c in fams:
            return c
    return None


def _friendly_latex_error(log: str) -> str:
    """Pull the first real LaTeX/pandoc error out of a long log."""
    lines = log.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("!") or ": error:" in line.lower() or re.match(r"^.*:\d+: ", line):
            snippet = " ".join(l.strip() for l in lines[i:i + 3] if l.strip())
            return snippet[:400]
    for line in lines:
        low = line.lower()
        if "error" in low or "not found" in low or "could not" in low:
            return line.strip()[:400]
    return (lines[-1] if lines else "Unknown error").strip()[:400]


def _has_bibliography_meta(text: str) -> bool:
    m = re.match(r"^---\s*\n(.*?)\n(---|\.\.\.)\s*\n", text, re.S)
    return bool(m and re.search(r"^bibliography\s*:", m.group(1), re.M))


async def markdown_to(src: Path, project_root: Path, fmt: str) -> Path:
    """fmt: 'pdf' or 'docx'. Output is written next to the source file."""
    src, project_root = src.resolve(), project_root.resolve()
    out = src.with_suffix("." + fmt)
    env = agent_env(project_root)
    cmd = [
        "pandoc", src.name, "-o", str(out),
        "--from", "markdown",
        "--standalone", "--citeproc",
        f"--resource-path=.:{project_root}",
    ]
    text = src.read_text(encoding="utf-8", errors="replace")
    if not _has_bibliography_meta(text):
        for bib in (src.parent / "references.bib", project_root / "references.bib"):
            if bib.exists():
                cmd.append(f"--bibliography={bib}")
                break
    if fmt == "pdf":
        if not shutil.which("xelatex"):
            raise BuildError("LaTeX is not installed on the server yet (run scripts/install_deps.sh).")
        cmd += [
            "--pdf-engine=xelatex",
            f"--include-in-header={TEMPLATES / 'pdf-header.tex'}",
            "-V", "papersize=a4", "-V", "geometry:margin=2.4cm", "-V", "fontsize=11pt",
            "-V", "colorlinks=true", "-V", "linkcolor=MidnightBlue", "-V", "urlcolor=MidnightBlue",
            "-V", "citecolor=MidnightBlue", "-V", "linestretch=1.15",
        ]
        # Front matter in the note (mainfont:, geometry:, ...) overrides these defaults.
        main = _pick("Libertinus Serif", "Noto Serif", "TeX Gyre Pagella", "DejaVu Serif")
        sans = _pick("Libertinus Sans", "Noto Sans", "TeX Gyre Heros", "DejaVu Sans")
        mono = _pick("DejaVu Sans Mono", "Noto Sans Mono")
        math = _pick("Libertinus Math", "TeX Gyre Pagella Math")
        for key, val in (("mainfont", main), ("sansfont", sans), ("monofont", mono), ("mathfont", math)):
            if val:
                cmd += ["-V", f"{key}={val}"]
        if mono:
            cmd += ["-V", "monofontoptions=Scale=0.85"]
    else:
        ref = TEMPLATES / "reference.docx"
        if ref.exists():
            cmd.append(f"--reference-doc={ref}")

    async with _lock(str(out)):
        code, log = await _run(cmd, src.parent, env)
    if code != 0 or not out.exists():
        raise BuildError(_friendly_latex_error(log), log[-6000:])
    return out


async def tex_to_pdf(src: Path, project_root: Path) -> Path:
    src, project_root = src.resolve(), project_root.resolve()
    if not shutil.which("latexmk"):
        raise BuildError("LaTeX is not installed on the server yet (run scripts/install_deps.sh).")
    text = src.read_text(encoding="utf-8", errors="replace")
    head = text[:3000]
    m = re.search(r"%\s*!\s*TEX\s+(?:TS-)?program\s*=\s*(\w+)", head, re.I)
    prog = (m.group(1).lower() if m else "")
    if prog == "lualatex" or "luacode" in head:
        flag = "-pdflua"
    elif prog == "xelatex" or "fontspec" in text or "polyglossia" in text:
        flag = "-pdfxe"
    else:
        flag = "-pdf"
    build = TMP / project_root.name / "latex-build" / hashlib.sha1(str(src).encode()).hexdigest()[:12]
    build.mkdir(parents=True, exist_ok=True)
    cmd = ["latexmk", flag, "-interaction=nonstopmode", "-halt-on-error", "-file-line-error",
           f"-outdir={build}", src.name]
    async with _lock(str(src)):
        code, log = await _run(cmd, src.parent, agent_env(project_root))
    built = build / (src.stem + ".pdf")
    if code != 0 or not built.exists():
        logfile = build / (src.stem + ".log")
        full = logfile.read_text(errors="replace") if logfile.exists() else log
        raise BuildError(_friendly_latex_error(full), full[-6000:])
    out = src.with_suffix(".pdf")
    shutil.copyfile(built, out)
    return out


async def import_to_markdown(src: Path, project_root: Path) -> Path:
    """Word/ODT/RTF/HTML -> Markdown note (images extracted next to it)."""
    src, project_root = src.resolve(), project_root.resolve()
    out = unique_path(src.with_suffix(".md"))
    media = out.parent / f"{out.stem} images"
    cmd = ["pandoc", src.name, "-o", str(out), "--wrap=none",
           "-t", "markdown-simple_tables-multiline_tables-grid_tables-raw_attribute-bracketed_spans-native_spans-link_attributes",
           f"--extract-media={media.name}"]
    code, log = await _run(cmd, src.parent, agent_env(project_root))
    if code != 0 or not out.exists():
        raise BuildError(_friendly_latex_error(log), log[-4000:])
    if media.exists():  # pandoc nests media under ./media; flatten for a tidier project
        inner = media / "media"
        if inner.is_dir():
            text = out.read_text(encoding="utf-8")
            text = text.replace(f"{media.name}/media/", f"{media.name}/")
            out.write_text(text, encoding="utf-8")
            for f in inner.iterdir():
                shutil.move(str(f), str(media / f.name))
            inner.rmdir()
    return out


async def office_preview_pdf(src: Path, project_root: Path) -> Path:
    """Convert an Office document to a cached PDF so the browser can show it."""
    src, project_root = src.resolve(), project_root.resolve()
    if not shutil.which("soffice"):
        raise BuildError("LibreOffice is not installed on the server yet (run scripts/install_deps.sh).")
    st = src.stat()
    key = hashlib.sha1(f"{src}:{st.st_mtime}:{st.st_size}".encode()).hexdigest()[:16]
    cache = TMP / "_previews" / key
    out = cache / (src.stem + ".pdf")
    if out.exists():
        return out
    cache.mkdir(parents=True, exist_ok=True)
    profile = TMP / "_libreoffice-profile"
    cmd = ["soffice", f"-env:UserInstallation=file://{profile}", "--headless", "--norestore",
           "--convert-to", "pdf", "--outdir", str(cache), str(src)]
    async with _lock("soffice"):  # LibreOffice can't run two conversions on one profile
        code, log = await _run(cmd, src.parent, agent_env(project_root), timeout=180)
    if not out.exists():
        raise BuildError("Couldn't create a preview of this document.", log[-3000:])
    return out


def table_preview(src: Path, sheet: Optional[str] = None, limit: int = 300) -> dict:
    import pandas as pd
    ext = src.suffix.lower()
    sheets = None
    if ext in (".csv", ".tsv"):
        df = pd.read_csv(src, sep=None if ext == ".csv" else "\t", engine="python",
                         nrows=limit + 1, encoding_errors="replace")
        total = None
        try:
            with open(src, "rb") as f:
                total = max(0, sum(1 for _ in f) - 1)
        except Exception:
            pass
    else:
        xl = pd.ExcelFile(src)
        sheets = xl.sheet_names
        sheet = sheet if sheet in sheets else sheets[0]
        df = xl.parse(sheet, nrows=limit + 1)
        total = None
    truncated = len(df) > limit
    df = df.head(limit)
    df = df.astype(object).where(df.notna(), None)
    rows = [[None if v is None else str(v) for v in r] for r in df.itertuples(index=False)]
    return {"columns": [str(c) for c in df.columns], "rows": rows, "truncated": truncated,
            "total_rows": total, "sheets": sheets, "sheet": sheet}


def pandoc_version() -> Optional[str]:
    if not shutil.which("pandoc"):
        return None
    try:
        return subprocess.run(["pandoc", "--version"], capture_output=True, text=True, timeout=10).stdout.split("\n")[0]
    except Exception:
        return None


__all__ = ["BuildError", "markdown_to", "tex_to_pdf", "import_to_markdown", "office_preview_pdf",
           "table_preview", "MARKDOWN_EXT", "TEX_EXT", "IMPORTABLE_EXT", "OFFICE_PREVIEW_EXT", "TABLE_EXT", "ROOT"]
