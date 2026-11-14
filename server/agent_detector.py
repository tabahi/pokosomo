import os
import json
import shutil
import subprocess
from typing import Dict, Any

def get_agents_status() -> Dict[str, Any]:
    """Inspect and return current status of all supported coding agents and tools."""
    # 1. Claude Code
    claude_which = shutil.which("claude")
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

    # 2. Antigravity (agy)
    agy_which = shutil.which("agy") or "/home/dev/.local/bin/agy"
    if not os.path.exists(agy_which) and not shutil.which("agy"):
        agy_installed = False
    else:
        agy_installed = True

    token_file = os.path.expanduser("~/.gemini/antigravity-cli/antigravity-oauth-token")
    has_agy_token = os.path.exists(token_file) and os.path.getsize(token_file) > 0
    agy_ver = "1.5.6"
    if agy_installed:
        try:
            agy_ver = subprocess.check_output([agy_which, "--version"], timeout=3).decode().strip()
        except Exception:
            pass

    agy_info = {
        "installed": agy_installed,
        "path": agy_which if agy_installed else None,
        "version": agy_ver,
        "authenticated": has_agy_token,
        "account_type": "Google Account (Antigravity OAuth)",
        "models": [
            {"id": "gemini-3.8-flash-high", "name": "Gemini 3.8 Flash (High)"},
            {"id": "gemini-3.8-flash-medium", "name": "Gemini 3.8 Flash (Medium)"},
            {"id": "gemini-3.8-flash-low", "name": "Gemini 3.8 Flash (Low)"},
            {"id": "claude-sonnet-4-6", "name": "Claude Sonnet 4.6 (Thinking)"},
            {"id": "claude-opus-4-6-thinking", "name": "Claude Opus 4.6 (Thinking)"},
            {"id": "gpt-oss-120b-medium", "name": "GPT-OSS 120B (Medium)"}
        ],
        "modes": [
            {"id": "auto", "name": "Auto (Interactive edits & commands)"},
            {"id": "plan", "name": "Plan (Research & propose plan first)"},
            {"id": "accept-edits", "name": "Accept Edits (Automatically accept file changes)"}
        ]
    }

    # 3. Codex CLI
    codex_which = shutil.which("codex")
    if not codex_which:
        candidate = os.path.expanduser("~/.local/bin/codex")
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            codex_which = candidate
    codex_home = os.environ.get("CODEX_HOME", os.path.expanduser("~/.codex"))
    codex_auth_file = os.path.join(codex_home, "auth.json")
    codex_info: Dict[str, Any] = {
        "installed": bool(codex_which),
        "path": codex_which,
        "version": None,
        "authenticated": (os.path.isfile(codex_auth_file) and os.path.getsize(codex_auth_file) > 0)
                         or bool(os.environ.get("CODEX_API_KEY")),
    }
    if codex_which:
        try:
            codex_info["version"] = subprocess.check_output(
                [codex_which, "--version"], timeout=4, stderr=subprocess.STDOUT
            ).decode().strip()
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
