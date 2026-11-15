"""Assistant chats: runs Claude Code (or Antigravity) headlessly inside a project folder,
turns their JSON event streams into a simple message model, saves history per project,
and streams live updates to connected browsers."""
import asyncio
import json
import os
import re
import signal
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import WebSocket

from .config import DATA, PROJECT_META_DIR, ROOT, TMP, VENV, agent_env

INSTRUCTIONS_FILE = Path(__file__).resolve().parent / "agent_instructions.md"
SETTINGS_FILE = DATA / "settings.json"
MAX_CONCURRENT_RUNS = 3
CLAUDE_BIN = os.environ.get("POKOSOMO_CLAUDE_BIN", "claude")
AGY_BIN = os.environ.get("POKOSOMO_AGY_BIN", "agy")
CODEX_BIN = os.environ.get("POKOSOMO_CODEX_BIN", "codex")
TRIM = 2500
# Set in the Docker image (and detectable via /.dockerenv): agents run without their own sandboxes there.
IN_CONTAINER = os.environ.get("IS_SANDBOX") == "1" or Path("/.dockerenv").exists()

DEFAULT_SETTINGS = {
    "engine": "claude",            # "claude" | "agy" | "codex"
    "claude_model": "",            # "" = Claude Code's default; or "opus" / "sonnet" / "haiku"
    "agy_model": "gemini-3.8-flash-high",
    "codex_model": "",             # "" = Codex CLI's configured default
}

CLAUDE_MODELS = [
    {"id": "", "name": "Default (from Claude Code settings)"},
    {"id": "opus", "name": "Opus — most capable"},
    {"id": "sonnet", "name": "Sonnet — fast and capable"},
    {"id": "haiku", "name": "Haiku — fastest, for simple tasks"},
]


def load_settings() -> dict:
    try:
        settings = {**DEFAULT_SETTINGS, **json.loads(SETTINGS_FILE.read_text())}
    except Exception:
        settings = dict(DEFAULT_SETTINGS)
    if settings["engine"] not in ("claude", "agy", "codex"):
        settings["engine"] = "claude"
    return settings


def save_settings(new: dict) -> dict:
    s = load_settings()
    for k in DEFAULT_SETTINGS:
        if k in new and isinstance(new[k], str):
            s[k] = new[k]
    if s["engine"] not in ("claude", "agy", "codex"):
        s["engine"] = "claude"
    SETTINGS_FILE.write_text(json.dumps(s, indent=2))
    return s


def _trim(s: str, n: int = TRIM) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n] + f"\n… ({len(s) - n} more characters)"


def _stringify(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for c in content:
            if isinstance(c, dict):
                if c.get("type") == "text":
                    out.append(c.get("text", ""))
                elif c.get("type") == "image":
                    out.append("[image]")
                else:
                    out.append(json.dumps(c)[:500])
            else:
                out.append(str(c))
        return "\n".join(out)
    return json.dumps(content)[:TRIM]


# --------------------------------------------------------------------------- tool labels
def _rel(path: Optional[str], project_dir: Path) -> Optional[str]:
    if not path:
        return None
    try:
        p = Path(path)
        if not p.is_absolute():
            p = project_dir / p
        return str(p.resolve().relative_to(project_dir.resolve()))
    except Exception:
        return None


def describe_claude_tool(name: str, inp: dict, project_dir: Path) -> dict:
    inp = inp or {}
    fp = inp.get("file_path") or inp.get("notebook_path") or inp.get("path")
    rel = _rel(fp, project_dir)
    shown = rel or (Path(fp).name if fp else "")
    if name == "Read":
        return {"kind": "read", "label": f"Read {shown}", "file": rel}
    if name == "Write":
        return {"kind": "write", "label": f"Wrote {shown}", "file": rel,
                "detail": _trim(inp.get("content", ""), 1500)}
    if name in ("Edit", "MultiEdit", "NotebookEdit"):
        return {"kind": "edit", "label": f"Edited {shown}", "file": rel}
    if name == "Bash":
        desc = inp.get("description") or "Ran a command"
        return {"kind": "run", "label": desc, "detail": _trim(inp.get("command", ""), 1500)}
    if name in ("Glob", "Grep"):
        return {"kind": "search", "label": "Searched the project files", "detail": inp.get("pattern", "")}
    if name == "WebSearch":
        return {"kind": "web", "label": f"Searched the web: {inp.get('query', '')}"}
    if name == "WebFetch":
        return {"kind": "web", "label": "Read a web page", "detail": inp.get("url", "")}
    if name == "TodoWrite":
        todos = inp.get("todos") or []
        return {"kind": "plan", "label": "Updated the plan",
                "todos": [{"text": t.get("content", ""), "status": t.get("status", "")} for t in todos]}
    if name in ("Task", "Agent"):
        return {"kind": "agent", "label": f"Asked a helper: {inp.get('description', '')}".rstrip(": ")}
    if name == "Skill":
        return {"kind": "other", "label": f"Used skill {inp.get('skill', '')}"}
    if name in ("ToolSearch",):
        return {"kind": "other", "label": "Looked up a tool"}
    return {"kind": "other", "label": name.replace("mcp__", "").replace("__", ": "),
            "detail": _trim(json.dumps(inp), 800)}


def _snake(name: str) -> str:
    """CommandLine -> command_line, AbsolutePath -> absolute_path."""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


def _friendly_agy_error(err: str, model: Optional[str]) -> str:
    if "quota" not in err.lower() and "RESOURCE_EXHAUSTED" not in err:
        return err
    m = re.search(r"resets in\s*(?:(\d+)h)?\s*(?:(\d+)m)?\s*(?:(\d+)s)?", err, re.I)
    when = ""
    if m and any(m.groups()):
        h, mi, s = (int(x or 0) for x in m.groups())
        when = " It comes back on " + time.strftime("%A %d %B at %H:%M", time.localtime(time.time() + h * 3600 + mi * 60 + s)) + "."
    name = f"“{model}”" if model else "This model"
    return (f"{name} has used up its allowance on your Google plan.{when}\n\n"
            "Each model has its own allowance, so open Settings, pick a different model "
            "(or switch to Claude), then press “Try again”.")


def describe_agy_step(step_type: str, data: dict, project_dir: Path) -> dict:
    st = (step_type or "step").lower()
    fp = None
    for k in ("absolute_path", "file_path", "path", "target_file", "uri", "file"):
        if isinstance(data.get(k), str):
            fp = data[k]
            break
    rel = _rel(fp.replace("file://", "") if fp else None, project_dir)
    detail = None
    for k in ("command_line", "command", "query", "url", "description", "title"):
        if isinstance(data.get(k), str):
            detail = data[k]
            break
    pretty = st.replace("_", " ")
    if "browser" in st or "web" in st or "url" in st:
        return {"kind": "web", "label": "Used the web", "detail": detail}
    if any(w in st for w in ("view", "read")):
        return {"kind": "read", "label": f"Read {rel or ''}".strip(), "file": rel, "detail": detail}
    if any(w in st for w in ("write", "create")):
        return {"kind": "write", "label": f"Wrote {rel or ''}".strip(), "file": rel, "detail": detail}
    if any(w in st for w in ("edit", "replace")):
        return {"kind": "edit", "label": f"Edited {rel or ''}".strip(), "file": rel, "detail": detail}
    if any(w in st for w in ("command", "run", "shell")):
        return {"kind": "run", "label": "Ran a command", "detail": detail}
    if any(w in st for w in ("search", "grep", "find", "list")):
        return {"kind": "search", "label": "Searched", "detail": detail}
    return {"kind": "other", "label": pretty.capitalize(), "file": rel,
            "detail": detail or _trim(json.dumps(data), 800)}


# --------------------------------------------------------------------------- event adapters
class ClaudeAdapter:
    def __init__(self, msg: dict, chat: dict, project_dir: Path):
        self.msg, self.chat, self.project_dir = msg, chat, project_dir
        self.by_key: dict[str, dict] = {}
        self.by_tool: dict[str, dict] = {}
        # Streamed text parts per API message, in order; the CLI's "assistant" events then
        # repeat each finished block (one block per event), which we match up in the same order.
        self.streamed_text: dict[str, list] = {}
        self.consumed_text: dict[str, int] = {}
        self.finished = False
        self.limit_reset: Optional[float] = None
        self.files_touched = False

    def _new_part(self, part: dict) -> dict:
        self.msg["parts"].append(part)
        return part

    def handle(self, ev: dict):
        t = ev.get("type")
        if ev.get("parent_tool_use_id"):
            return  # events from sub-agents: keep the main conversation tidy
        if t == "system" and ev.get("subtype") == "init":
            self.chat["agent_session"] = ev.get("session_id")
            self.msg["model"] = ev.get("model")
        elif t == "stream_event":
            self._stream(ev)
        elif t == "assistant":
            m = ev.get("message") or {}
            mid = m.get("id")
            for block in m.get("content") or []:
                bt = block.get("type")
                if bt == "text":
                    streamed = self.streamed_text.get(mid, [])
                    n = self.consumed_text.get(mid, 0)
                    if n < len(streamed):
                        part = streamed[n]
                    else:
                        part = self._new_part({"type": "text", "text": ""})
                        self.streamed_text.setdefault(mid, []).append(part)
                    self.consumed_text[mid] = n + 1
                    part["text"] = block.get("text", "")
                elif bt == "tool_use":
                    part = self.by_tool.get(block.get("id"))
                    if part is None:
                        part = self._new_part({"type": "tool", "id": block.get("id"), "status": "running"})
                    part.update(describe_claude_tool(block.get("name", ""), block.get("input") or {}, self.project_dir))
                    part["name"] = block.get("name")
                    self.by_tool[block.get("id")] = part
            self.msg["thinking"] = False
        elif t == "user":
            m = ev.get("message") or {}
            content = m.get("content")
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "tool_result":
                        part = self.by_tool.get(block.get("tool_use_id"))
                        if part is not None:
                            part["status"] = "error" if block.get("is_error") else "done"
                            part["output"] = _trim(_stringify(block.get("content")))
                            if part.get("kind") in ("write", "edit", "run"):
                                self.files_touched = True
        elif t == "rate_limit_event":
            info = ev.get("rate_limit_info") or {}
            if info.get("status") not in (None, "allowed", "allowed_warning"):
                self.limit_reset = info.get("resetsAt")
        elif t == "result":
            self.finished = True
            self.chat["agent_session"] = ev.get("session_id") or self.chat.get("agent_session")
            self.msg["cost_usd"] = ev.get("total_cost_usd")
            self.msg["duration_s"] = round((ev.get("duration_ms") or 0) / 1000, 1)
            if ev.get("is_error") or (ev.get("subtype") or "success") != "success":
                err = ev.get("result") or ev.get("subtype") or "The assistant ran into a problem."
                if self.limit_reset:
                    err = f"Usage limit reached. It resets at {time.strftime('%H:%M on %b %d', time.localtime(self.limit_reset))}.\n\n{err}"
                self.msg["error"] = str(err)[:2000]
                self.msg["status"] = "error"
            else:
                self.msg["status"] = "done"
                if not any(p["type"] == "text" and p["text"].strip() for p in self.msg["parts"]) and ev.get("result"):
                    self._new_part({"type": "text", "text": ev["result"]})

    def _stream(self, ev: dict):
        e = ev.get("event") or {}
        et = e.get("type")
        key = f"{ev.get('api_message_id')}:{e.get('index')}"
        if et == "content_block_start":
            block = e.get("content_block") or {}
            bt = block.get("type")
            if bt == "text":
                part = self.by_key[key] = self._new_part({"type": "text", "text": block.get("text", "")})
                self.streamed_text.setdefault(ev.get("api_message_id"), []).append(part)
            elif bt == "tool_use":
                part = self._new_part({"type": "tool", "id": block.get("id"), "name": block.get("name"),
                                       "status": "running", "kind": "other",
                                       **describe_claude_tool(block.get("name", ""), {}, self.project_dir)})
                self.by_key[key] = part
                self.by_tool[block.get("id")] = part
            elif bt in ("thinking", "redacted_thinking"):
                self.msg["thinking"] = True
        elif et == "content_block_delta":
            d = e.get("delta") or {}
            if d.get("type") == "text_delta":
                part = self.by_key.get(key)
                if part is not None and part["type"] == "text":
                    part["text"] += d.get("text", "")
        elif et == "content_block_stop":
            self.msg["thinking"] = False


class AgyAdapter:
    def __init__(self, msg: dict, chat: dict, project_dir: Path):
        self.msg, self.chat, self.project_dir = msg, chat, project_dir
        self.steps: dict[int, dict] = {}
        self.finished = False
        self.files_touched = False

    def handle(self, ev: dict):
        kind = ev.get("event")
        if kind == "init":
            self.chat["agent_session"] = ev.get("conversation_id")
            self.msg["model"] = (ev.get("init") or {}).get("model")
        elif kind == "step_update":
            su = ev.get("step_update") or {}
            st = su.get("step_type", "")
            idx = su.get("step_index", -1)
            state = (su.get("state") or "").upper()
            if st == "user_input":
                return
            if "text_delta" in su and ("response" in st or st in ("text", "message")):
                part = self.steps.get(idx)
                if part is None:
                    part = self.steps[idx] = {"type": "text", "text": ""}
                    self.msg["parts"].append(part)
                part["text"] += su.get("text_delta") or ""
                return
            if "think" in st:
                self.msg["thinking"] = state == "ACTIVE"
                return
            if "response" in st or st in ("system_message", "error_message", "text", "message"):
                return  # bookkeeping steps without text; the final error arrives with "result"
            data = {k: v for k, v in su.items() if k not in
                    ("conversation_id", "step_index", "state", "step_type", "usage", "duration_seconds", "text_delta")}
            if st == "tool" and isinstance(su.get("tool_info"), dict):
                # {"tool_name": "run_command", "tool_info": {"parameters": {"CommandLine": ...}, "output": ...}}
                info = su["tool_info"]
                st = su.get("tool_name") or info.get("name") or st
                params = info.get("parameters") if isinstance(info.get("parameters"), dict) else {}
                data = {_snake(k): v for k, v in params.items()}
                if info.get("output"):
                    data["output"] = info["output"]
            part = self.steps.get(idx)
            if part is None:
                part = self.steps[idx] = {"type": "tool", "id": f"step-{idx}", "name": st, "status": "running"}
                self.msg["parts"].append(part)
            desc = describe_agy_step(st, data, self.project_dir)
            for k, v in desc.items():
                if v or k not in part:
                    part[k] = v
            if state in ("DONE", "COMPLETED", "SUCCESS"):
                part["status"] = "done"
                if part.get("kind") in ("write", "edit", "run"):
                    self.files_touched = True
            elif state in ("ERROR", "FAILED", "CANCELED", "CANCELLED"):
                part["status"] = "error"
            out = data.get("output") or data.get("result") or data.get("stdout")
            if out:
                part["output"] = _trim(_stringify(out))
        elif kind == "result":
            self.finished = True
            r = ev.get("result") or {}
            self.chat["agent_session"] = r.get("conversation_id") or self.chat.get("agent_session")
            self.msg["duration_s"] = round(r.get("duration_seconds") or 0, 1)
            if (r.get("status") or "").upper() == "SUCCESS":
                self.msg["status"] = "done"
                if not any(p["type"] == "text" and p["text"].strip() for p in self.msg["parts"]) and r.get("response"):
                    self.msg["parts"].append({"type": "text", "text": r["response"]})
            else:
                self.msg["status"] = "error"
                err = str(r.get("error") or r.get("response") or r.get("status") or "The assistant ran into a problem.")
                self.msg["error"] = _friendly_agy_error(err, self.chat.get("model"))[:2000]
        elif kind == "error":
            self.msg["error"] = str(ev.get("error") or ev)[:2000]


class CodexAdapter:
    def __init__(self, msg: dict, chat: dict, project_dir: Path):
        self.msg, self.chat, self.project_dir = msg, chat, project_dir
        self.parts: dict[str, dict] = {}
        self.files_touched = False

    def _part(self, item_id: str) -> dict:
        if item_id not in self.parts:
            part = {"type": "tool", "id": item_id, "status": "running"}
            self.msg["parts"].append(part)
            self.parts[item_id] = part
        return self.parts[item_id]

    def handle(self, ev: dict):
        kind = ev.get("type")
        if kind == "thread.started":
            self.chat["agent_session"] = ev.get("thread_id")
        elif kind == "turn.started":
            self.msg["thinking"] = True
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = ev.get("item") or {}
            item_type = item.get("type")
            item_id = str(item.get("id") or f"item-{len(self.parts)}")
            if item_type == "agent_message":
                part = self.parts.get(item_id)
                if part is None:
                    part = {"type": "text", "text": ""}
                    self.parts[item_id] = part
                    self.msg["parts"].append(part)
                if isinstance(item.get("text"), str):
                    part["text"] = item["text"]
                elif isinstance(ev.get("delta"), str):
                    part["text"] += ev["delta"]
                self.msg["thinking"] = False
                return
            if item_type == "reasoning":
                self.msg["thinking"] = kind != "item.completed"
                return

            changes = item.get("changes") if item_type == "file_change" else None
            if not isinstance(changes, list):
                changes = None
            for index, change in enumerate(changes or [None]):
                part = self._part(f"{item_id}:{index}" if changes else item_id)
                if item_type == "command_execution":
                    command = item.get("command") or "command"
                    part.update({"name": "Command", "kind": "run", "label": "Ran a command",
                                 "detail": _trim(_stringify(command), 1500)})
                    output = item.get("aggregated_output") or item.get("output")
                    if output:
                        part["output"] = _trim(_stringify(output))
                elif item_type == "file_change":
                    change = change if isinstance(change, dict) else {}
                    path = str(change.get("path") or "a project file")
                    action = {"add": "Created", "delete": "Deleted"}.get(change.get("kind"), "Edited")
                    relative = _rel(path, self.project_dir)
                    part.update({"name": "File change", "kind": "edit", "file": relative,
                                 "label": f"{action} {relative or Path(path).name}"})
                elif item_type == "web_search":
                    part.update({"name": "Web search", "kind": "web", "label": "Searched the web",
                                 "detail": _trim(_stringify(item.get("query") or item.get("search_query") or ""), 800)})
                elif item_type == "mcp_tool_call":
                    name = item.get("tool") or item.get("name") or "Tool"
                    part.update({"name": str(name), "kind": "other", "label": f"Used {name}"})
                else:
                    label = str(item_type or "Activity").replace("_", " ").capitalize()
                    part.update({"name": str(item_type or "Activity"), "kind": "other", "label": label})

                status = item.get("status")
                if kind == "item.completed" or status in ("completed", "failed", "cancelled"):
                    part["status"] = "error" if status in ("failed", "cancelled") else "done"
                    if item_type in ("file_change", "command_execution"):
                        self.files_touched = True
                    self.msg["thinking"] = False
                else:
                    part["status"] = "running"
        elif kind == "turn.completed":
            self.msg["thinking"] = False
            self.msg["status"] = "done"
        elif kind == "turn.failed":
            self.msg["thinking"] = False
            error = ev.get("error") or {}
            if isinstance(error, dict):
                error = error.get("message") or error
            self.msg["error"] = str(error or "Codex could not complete this request.")[:2000]
            self.msg["status"] = "error"
        elif kind == "error":
            self.msg["error"] = str(ev.get("message") or ev.get("error") or ev)[:2000]


# --------------------------------------------------------------------------- manager
class ChatRun:
    def __init__(self, proc: asyncio.subprocess.Process):
        self.proc = proc
        self.stopped = False

    def stop(self):
        self.stopped = True
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return
        async def _force():
            await asyncio.sleep(4)
            if self.proc.returncode is None:
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        asyncio.create_task(_force())


class ChatManager:
    def __init__(self):
        self.runs: dict[tuple, ChatRun] = {}
        self.subs: dict[tuple, set] = {}
        self._dirty_at: dict[tuple, float] = {}
        self._flush_pending: set = set()

    # ---- storage
    @staticmethod
    def _dir(project_dir: Path) -> Path:
        d = project_dir / PROJECT_META_DIR / "chats"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _path(self, project_dir: Path, chat_id: str) -> Path:
        if not chat_id or not all(c.isalnum() or c == "-" for c in chat_id):
            raise FileNotFoundError("Chat not found")
        return self._dir(project_dir) / f"{chat_id}.json"

    def _save(self, project_dir: Path, chat: dict):
        p = self._path(project_dir, chat["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(chat))
        tmp.replace(p)

    def load(self, project_dir: Path, chat_id: str) -> dict:
        p = self._path(project_dir, chat_id)
        if not p.exists():
            raise FileNotFoundError("Chat not found")
        chat = json.loads(p.read_text())
        key = (str(project_dir), chat_id)
        if key not in self.runs:
            changed = False
            for m in chat["messages"]:
                if m.get("role") == "assistant" and m.get("status") == "running":
                    m["status"] = "stopped"
                    m["error"] = "Interrupted (the studio was restarted)."
                    changed = True
            if changed:
                self._save(project_dir, chat)
        chat["running"] = key in self.runs
        return chat

    def list(self, project_dir: Path) -> list:
        out = []
        for p in self._dir(project_dir).glob("*.json"):
            try:
                c = json.loads(p.read_text())
            except Exception:
                continue
            out.append({"id": c["id"], "title": c.get("title") or "New chat", "updated": c.get("updated", 0),
                        "engine": c.get("engine"), "running": (str(project_dir), c["id"]) in self.runs})
        out.sort(key=lambda c: -c["updated"])
        return out

    def create(self, project_dir: Path) -> dict:
        s = load_settings()
        engine = s["engine"]
        chat = {
            "id": uuid.uuid4().hex[:12],
            "title": "",
            "engine": engine,
            "model": {"claude": s["claude_model"], "agy": s["agy_model"],
                      "codex": s["codex_model"]}[engine],
            "agent_session": None,
            "created": time.time(),
            "updated": time.time(),
            "messages": [],
        }
        self._save(project_dir, chat)
        return chat

    def delete(self, project_dir: Path, chat_id: str):
        key = (str(project_dir), chat_id)
        if key in self.runs:
            self.runs[key].stop()
        p = self._path(project_dir, chat_id)
        if p.exists():
            p.unlink()

    # ---- live updates
    async def subscribe(self, project_dir: Path, chat_id: str, ws: WebSocket):
        self.subs.setdefault((str(project_dir), chat_id), set()).add(ws)

    def unsubscribe(self, project_dir: Path, chat_id: str, ws: WebSocket):
        self.subs.get((str(project_dir), chat_id), set()).discard(ws)

    async def _broadcast(self, key: tuple, payload: dict):
        dead = []
        for ws in list(self.subs.get(key, ())):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.subs.get(key, set()).discard(ws)

    def _schedule_update(self, key: tuple, msg: dict):
        if key in self._flush_pending:
            return
        self._flush_pending.add(key)

        async def flush():
            await asyncio.sleep(0.12)
            self._flush_pending.discard(key)
            await self._broadcast(key, {"type": "update", "message": msg})
        asyncio.create_task(flush())

    # ---- running
    def _instructions(self, project_dir: Path, context: str = "") -> str:
        text = INSTRUCTIONS_FILE.read_text()
        values = {"project_dir": project_dir, "studio_dir": ROOT, "tmp_dir": TMP / project_dir.name,
                  "venv": VENV, "context": context}
        for k, v in values.items():  # plain replace: the text contains LaTeX braces
            text = text.replace("{" + k + "}", str(v))
        return text

    def _command(self, chat: dict, project_dir: Path, prompt: str) -> list:
        if chat["engine"] == "agy":
            # agy's -p/--print takes the prompt as its value (unlike Claude's boolean -p, which
            # reads stdin). The attached "=" form stays unambiguous even if the text starts with "-".
            cmd = [AGY_BIN, "--output-format", "stream-json", "--dangerously-skip-permissions"]
            if chat.get("model"):
                cmd += ["--model", chat["model"]]
            if chat.get("agent_session"):
                cmd += ["--conversation", chat["agent_session"]]
            return cmd + [f"--print={prompt}"]
        if chat["engine"] == "codex":
            cmd = [CODEX_BIN, "exec"]
            if chat.get("agent_session"):
                cmd += ["resume", chat["agent_session"]]
            # `codex exec resume` accepts neither --sandbox nor --cd/--add-dir, so settings go through -c
            # (valid for both forms) and the project folder is the process's working directory.
            cmd += ["--json", "--skip-git-repo-check"]
            if IN_CONTAINER:
                # Codex's own sandbox (bubblewrap) cannot create namespaces inside Docker, so every
                # command would fail. The container is the isolation boundary, as for Claude and agy.
                cmd += ["--dangerously-bypass-approvals-and-sandbox"]
            else:
                tmp_dir = json.dumps(str(TMP / project_dir.name))
                cmd += ["-c", 'approval_policy="never"', "-c", 'sandbox_mode="workspace-write"',
                        "-c", f"sandbox_workspace_write.writable_roots=[{tmp_dir}]",
                        "-c", "sandbox_workspace_write.network_access=true"]
            if chat.get("model"):
                cmd += ["--model", chat["model"]]
            return cmd + [prompt]
        cmd = [CLAUDE_BIN, "-p", "--output-format", "stream-json", "--verbose", "--include-partial-messages",
               "--dangerously-skip-permissions",
               "--append-system-prompt", self._instructions(project_dir),
               "--disallowedTools", "AskUserQuestion"]
        if chat.get("model"):
            cmd += ["--model", chat["model"]]
        if chat.get("agent_session"):
            cmd += ["--resume", chat["agent_session"]]
        return cmd

    async def send(self, project_dir: Path, chat_id: str, text: str, open_file: Optional[str] = None) -> dict:
        key = (str(project_dir), chat_id)
        if key in self.runs:
            raise RuntimeError("The assistant is still working on the previous message.")
        if len(self.runs) >= MAX_CONCURRENT_RUNS:
            raise RuntimeError("Several assistants are already working. Please wait for one to finish.")
        chat = self.load(project_dir, chat_id)
        text = text.strip()
        if not text:
            raise ValueError("Message is empty.")

        user_msg = {"id": uuid.uuid4().hex[:10], "role": "user", "text": text, "ts": time.time()}
        if open_file:
            user_msg["open_file"] = open_file
        asst = {"id": uuid.uuid4().hex[:10], "role": "assistant", "ts": time.time(), "status": "running",
                "parts": [], "thinking": False}
        chat["messages"] += [user_msg, asst]
        if not chat.get("title"):
            first = text.splitlines()[0]
            chat["title"] = first[:60] + ("…" if len(first) > 60 else "")
        chat["updated"] = time.time()

        prompt = text
        if open_file:
            prompt += f"\n\n(For context: I currently have the file `{open_file}` open in the studio.)"
        if chat["engine"] == "agy" and not chat.get("agent_session"):
            prompt = f"<studio_instructions>\n{self._instructions(project_dir)}\n</studio_instructions>\n\n{prompt}"
        elif chat["engine"] == "codex" and not chat.get("agent_session"):
            prompt = f"<studio_instructions>\n{self._instructions(project_dir)}\n</studio_instructions>\n\n{prompt}"

        cmd = self._command(chat, project_dir, prompt)
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd, cwd=str(project_dir), env=agent_env(project_dir),
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                start_new_session=True, limit=64 * 1024 * 1024,
            )
        except FileNotFoundError:
            asst["status"] = "error"
            asst["error"] = f"The assistant program ({cmd[0]}) is not installed."
            self._save(project_dir, chat)
            return chat
        run = ChatRun(proc)
        self.runs[key] = run
        self._save(project_dir, chat)
        chat_out = dict(chat, running=True)
        await self._broadcast(key, {"type": "chat", "chat": chat_out})
        asyncio.create_task(self._pump(project_dir, chat, asst, run, prompt))
        return chat_out

    async def _pump(self, project_dir: Path, chat: dict, msg: dict, run: ChatRun, prompt: str):
        key = (str(project_dir), chat["id"])
        adapter_type = {"agy": AgyAdapter, "claude": ClaudeAdapter, "codex": CodexAdapter}[chat["engine"]]
        adapter = adapter_type(msg, chat, project_dir)
        proc = run.proc
        stderr_tail = bytearray()

        async def read_stderr():
            while True:
                chunk = await proc.stderr.read(4096)
                if not chunk:
                    break
                stderr_tail.extend(chunk)
                del stderr_tail[:-8000]
        err_task = asyncio.create_task(read_stderr())

        try:
            if chat["engine"] == "claude":  # Claude reads its prompt from stdin.
                proc.stdin.write(prompt.encode())
                await proc.stdin.drain()
            proc.stdin.close()
        except Exception:
            pass

        last_save = time.time()
        files_signal_at = 0.0
        try:
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                line = line.strip()
                if not line.startswith(b"{"):
                    continue
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                try:
                    adapter.handle(ev)
                except Exception as e:  # never let an odd event kill the stream
                    print(f"[chat] adapter error: {e!r}")
                self._schedule_update(key, msg)
                if adapter.files_touched and time.time() - files_signal_at > 1.5:
                    adapter.files_touched = False
                    files_signal_at = time.time()
                    await self._broadcast(key, {"type": "files_changed"})
                if time.time() - last_save > 3:
                    self._save(project_dir, chat)
                    last_save = time.time()
        finally:
            await proc.wait()
            await err_task
            self.runs.pop(key, None)
            msg["thinking"] = False
            for p in msg["parts"]:
                if p.get("type") == "tool" and p.get("status") == "running":
                    p["status"] = "stopped" if run.stopped else "done"
            if "no conversation found" in (msg.get("error") or "").lower() + stderr_tail.decode("utf-8", "replace").lower():
                # Claude keeps sessions per folder; after a project rename the old one can't be resumed.
                chat["agent_session"] = None
                msg["status"] = "error"
                msg["error"] = ("The earlier conversation couldn't be continued (was the project renamed?). "
                                "Press “Try again” — the assistant will start fresh in this chat.")
            elif run.stopped:
                msg["status"] = "stopped"
            elif msg["status"] == "running":
                msg["status"] = "error"
                tail = stderr_tail.decode("utf-8", "replace").strip()
                msg["error"] = msg.get("error") or (tail[-1500:] if tail else f"The assistant stopped unexpectedly (exit code {proc.returncode}).")
            chat["updated"] = time.time()
            self._save(project_dir, chat)
            await self._broadcast(key, {"type": "update", "message": msg})
            await self._broadcast(key, {"type": "run_end", "status": msg["status"]})
            await self._broadcast(key, {"type": "files_changed"})

    def stop(self, project_dir: Path, chat_id: str):
        run = self.runs.get((str(project_dir), chat_id))
        if run:
            run.stop()


chat_manager = ChatManager()
