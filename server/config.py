"""Central paths and environment for the studio."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = ROOT / "workspace"      # one sub-folder per project
TMP = ROOT / "tmp"                  # scratch space for agents and document builds
DATA = Path(os.environ.get("POKOSOMO_DATA", ROOT / "data"))  # sessions, settings (git-ignored)
STATIC = ROOT / "static"
SECRETS_FILE = Path(os.environ.get("POKOSOMO_SECRETS", ROOT / "secrets.json"))

VENV = Path(os.environ.get("POKOSOMO_VENV", ROOT / ".venv"))
HOME = Path(os.path.expanduser("~"))

for _d in (WORKSPACE, TMP, DATA):
    _d.mkdir(parents=True, exist_ok=True)

# Hidden per-project folder for studio metadata (chat history etc.)
PROJECT_META_DIR = ".studio"
TRASH_DIR = WORKSPACE / ".trash"


def tool_path() -> str:
    extra = [
        str(HOME / ".gemini/antigravity-cli/bin"),
        str(HOME / ".local/bin"),
        str(VENV / "bin"),
        "/usr/local/bin", "/usr/bin", "/bin", "/usr/local/sbin", "/usr/sbin", "/sbin",
    ]
    current = os.environ.get("PATH", "").split(os.pathsep)
    seen, out = set(), []
    for p in extra + current:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return os.pathsep.join(out)


def agent_env(project_dir: Path) -> dict:
    """Environment for agents, terminals and document builds started inside a project."""
    tmp = TMP / project_dir.name
    tmp.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env.update({
        "PATH": tool_path(),
        "HOME": str(HOME),
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "TMPDIR": str(tmp),
        "VIRTUAL_ENV": str(VENV),
        "MPLBACKEND": "Agg",          # matplotlib: never try to open a window
        "PYTHONUNBUFFERED": "1",
        "POKOSOMO_PROJECT_DIR": str(project_dir),
    })
    # Don't leak the studio's own session/debug state into child agents.
    for k in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT"):
        env.pop(k, None)
    return env
