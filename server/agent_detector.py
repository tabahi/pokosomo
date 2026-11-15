import os
import json
import shutil
import subprocess
import re
import time
from typing import Any, Dict, List, Optional

from .config import tool_path

# Used when `agy models` can't be read (not signed in, offline, or an output format we don't recognise).
AGY_FALLBACK_MODELS = [
        {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
        {"id": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)"},
        {"id": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)"},
        {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)"},
        {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)"},
        {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"}
]
_AGY_MODEL_ID = re.compile(r"\b[a-z0-9][a-z0-9._]*(?:-[a-z0-9._]+)+\b")
_agy_cache: Dict[str, Any] = {"at": 0.0, "models": None}


def parse_agy_models(out: str) -> List[Dict[str, str]]:
    """Read the list printed by `agy models` (after its "Available models:" line).
    Accepts lines like "gemini-3.8-flash-high  Gemini 3.8 Flash (High)", "Name (id)", "- id: Name" or a bare id."""
    lines = out.splitlines()
    for i, line in enumerate(lines):
        if line.strip().lower().startswith("available models"):
            lines = lines[i + 1:]
            break
    models, seen = [], set()
    for raw in lines:
        line = raw.strip().lstrip("-*•>").strip()
        if not line or line.lower().startswith(("fetching", "error", "no models")):
            continue
        m = _AGY_MODEL_ID.search(line)
        if not m or m.group(0) in seen:
            continue
        mid = m.group(0)
        name = (line[:m.start()] + " " + line[m.end():]).strip()
        name = re.sub(r"^[\s:|()\[\]=-]+|[\s:|(\[=-]+$", "", name)
        name = re.sub(r"\(\s*\)|\[\s*\]", "", name).strip()
        if name.startswith("(") and not name.endswith(")"):
            name = name[1:].strip()
        models.append({"id": mid, "name": name or mid})
        seen.add(mid)
    return models


def _agy_models(agy_which: Optional[str], signed_in: bool) -> List[Dict[str, str]]:
    """The models this account can use, from `agy models` (cached for 10 minutes)."""
    if not (agy_which and signed_in):
        return AGY_FALLBACK_MODELS
    now = time.time()
    if _agy_cache["models"] and now - _agy_cache["at"] < 600:
        return _agy_cache["models"]
    models: List[Dict[str, str]] = []
    try:
        env = dict(os.environ, PATH=tool_path())
        out = subprocess.run([agy_which, "models"], capture_output=True, text=True, timeout=20,
                             stdin=subprocess.DEVNULL, env=env)
        models = parse_agy_models(out.stdout + "\n" + out.stderr)
    except Exception:
        pass
    _agy_cache.update(at=now, models=models or None)
    return models or AGY_FALLBACK_MODELS



_codex_cache: Dict[str, Any] = {"at": 0.0, "models": None}


def parse_codex_models(out: str) -> List[Dict[str, str]]:
    """Models from `codex debug models` (JSON catalog): the visible ones, in Codex's own order."""
    try:
        catalog = json.loads(out[out.index("{"):])
    except ValueError:
        return []
    listed = [m for m in catalog.get("models") or []
              if isinstance(m, dict) and m.get("slug") and m.get("visibility", "list") == "list"]
    listed.sort(key=lambda m: m.get("priority", 999))
    models = []
    for m in listed:
        name = m.get("display_name") or m["slug"]
        if m.get("description"):
            name += " — " + m["description"].rstrip(".")
        models.append({"id": m["slug"], "name": name})
    return models


def _codex_models(codex_which: Optional[str]) -> List[Dict[str, str]]:
    """Default first, then the catalog (cached for 10 minutes). Works without signing in."""
    default = [{"id": "", "name": "Default (from Codex settings)"}]
    if not codex_which:
        return default
    now = time.time()
    if _codex_cache["models"] is None or now - _codex_cache["at"] > 600:
        models: List[Dict[str, str]] = []
        try:
            out = subprocess.run([codex_which, "debug", "models"], capture_output=True, text=True, timeout=15,
                                 stdin=subprocess.DEVNULL, env=dict(os.environ, PATH=tool_path()))
            models = parse_codex_models(out.stdout)
        except Exception:
            pass
        _codex_cache.update(at=now, models=models)
    return default + _codex_cache["models"]


def get_agents_status() -> Dict[str, Any]:
    """Inspect and return current status of all supported coding agents and tools."""
    # 1. Claude Code
    claude_which = shutil.which(os.environ.get("POKOSOMO_CLAUDE_BIN", "claude"), path=tool_path())
    claude_info: Dict[str, Any] = {
        "installed": bool(claude_which),
        "path": claude_which,
        "version": None,
        "auth": None,
    }
    if claude_which:
        try:
            ver = subprocess.check_output([claude_which, "--version"], timeout=4).decode().strip()
            claude_info["version"] = ver
        except Exception:
            pass

        try:
            out = subprocess.check_output([claude_which, "auth", "status"], stderr=subprocess.STDOUT, timeout=5).decode()
            start = out.find("{")
            end = out.rfind("}")
            if start != -1 and end != -1:
                claude_info["auth"] = json.loads(out[start:end+1])
        except Exception as e:
            claude_info["auth_error"] = str(e)

    # 2. Antigravity (agy). Its installer puts the binary in ~/.local/bin, which may not be on the
    # server's own PATH, so look it up on the same PATH the agents get.
    agy_which = shutil.which(os.environ.get("POKOSOMO_AGY_BIN", "agy"), path=tool_path())
    agy_installed = bool(agy_which)

    token_file = os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token")
    has_agy_token = os.path.isfile(token_file) and os.path.getsize(token_file) > 0
    agy_ver = None
    if agy_installed:
        try:
            agy_ver = subprocess.check_output([agy_which, "--version"], timeout=5,
                                              stderr=subprocess.STDOUT).decode().strip()
        except Exception:
            pass

    agy_info = {
        "installed": agy_installed,
        "path": agy_which,
        "version": agy_ver,
        "authenticated": has_agy_token,
        "account_type": "Google Account (Antigravity OAuth)",
        "models": _agy_models(agy_which, has_agy_token),
        "modes": [
            {"id": "auto", "name": "Auto (Interactive edits & commands)"},
            {"id": "plan", "name": "Plan (Research & propose plan first)"},
            {"id": "accept-edits", "name": "Accept Edits (Automatically accept file changes)"}
        ]
    }

    # 3. Codex CLI
    codex_which = shutil.which(os.environ.get("POKOSOMO_CODEX_BIN", "codex"), path=tool_path())
    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    codex_auth_file = os.path.join(codex_home, "auth.json")
    codex_info: Dict[str, Any] = {
        "installed": bool(codex_which),
        "path": codex_which,
        "version": None,
        "authenticated": (os.path.isfile(codex_auth_file) and os.path.getsize(codex_auth_file) > 0)
                         or bool(os.environ.get("CODEX_API_KEY")),
    }
    codex_info["models"] = _codex_models(codex_which)
    if codex_which:
        try:
            out = subprocess.check_output([codex_which, "--version"], timeout=4, stderr=subprocess.DEVNULL)
            codex_info["version"] = (out.decode().strip().splitlines() or [None])[-1]
        except Exception:
            pass

    # 4. System Environment
    system_info = {
        "node": shutil.which("node"),
        "python": shutil.which("python3"),
        "git": shutil.which("git"),
    }

    return {
        "agy": agy_info,
        "claude": claude_info,
        "codex": codex_info,
        "system": system_info
    }
