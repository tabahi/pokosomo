"""Login protection: password, optional TOTP (authenticator app), server-side sessions.

secrets.json layout (other top-level keys are preserved untouched):
    {
      "login": {
        "password_hash": "scrypt$16384$8$1$<salt b64>$<hash b64>",
        "totp_secret": "BASE32SECRET"      # only present when two-factor sign-in is enabled
      }
    }

Create or change it with:  ./setup_auth.sh   (= python -m server.auth setup)
"""
import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import sys
import threading
import time
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from .config import DATA, SECRETS_FILE

COOKIE_NAME = "pokosomo_session"
REMEMBER_SECONDS = 30 * 24 * 3600          # "remember me": one month
NO_REMEMBER_IDLE_SECONDS = 12 * 3600       # otherwise: browser-session cookie + 12h idle limit
MAX_FAILURES = 5
FAILURE_WINDOW = 15 * 60
SESSIONS_FILE = DATA / "sessions.json"

# Paths reachable without logging in.
PUBLIC_PATHS = {"/login", "/api/auth/login", "/api/auth/state", "/favicon.svg"}


# --------------------------------------------------------------------------- secrets
def _scrypt(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=n, r=r, p=p, maxmem=128 * 1024 * 1024, dklen=32)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    n, r, p = 16384, 8, 1
    digest = _scrypt(password, salt, n, r, p)
    return f"scrypt${n}${r}${p}${base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt_b64, hash_b64 = stored.split("$")
        if algo != "scrypt":
            return False
        digest = _scrypt(password, base64.b64decode(salt_b64), int(n), int(r), int(p))
        return hmac.compare_digest(digest, base64.b64decode(hash_b64))
    except Exception:
        return False


def load_secrets(path: Path = SECRETS_FILE) -> dict:
    try:
        text = path.read_text().strip()
        return json.loads(text) if text else {}
    except FileNotFoundError:
        return {}


def login_config() -> Optional[dict]:
    login = load_secrets().get("login") or {}
    if login.get("password_hash"):
        return login
    return None


def totp_enabled(cfg: Optional[dict] = None) -> bool:
    cfg = login_config() if cfg is None else cfg
    return bool(cfg and cfg.get("totp_secret"))


# --------------------------------------------------------------------------- TOTP
class TotpVerifier:
    """RFC 6238 check (via pyotp) with replay protection: a code can be used once."""

    def __init__(self):
        self._last_step = 0
        self._lock = threading.Lock()

    def verify(self, secret: str, code: str) -> bool:
        import pyotp
        code = "".join(ch for ch in code if ch.isdigit())
        if len(code) != 6:
            return False
        totp = pyotp.TOTP(secret)
        now = time.time()
        for drift in (-1, 0, 1):  # allow ±30s clock skew
            t = now + drift * totp.interval
            if hmac.compare_digest(totp.at(t), code):
                step = int(t // totp.interval)
                with self._lock:
                    if step <= self._last_step:
                        return False
                    self._last_step = step
                return True
        return False


totp_verifier = TotpVerifier()


# --------------------------------------------------------------------------- rate limiting
class FailureLimiter:
    def __init__(self):
        self._fails: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def _recent(self, key: str) -> list[float]:
        now = time.time()
        lst = [t for t in self._fails.get(key, []) if now - t < FAILURE_WINDOW]
        self._fails[key] = lst
        return lst

    def blocked_for(self, key: str) -> int:
        with self._lock:
            lst = self._recent(key)
            if len(lst) >= MAX_FAILURES:
                return int(FAILURE_WINDOW - (time.time() - lst[0])) + 1
            return 0

    def fail(self, key: str):
        with self._lock:
            self._recent(key).append(time.time())

    def reset(self, key: str):
        with self._lock:
            self._fails.pop(key, None)


limiter = FailureLimiter()


# --------------------------------------------------------------------------- sessions
class SessionStore:
    """Sessions persisted to data/sessions.json, keyed by SHA-256 of the cookie token."""

    def __init__(self, path: Path = SESSIONS_FILE):
        self.path = path
        self._lock = threading.Lock()
        self._sessions: dict[str, dict] = {}
        self._load()

    @staticmethod
    def _key(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def _load(self):
        try:
            self._sessions = json.loads(self.path.read_text())
        except Exception:
            self._sessions = {}
        self._purge()

    def _save(self):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._sessions))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    def _purge(self):
        now = time.time()
        dead = [k for k, s in self._sessions.items() if not self._alive(s, now)]
        for k in dead:
            del self._sessions[k]
        return bool(dead)

    @staticmethod
    def _alive(s: dict, now: float) -> bool:
        if now >= s["expires"]:
            return False
        if not s["remember"] and now - s["last_seen"] > NO_REMEMBER_IDLE_SECONDS:
            return False
        return True

    def create(self, remember: bool, user_agent: str = "") -> str:
        token = secrets.token_urlsafe(32)
        now = time.time()
        with self._lock:
            self._purge()
            self._sessions[self._key(token)] = {
                "created": now,
                "last_seen": now,
                "expires": now + REMEMBER_SECONDS,
                "remember": remember,
                "ua": user_agent[:200],
            }
            self._save()
        return token

    def validate(self, token: Optional[str]) -> bool:
        if not token:
            return False
        key = self._key(token)
        now = time.time()
        with self._lock:
            s = self._sessions.get(key)
            if not s:
                return False
            if not self._alive(s, now):
                del self._sessions[key]
                self._save()
                return False
            if now - s["last_seen"] > 300:  # don't write to disk on every request
                s["last_seen"] = now
                self._save()
            return True

    def revoke(self, token: Optional[str]):
        if not token:
            return
        with self._lock:
            if self._sessions.pop(self._key(token), None) is not None:
                self._save()

    def revoke_all(self):
        with self._lock:
            self._sessions = {}
            self._save()


sessions = SessionStore()


# --------------------------------------------------------------------------- helpers
def _headers(scope) -> dict:
    return {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}


def token_from_scope(scope) -> Optional[str]:
    cookie = _headers(scope).get("cookie")
    if not cookie:
        return None
    jar = SimpleCookie()
    try:
        jar.load(cookie)
    except Exception:
        return None
    morsel = jar.get(COOKIE_NAME)
    return morsel.value if morsel else None


def is_https(scope) -> bool:
    h = _headers(scope)
    return scope.get("scheme") in ("https", "wss") or h.get("x-forwarded-proto", "").split(",")[0].strip() == "https"


def client_ip(scope) -> str:
    # Deliberately not reading X-Forwarded-For here (clients could spoof it to dodge the
    # lockout). uvicorn --proxy-headers rewrites scope["client"] for trusted proxies only.
    client = scope.get("client")
    return client[0] if client else "unknown"


def same_origin(scope) -> bool:
    """Reject cross-site requests (CSRF / cross-site WebSocket hijacking)."""
    h = _headers(scope)
    origin = h.get("origin")
    if not origin or origin == "null":
        # Browsers always send Origin on WebSocket handshakes and cross-site POSTs.
        return scope["type"] != "websocket" and origin is None
    origin_host = urlsplit(origin).netloc.lower()
    allowed = {h.get("host", "").lower()}
    if h.get("x-forwarded-host"):
        allowed.add(h["x-forwarded-host"].split(",")[0].strip().lower())
    return origin_host in allowed


def session_cookie_header(token: str, remember: bool, secure: bool) -> str:
    parts = [f"{COOKIE_NAME}={token}", "Path=/", "HttpOnly", "SameSite=Lax"]
    if remember:
        parts.append(f"Max-Age={REMEMBER_SECONDS}")
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_cookie_header(secure: bool) -> str:
    parts = [f"{COOKIE_NAME}=", "Path=/", "HttpOnly", "SameSite=Lax", "Max-Age=0"]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


async def attempt_login(scope, password: str, code: str, remember: bool) -> tuple[bool, str, Optional[str]]:
    """Returns (ok, message, token)."""
    cfg = login_config()
    if not cfg:
        return False, "Login is not set up yet. Run ./setup_auth.sh on the server.", None
    ip = client_ip(scope)
    wait = limiter.blocked_for(ip)
    if wait:
        return False, f"Too many attempts. Please wait {max(1, wait // 60)} minute(s) and try again.", None
    pw_ok = await asyncio.to_thread(verify_password, password or "", cfg["password_hash"])
    if totp_enabled(cfg):
        code_ok = pw_ok and totp_verifier.verify(cfg["totp_secret"], code or "")
        wrong = "Password or code is not correct. Codes change every 30 seconds — use a fresh one."
    else:
        code_ok = True
        wrong = "That password is not correct."
    if not (pw_ok and code_ok):
        limiter.fail(ip)
        await asyncio.sleep(0.6)
        return False, wrong, None
    limiter.reset(ip)
    token = sessions.create(remember=remember, user_agent=_headers(scope).get("user-agent", ""))
    return True, "ok", token


# --------------------------------------------------------------------------- middleware
SECURITY_HEADERS = [
    (b"x-content-type-options", b"nosniff"),
    (b"referrer-policy", b"no-referrer"),
    (b"x-frame-options", b"SAMEORIGIN"),
]


class AuthMiddleware:
    """Pure ASGI middleware so it covers both HTTP and WebSocket traffic."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            return await self.app(scope, receive, send)

        path = scope.get("path", "")

        if scope["type"] == "websocket":
            if not same_origin(scope) or not sessions.validate(token_from_scope(scope)):
                await send({"type": "websocket.close", "code": 4401})
                return
            return await self.app(scope, receive, send)

        method = scope.get("method", "GET")
        if method not in ("GET", "HEAD", "OPTIONS") and not same_origin(scope):
            return await self._respond(send, 403, b'{"detail":"Cross-site request blocked"}', b"application/json")

        authed = path in PUBLIC_PATHS or sessions.validate(token_from_scope(scope))
        if not authed:
            if path.startswith("/api/"):
                return await self._respond(send, 401, b'{"detail":"Not signed in"}', b"application/json")
            return await self._redirect(send, "/login")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                existing = {k.lower() for k, _ in headers}
                headers += [h for h in SECURITY_HEADERS if h[0] not in existing]
                if path.startswith("/api/"):
                    headers.append((b"cache-control", b"no-store"))
                message["headers"] = headers
            await send(message)

        return await self.app(scope, receive, send_with_headers)

    @staticmethod
    async def _respond(send, status, body, ctype):
        await send({"type": "http.response.start", "status": status,
                    "headers": [(b"content-type", ctype), *SECURITY_HEADERS]})
        await send({"type": "http.response.body", "body": body})

    @staticmethod
    async def _redirect(send, location):
        await send({"type": "http.response.start", "status": 302,
                    "headers": [(b"location", location.encode()), *SECURITY_HEADERS]})
        await send({"type": "http.response.body", "body": b""})


# --------------------------------------------------------------------------- CLI
def _setup_cli():
    import getpass
    import pyotp
    import qrcode

    print("Pokosomo Studio — login setup\n")
    data = load_secrets()
    while True:
        pw = getpass.getpass("New password (min 10 characters): ")
        if len(pw) < 10:
            print("  Too short, try again.")
            continue
        if getpass.getpass("Repeat password: ") != pw:
            print("  Passwords don't match, try again.")
            continue
        break

    login = data.get("login") or {}
    keep_totp = False
    if login.get("totp_secret"):
        keep_totp = input("Keep the existing authenticator (2FA) setup? [Y/n] ").strip().lower() in ("", "y", "yes")
    use_totp = keep_totp
    if not keep_totp:
        print("\nTwo-factor sign-in (2FA) asks for a 6-digit code from an authenticator app on your phone,")
        print("in addition to the password.")
        print("  - Running only on your own computer (http://localhost)? You can skip it.")
        print("  - Reachable from the internet or a shared network (a public server)? You MUST enable it.")
        use_totp = input("Enable two-factor sign-in? [y/N] ").strip().lower() in ("y", "yes")
    secret = login["totp_secret"] if keep_totp else (pyotp.random_base32() if use_totp else None)

    if use_totp and not keep_totp:
        name = input("Name shown in the authenticator app [studio]: ").strip() or "studio"
        uri = pyotp.TOTP(secret).provisioning_uri(name=name, issuer_name="Pokosomo Studio")
        print("\nScan this QR code with Google Authenticator / Microsoft Authenticator / Aegis / 1Password:\n")
        qr = qrcode.QRCode(border=1)
        qr.add_data(uri)
        qr.print_ascii(invert=True)
        print(f"\nOr enter this key manually: {secret}\n")
        for _ in range(3):
            code = input("Enter the 6-digit code the app shows now, to confirm: ").strip()
            if pyotp.TOTP(secret).verify(code, valid_window=1):
                print("  Code OK.")
                break
            print("  That code didn't match. Check the phone's clock and try again.")
        else:
            print("Aborted — nothing was saved.")
            sys.exit(1)

    data["login"] = {"password_hash": hash_password(pw)}
    if secret:
        data["login"]["totp_secret"] = secret
    else:
        print("\nTwo-factor sign-in is OFF. Do not expose this studio to the internet without it;")
        print("run ./setup_auth.sh again to turn it on.")
    SECRETS_FILE.write_text(json.dumps(data, indent=2) + "\n")
    os.chmod(SECRETS_FILE, 0o600)
    sessions.revoke_all()
    print(f"\nSaved to {SECRETS_FILE}. All existing sign-ins were logged out.")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "setup"
    if cmd == "setup":
        _setup_cli()
    elif cmd == "logout-all":
        sessions.revoke_all()
        print("All sessions revoked.")
    elif cmd == "status":
        print("Login configured." if login_config() else "Login NOT configured — run ./setup_auth.sh")
    else:
        print("usage: python -m server.auth [setup|logout-all|status]")
        sys.exit(2)
