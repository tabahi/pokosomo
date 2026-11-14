import json
from pathlib import Path
from typing import List, Optional

from fastapi import FastAPI, File, Form, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, documents
from .agent_detector import get_agents_status
from .chat_manager import CLAUDE_MODELS, chat_manager, load_settings, save_settings
from .config import STATIC, agent_env
from .terminal_manager import TerminalManager
from .workspace_manager import (ProjectFiles, create_project, delete_project, list_projects,
                                project_dir, rename_project)

app = FastAPI(title="Pokosomo Studio", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(auth.AuthMiddleware)
terminal_mgr = TerminalManager()


def _err(e: Exception):
    if isinstance(e, HTTPException):
        raise e
    if isinstance(e, documents.BuildError):
        raise HTTPException(422, detail={"message": e.message, "log": e.log})
    code = {FileNotFoundError: 404, FileExistsError: 409, PermissionError: 403,
            IsADirectoryError: 400, NotADirectoryError: 400, ValueError: 400, RuntimeError: 409}
    for cls, status in code.items():
        if isinstance(e, cls):
            raise HTTPException(status, detail=str(e))
    raise HTTPException(500, detail=f"Something went wrong: {e}")


def _project(name: str) -> Path:
    try:
        return project_dir(name)
    except Exception as e:
        _err(e)


def _files(name: str) -> ProjectFiles:
    return ProjectFiles(_project(name))


# =========================================================================== auth
class LoginRequest(BaseModel):
    password: str
    code: str
    remember: bool = False


@app.get("/login")
async def login_page(request: Request):
    if auth.sessions.validate(auth.token_from_scope(request.scope)):
        return Response(status_code=302, headers={"location": "/"})
    return FileResponse(STATIC / "login.html")


@app.get("/api/auth/state")
async def auth_state(request: Request):
    return {"configured": auth.login_config() is not None,
            "signed_in": auth.sessions.validate(auth.token_from_scope(request.scope))}


@app.post("/api/auth/login")
async def login(req: LoginRequest, request: Request):
    ok, message, token = await auth.attempt_login(request.scope, req.password, req.code, req.remember)
    if not ok:
        return JSONResponse({"detail": message}, status_code=401)
    resp = JSONResponse({"ok": True})
    resp.headers.append("set-cookie", auth.session_cookie_header(token, req.remember, auth.is_https(request.scope)))
    return resp


@app.post("/api/auth/logout")
async def logout(request: Request):
    auth.sessions.revoke(auth.token_from_scope(request.scope))
    resp = JSONResponse({"ok": True})
    resp.headers.append("set-cookie", auth.clear_cookie_header(auth.is_https(request.scope)))
    return resp


@app.post("/api/auth/logout-all")
async def logout_all(request: Request):
    auth.sessions.revoke_all()
    resp = JSONResponse({"ok": True})
    resp.headers.append("set-cookie", auth.clear_cookie_header(auth.is_https(request.scope)))
    return resp


# =========================================================================== settings
@app.get("/api/settings")
async def get_settings():
    return {"settings": load_settings(), "claude_models": CLAUDE_MODELS}


@app.put("/api/settings")
async def put_settings(body: dict):
    return {"settings": save_settings(body)}


@app.get("/api/agents")
async def get_agents():
    import asyncio
    return await asyncio.to_thread(get_agents_status)


# =========================================================================== projects
class NameRequest(BaseModel):
    name: str


@app.get("/api/projects")
async def api_list_projects():
    return list_projects()


@app.post("/api/projects")
async def api_create_project(req: NameRequest):
    try:
        return create_project(req.name)
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/rename")
async def api_rename_project(name: str, req: NameRequest):
    try:
        return rename_project(name, req.name)
    except Exception as e:
        _err(e)


@app.delete("/api/projects/{name}")
async def api_delete_project(name: str):
    try:
        return delete_project(name)
    except Exception as e:
        _err(e)


# =========================================================================== files
class SaveRequest(BaseModel):
    path: str
    content: str
    expected_mtime: Optional[float] = None


class CreateRequest(BaseModel):
    path: str
    kind: str = "file"
    content: str = ""


class RenameRequest(BaseModel):
    path: str
    new_name: str


class MoveRequest(BaseModel):
    path: str
    dest_dir: str


class PathRequest(BaseModel):
    path: str
    format: Optional[str] = None


@app.get("/api/projects/{name}/tree")
async def api_tree(name: str):
    try:
        return _files(name).tree()
    except Exception as e:
        _err(e)


@app.get("/api/projects/{name}/file")
async def api_read(name: str, path: str = Query(...)):
    try:
        return _files(name).read_text(path)
    except Exception as e:
        _err(e)


@app.get("/api/projects/{name}/stat")
async def api_stat(name: str, path: str = Query(...)):
    try:
        p = _files(name).resolve(path, must_exist=True)
        st = p.stat()
        return {"mtime": st.st_mtime, "size": st.st_size}
    except Exception as e:
        _err(e)


@app.put("/api/projects/{name}/file")
async def api_save(name: str, req: SaveRequest):
    try:
        return _files(name).write_text(req.path, req.content, req.expected_mtime)
    except FileExistsError as e:
        if str(e) == "changed-on-disk":
            raise HTTPException(409, detail="changed-on-disk")
        _err(e)
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/create")
async def api_create(name: str, req: CreateRequest):
    try:
        return _files(name).create(req.path, req.kind, req.content)
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/rename-item")
async def api_rename(name: str, req: RenameRequest):
    try:
        return _files(name).rename(req.path, req.new_name)
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/move")
async def api_move(name: str, req: MoveRequest):
    try:
        return _files(name).move(req.path, req.dest_dir)
    except Exception as e:
        _err(e)


@app.delete("/api/projects/{name}/item")
async def api_delete(name: str, path: str = Query(...)):
    try:
        return _files(name).delete(path)
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/upload")
async def api_upload(name: str, dir: str = Form(""), files: List[UploadFile] = File(...)):
    pf = _files(name)
    try:
        out = []
        for f in files:
            out.append(pf.save_upload(dir, f.filename or "upload", await f.read()))
        return {"files": out}
    except Exception as e:
        _err(e)


INLINE_SAFE = {"application/pdf", "image/png", "image/jpeg", "image/gif", "image/webp", "image/bmp",
               "text/plain", "text/csv", "audio/mpeg", "audio/wav", "video/mp4"}


@app.get("/api/projects/{name}/raw")
async def api_raw(name: str, path: str = Query(...), download: int = 0):
    pf = _files(name)
    try:
        p = pf.resolve(path, must_exist=True)
    except Exception as e:
        _err(e)
    if not p.is_file():
        raise HTTPException(404, "Not a file")
    mime = pf.mime(p)
    headers = {"cache-control": "no-cache"}
    if mime == "image/svg+xml" and not download:
        # SVGs can contain script: show them, but sandboxed so nothing in them can run.
        return FileResponse(p, media_type=mime, headers={**headers, "content-security-policy": "sandbox; default-src 'none'; style-src 'unsafe-inline'"},
                            content_disposition_type="inline", filename=p.name)
    if download or mime not in INLINE_SAFE:
        # Anything that could run script in our origin (HTML, SVG, ...) is only ever downloaded.
        return FileResponse(p, filename=p.name, media_type="application/octet-stream" if not download else mime,
                            headers=headers, content_disposition_type="attachment")
    return FileResponse(p, media_type=mime, headers=headers, content_disposition_type="inline", filename=p.name)


@app.get("/api/projects/{name}/table")
async def api_table(name: str, path: str = Query(...), sheet: Optional[str] = None):
    import asyncio
    try:
        p = _files(name).resolve(path, must_exist=True)
        return await asyncio.to_thread(documents.table_preview, p, sheet)
    except Exception as e:
        if isinstance(e, (HTTPException, FileNotFoundError, PermissionError)):
            _err(e)
        raise HTTPException(422, detail=f"Couldn't read this table: {e}")


@app.get("/api/projects/{name}/preview-pdf")
async def api_preview_pdf(name: str, path: str = Query(...)):
    """Office documents rendered to PDF (cached) so they can be viewed in the browser."""
    proj = _project(name)
    try:
        p = ProjectFiles(proj).resolve(path, must_exist=True)
        out = await documents.office_preview_pdf(p, proj)
        return FileResponse(out, media_type="application/pdf", content_disposition_type="inline",
                            filename=p.stem + ".pdf")
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/export")
async def api_export(name: str, req: PathRequest):
    """Note (.md) -> PDF/Word, or LaTeX (.tex) -> PDF. Output lands next to the source."""
    proj = _project(name)
    pf = ProjectFiles(proj)
    try:
        src = pf.resolve(req.path, must_exist=True)
        fmt = (req.format or "pdf").lower()
        ext = src.suffix.lower()
        if ext in documents.TEX_EXT and fmt == "pdf":
            out = await documents.tex_to_pdf(src, proj)
        elif ext in documents.MARKDOWN_EXT and fmt in ("pdf", "docx"):
            out = await documents.markdown_to(src, proj, fmt)
        else:
            raise ValueError("This kind of file can't be converted that way.")
        return {"path": pf.rel(out), "mtime": out.stat().st_mtime}
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/import")
async def api_import(name: str, req: PathRequest):
    """Word / ODT / RTF / HTML -> editable Markdown note."""
    proj = _project(name)
    pf = ProjectFiles(proj)
    try:
        src = pf.resolve(req.path, must_exist=True)
        if src.suffix.lower() not in documents.IMPORTABLE_EXT:
            raise ValueError("Only Word, OpenDocument, RTF and web pages can be turned into notes.")
        out = await documents.import_to_markdown(src, proj)
        return {"path": pf.rel(out)}
    except Exception as e:
        _err(e)


# =========================================================================== chats
class SendRequest(BaseModel):
    text: str
    open_file: Optional[str] = None


@app.get("/api/projects/{name}/chats")
async def api_chats(name: str):
    return chat_manager.list(_project(name))


@app.post("/api/projects/{name}/chats")
async def api_new_chat(name: str):
    return chat_manager.create(_project(name))


@app.get("/api/projects/{name}/chats/{chat_id}")
async def api_chat(name: str, chat_id: str):
    try:
        return chat_manager.load(_project(name), chat_id)
    except Exception as e:
        _err(e)


@app.delete("/api/projects/{name}/chats/{chat_id}")
async def api_delete_chat(name: str, chat_id: str):
    try:
        chat_manager.delete(_project(name), chat_id)
        return {"ok": True}
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/chats/{chat_id}/send")
async def api_send(name: str, chat_id: str, req: SendRequest):
    try:
        return await chat_manager.send(_project(name), chat_id, req.text, req.open_file)
    except Exception as e:
        _err(e)


@app.post("/api/projects/{name}/chats/{chat_id}/stop")
async def api_stop(name: str, chat_id: str):
    chat_manager.stop(_project(name), chat_id)
    return {"ok": True}


@app.websocket("/ws/projects/{name}/chats/{chat_id}")
async def ws_chat(websocket: WebSocket, name: str, chat_id: str):
    try:
        proj = project_dir(name)
        chat_manager.load(proj, chat_id)
    except Exception:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    await chat_manager.subscribe(proj, chat_id, websocket)
    try:
        await websocket.send_json({"type": "chat", "chat": chat_manager.load(proj, chat_id)})
        while True:
            await websocket.receive_text()  # keep-alive pings from the browser
    except WebSocketDisconnect:
        pass
    finally:
        chat_manager.unsubscribe(proj, chat_id, websocket)


# =========================================================================== terminals (advanced)
class TerminalRequest(BaseModel):
    project: str
    command: Optional[str] = "/bin/bash"
    title: Optional[str] = "Terminal"
    cols: Optional[int] = 100
    rows: Optional[int] = 30


@app.get("/api/terminals")
async def list_terminals(project: Optional[str] = None):
    sessions = terminal_mgr.list_sessions()
    if project:
        try:
            cwd = str(project_dir(project))
            sessions = [s for s in sessions if s["cwd"] == cwd]
        except Exception:
            sessions = []
    return sessions


@app.post("/api/terminals")
async def create_terminal(req: TerminalRequest):
    proj = _project(req.project)
    s = terminal_mgr.create_session(command=req.command or "/bin/bash", cwd=str(proj), title=req.title or "Terminal",
                                    cols=req.cols or 100, rows=req.rows or 30, env=agent_env(proj))
    return s.get_info()


@app.delete("/api/terminals/{session_id}")
async def close_terminal(session_id: str):
    terminal_mgr.close_session(session_id)
    return {"ok": True}


@app.websocket("/ws/terminal/{session_id}")
async def terminal_ws(websocket: WebSocket, session_id: str):
    session = terminal_mgr.get_session(session_id)
    if not session:
        await websocket.close(code=4404)
        return
    await websocket.accept()
    session.add_socket(websocket)
    try:
        while True:
            msg = await websocket.receive_text()
            try:
                packet = json.loads(msg)
            except json.JSONDecodeError:
                session.write(msg)
                continue
            t = packet.get("type")
            if t == "input":
                session.write(packet.get("data", ""))
            elif t == "resize":
                session.resize(int(packet.get("cols", 100)), int(packet.get("rows", 30)))
    except WebSocketDisconnect:
        pass
    finally:
        session.remove_socket(websocket)


# =========================================================================== static
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/favicon.svg")
async def favicon():
    return FileResponse(STATIC / "favicon.svg", media_type="image/svg+xml")


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html", headers={"cache-control": "no-cache"})
