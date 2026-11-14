import os
import pty
import fcntl
import termios
import struct
import signal
import asyncio
import uuid
import time
from typing import Dict, Optional, Set
from fastapi import WebSocket

class TerminalSession:
    def __init__(self, session_id: str, command: str, cwd: str, title: str, loop: asyncio.AbstractEventLoop,
                 env: Optional[dict] = None):
        self.base_env = env
        self.session_id = session_id
        self.command = command
        self.cwd = cwd
        self.title = title
        self.loop = loop
        self.master_fd: Optional[int] = None
        self.pid: Optional[int] = None
        self.is_alive = False
        self.exit_code: Optional[int] = None
        self.buffer = bytearray()
        self.max_buffer_size = 500_000  # 500KB rolling buffer
        self.sockets: Set[WebSocket] = set()
        self.created_at = time.time()

    def start(self, cols: int = 100, rows: int = 30):
        master, slave = pty.openpty()
        self.master_fd = master

        # Set initial window size
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(master, termios.TIOCSWINSZ, winsize)

        env = dict(self.base_env or os.environ)
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env.setdefault("SHELL", "/bin/bash")

        pid = os.fork()
        if pid == 0:
            # Child process
            os.close(master)
            os.setsid()
            fcntl.ioctl(slave, termios.TIOCSCTTY, 0)

            os.dup2(slave, 0)
            os.dup2(slave, 1)
            os.dup2(slave, 2)
            if slave > 2:
                os.close(slave)

            # Change to target directory
            try:
                os.chdir(self.cwd)
            except Exception:
                os.chdir(os.path.expanduser("~"))

            # Execute command
            os.execvpe("/bin/bash", ["/bin/bash", "-c", self.command], env)
            os._exit(1)
        else:
            # Parent process
            os.close(slave)
            self.pid = pid
            self.is_alive = True
            # Register reader on asyncio loop
            self.loop.add_reader(self.master_fd, self._on_readable)

    def _on_readable(self):
        if self.master_fd is None:
            return
        try:
            data = os.read(self.master_fd, 8192)
            if not data:
                self._handle_exit()
                return

            self.buffer.extend(data)
            if len(self.buffer) > self.max_buffer_size:
                self.buffer = self.buffer[-self.max_buffer_size:]

            self._broadcast(data)
        except (OSError, IOError):
            self._handle_exit()

    def _handle_exit(self):
        if not self.is_alive:
            return
        self.is_alive = False

        if self.master_fd is not None:
            try:
                self.loop.remove_reader(self.master_fd)
            except Exception:
                pass
            try:
                os.close(self.master_fd)
            except OSError:
                pass
            self.master_fd = None

        if self.pid is not None:
            try:
                _, status = os.waitpid(self.pid, os.WNOHANG)
                if os.WIFEXITED(status):
                    self.exit_code = os.WEXITSTATUS(status)
                elif os.WIFSIGNALED(status):
                    self.exit_code = -os.WTERMSIG(status)
            except ChildProcessError:
                pass

        exit_msg = f"\r\n\x1b[90m[Process exited with code {self.exit_code if self.exit_code is not None else 0}]\x1b[0m\r\n".encode("utf-8")
        self.buffer.extend(exit_msg)
        self._broadcast(exit_msg)

    def _broadcast(self, data: bytes):
        dead = []
        for ws in self.sockets:
            try:
                asyncio.create_task(ws.send_bytes(data))
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.sockets.discard(ws)

    def write(self, data: str):
        if self.is_alive and self.master_fd is not None:
            try:
                os.write(self.master_fd, data.encode("utf-8"))
            except OSError:
                self._handle_exit()

    def resize(self, cols: int, rows: int):
        if self.master_fd is not None:
            try:
                winsize = struct.pack("HHHH", rows, cols, 0, 0)
                fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            except OSError:
                pass

    def kill(self):
        if self.pid and self.is_alive:
            try:
                os.kill(self.pid, signal.SIGTERM)
                # schedule check
                def force_kill():
                    if self.is_alive and self.pid:
                        try:
                            os.kill(self.pid, signal.SIGKILL)
                        except OSError:
                            pass
                self.loop.call_later(0.5, force_kill)
            except OSError:
                pass
        self._handle_exit()

    def add_socket(self, ws: WebSocket):
        self.sockets.add(ws)
        # Send buffered output so client catches up
        if self.buffer:
            asyncio.create_task(ws.send_bytes(bytes(self.buffer)))

    def remove_socket(self, ws: WebSocket):
        self.sockets.discard(ws)

    def get_info(self) -> dict:
        return {
            "session_id": self.session_id,
            "title": self.title,
            "command": self.command,
            "cwd": self.cwd,
            "pid": self.pid,
            "is_alive": self.is_alive,
            "exit_code": self.exit_code,
            "created_at": self.created_at,
        }


class TerminalManager:
    def __init__(self):
        self.sessions: Dict[str, TerminalSession] = {}

    def create_session(
        self,
        command: str = "/bin/bash",
        cwd: str = ".",
        title: str = "Terminal",
        cols: int = 100,
        rows: int = 30,
        session_id: Optional[str] = None,
        env: Optional[dict] = None,
    ) -> TerminalSession:
        loop = asyncio.get_running_loop()
        if not session_id:
            session_id = str(uuid.uuid4())

        # If already exists, return existing
        if session_id in self.sessions:
            return self.sessions[session_id]

        session = TerminalSession(
            session_id=session_id,
            command=command,
            cwd=cwd,
            title=title,
            loop=loop,
            env=env,
        )
        session.start(cols=cols, rows=rows)
        self.sessions[session_id] = session
        return session

    def get_session(self, session_id: str) -> Optional[TerminalSession]:
        return self.sessions.get(session_id)

    def list_sessions(self) -> list:
        return [s.get_info() for s in self.sessions.values()]

    def close_session(self, session_id: str):
        session = self.sessions.pop(session_id, None)
        if session:
            session.kill()
