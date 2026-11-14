"""Projects (top-level folders of workspace/) and safe file operations inside them."""
import mimetypes
import re
import shutil
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .config import PROJECT_META_DIR, TRASH_DIR, WORKSPACE

HIDDEN_NAMES = {"__pycache__", ".ipynb_checkpoints", "node_modules", ".git", ".venv", "venv"}
NAME_RE = re.compile(r"^[^/\\\x00-\x1f]{1,120}$")
MAX_TEXT_BYTES = 5 * 1024 * 1024


def _check_name(name: str) -> str:
    name = name.strip()
    if not NAME_RE.match(name) or name in (".", "..") or name.startswith("."):
        raise ValueError("That name can't be used. Avoid slashes and don't start with a dot.")
    return name


def _move_to_trash(target: Path, label: str):
    TRASH_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = TRASH_DIR / f"{stamp}__{label.replace('/', '__')}"
    i = 1
    while dest.exists():
        dest = TRASH_DIR / f"{stamp}__{i}__{label.replace('/', '__')}"
        i += 1
    shutil.move(str(target), str(dest))


# --------------------------------------------------------------------------- projects
def list_projects() -> list:
    out = []
    for p in sorted(WORKSPACE.iterdir(), key=lambda x: x.name.lower()):
        if not p.is_dir() or p.name.startswith(".") or p.name in HIDDEN_NAMES:
            continue
        latest = p.stat().st_mtime
        count = 0
        for f in p.rglob("*"):
            rel = f.relative_to(p).parts
            if any(part.startswith(".") or part in HIDDEN_NAMES for part in rel):
                continue
            if f.is_file():
                count += 1
                latest = max(latest, f.stat().st_mtime)
            if count > 5000:
                break
        out.append({"name": p.name, "modified": latest, "file_count": count})
    out.sort(key=lambda x: -x["modified"])
    return out


def project_dir(name: str) -> Path:
    name = _check_name(name)
    p = (WORKSPACE / name).resolve()
    if p.parent != WORKSPACE.resolve() or not p.is_dir():
        raise FileNotFoundError("Project not found")
    return p


def create_project(name: str) -> dict:
    name = _check_name(name)
    p = WORKSPACE / name
    if p.exists():
        raise FileExistsError("A project with this name already exists.")
    p.mkdir(parents=True)
    return {"name": name}


def rename_project(name: str, new_name: str) -> dict:
    src = project_dir(name)
    new_name = _check_name(new_name)
    dst = WORKSPACE / new_name
    if dst.exists():
        raise FileExistsError("A project with this name already exists.")
    src.rename(dst)
    return {"name": new_name}


def delete_project(name: str) -> dict:
    src = project_dir(name)
    _move_to_trash(src, name)
    return {"success": True}


# --------------------------------------------------------------------------- files
class ProjectFiles:
    def __init__(self, root: Path):
        self.root = root.resolve()

    def resolve(self, rel_path: str, must_exist: bool = False) -> Path:
        clean = (rel_path or "").replace("\\", "/").lstrip("/").strip()
        target = (self.root / clean).resolve()
        if target != self.root and not target.is_relative_to(self.root):
            raise PermissionError("That location is outside the project.")
        rel_parts = target.relative_to(self.root).parts
        if rel_parts and rel_parts[0] == PROJECT_META_DIR:
            raise PermissionError("That location is reserved.")
        if must_exist and not target.exists():
            raise FileNotFoundError(f"Not found: {rel_path}")
        return target

    def rel(self, p: Path) -> str:
        return str(p.resolve().relative_to(self.root))

    def tree(self) -> Dict[str, Any]:
        def node(path: Path) -> Dict[str, Any]:
            st = path.stat()
            rel = "" if path == self.root else self.rel(path)
            n: Dict[str, Any] = {"name": path.name, "path": rel, "modified": st.st_mtime}
            if path.is_dir():
                n["type"] = "dir"
                children = []
                try:
                    entries = sorted(path.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower()))
                except PermissionError:
                    entries = []
                for e in entries:
                    if e.name.startswith(".") or e.name in HIDDEN_NAMES or e.is_symlink() and not e.exists():
                        continue
                    children.append(node(e))
                n["children"] = children
            else:
                n["type"] = "file"
                n["size"] = st.st_size
            return n
        return node(self.root)

    def read_text(self, rel_path: str) -> Dict[str, Any]:
        target = self.resolve(rel_path, must_exist=True)
        if target.is_dir():
            raise IsADirectoryError("That is a folder.")
        st = target.stat()
        if st.st_size > MAX_TEXT_BYTES:
            raise ValueError("This file is too large to open in the editor.")
        try:
            content = target.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            raise ValueError("This file isn't plain text, so it can't be edited here.")
        return {"path": self.rel(target), "name": target.name, "content": content, "mtime": st.st_mtime}

    def write_text(self, rel_path: str, content: str, expected_mtime: Optional[float] = None) -> Dict[str, Any]:
        target = self.resolve(rel_path)
        if expected_mtime is not None and target.exists():
            current = target.stat().st_mtime
            if abs(current - expected_mtime) > 0.001:
                raise FileExistsError("changed-on-disk")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(f".{target.name}.saving")
        tmp.write_text(content, encoding="utf-8")
        tmp.replace(target)
        return {"path": self.rel(target), "mtime": target.stat().st_mtime}

    def create(self, rel_path: str, kind: str, content: str = "") -> Dict[str, Any]:
        target = self.resolve(rel_path)
        _check_name(target.name)
        if target.exists():
            raise FileExistsError(f"'{target.name}' already exists here.")
        if kind == "dir":
            target.mkdir(parents=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        return {"path": self.rel(target)}

    def rename(self, rel_path: str, new_name: str) -> Dict[str, Any]:
        target = self.resolve(rel_path, must_exist=True)
        if target == self.root:
            raise ValueError("Can't rename the project here.")
        new_name = _check_name(new_name)
        dest = target.parent / new_name
        if dest.exists():
            raise FileExistsError(f"'{new_name}' already exists here.")
        target.rename(dest)
        return {"path": self.rel(dest)}

    def move(self, rel_path: str, dest_dir: str) -> Dict[str, Any]:
        target = self.resolve(rel_path, must_exist=True)
        folder = self.resolve(dest_dir, must_exist=True)
        if not folder.is_dir():
            raise NotADirectoryError("Destination is not a folder.")
        if folder == target or folder.is_relative_to(target):
            raise ValueError("Can't move a folder into itself.")
        dest = folder / target.name
        if dest.exists():
            raise FileExistsError(f"'{target.name}' already exists there.")
        shutil.move(str(target), str(dest))
        return {"path": self.rel(dest)}

    def delete(self, rel_path: str) -> Dict[str, Any]:
        target = self.resolve(rel_path, must_exist=True)
        if target == self.root:
            raise ValueError("Can't delete the project here.")
        _move_to_trash(target, f"{self.root.name}/{self.rel(target)}")
        return {"success": True}

    def save_upload(self, dir_rel: str, filename: str, data: bytes) -> Dict[str, Any]:
        folder = self.resolve(dir_rel)
        if folder.exists() and not folder.is_dir():
            folder = folder.parent
        folder.mkdir(parents=True, exist_ok=True)
        name = Path(filename.replace("\\", "/")).name.strip() or "upload"
        if name.startswith("."):
            name = "_" + name[1:]
        target = folder / name
        if target.exists():  # never silently overwrite her files
            stem, suffix = target.stem, target.suffix
            i = 2
            while target.exists():
                target = folder / f"{stem} ({i}){suffix}"
                i += 1
        target.write_bytes(data)
        return {"path": self.rel(target), "name": target.name, "size": len(data)}

    @staticmethod
    def mime(path: Path) -> str:
        m, _ = mimetypes.guess_type(path.name)
        return m or "application/octet-stream"


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    i = 2
    while True:
        cand = path.with_name(f"{path.stem} ({i}){path.suffix}")
        if not cand.exists():
            return cand
        i += 1


def now() -> float:
    return time.time()
