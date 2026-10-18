"""Turco Porto web server.

Serves the static site and handles the private dinner / catering form:
POST /api/request  ->  emails the request to MAIL_TO via SMTP.

Standard library only. Configure with environment variables (set them as
secrets in Outplane, never in this repo):

  SMTP_HOST   e.g. smtp.gmail.com
  SMTP_PORT   587 (STARTTLS, default) or 465 (SSL)
  SMTP_USER   the mailbox that sends, e.g. hey@techsalestr.com
  SMTP_PASS   its password or app password
  MAIL_TO     where requests go (default: hey@techsalestr.com)
  MAIL_FROM   sender address (default: SMTP_USER)
  PORT        port to listen on (default: 8080)
"""

import json
import mimetypes
import os
import re
import smtplib
import ssl
import sys
import threading
import time
from collections import defaultdict, deque
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent / "public"
PORT = int(os.environ.get("PORT", "8080"))
MAIL_TO = os.environ.get("MAIL_TO", "hey@techsalestr.com")

mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("image/svg+xml", ".svg")
mimetypes.add_type("text/plain; charset=utf-8", ".txt")

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
TYPES = {
    "Private dinner at home",
    "Birthday or celebration",
    "Team lunch or company event",
    "Something else",
}
LIMITS = {"name": 120, "email": 200, "date": 20, "guests": 6, "type": 60, "message": 4000}

# 5 requests per IP per hour, kept in memory.
RATE_MAX, RATE_WINDOW = 5, 3600
_hits = defaultdict(deque)
_lock = threading.Lock()


def log(*parts):
    print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), *parts, file=sys.stderr, flush=True)


def rate_limited(ip):
    now = time.time()
    with _lock:
        q = _hits[ip]
        while q and now - q[0] > RATE_WINDOW:
            q.popleft()
        if len(q) >= RATE_MAX:
            return True
        q.append(now)
        return False


def smtp_configured():
    return all(os.environ.get(k) for k in ("SMTP_HOST", "SMTP_USER", "SMTP_PASS"))


def send_mail(req):
    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ["SMTP_USER"]
    password = os.environ["SMTP_PASS"]
    sender = os.environ.get("MAIL_FROM", user)

    msg = EmailMessage()
    msg["Subject"] = f"Turco Porto request: {req['type']} ({req['name']})"
    msg["From"] = formataddr(("Turco Porto website", sender))
    msg["To"] = MAIL_TO
    msg["Reply-To"] = formataddr((req["name"], req["email"]))
    msg["Message-ID"] = make_msgid(domain="turcoporto.com")
    msg.set_content(
        "New request from turcoporto.com\n\n"
        f"Name:   {req['name']}\n"
        f"Email:  {req['email']}\n"
        f"Date:   {req['date'] or 'not set yet'}\n"
        f"Guests: {req['guests'] or 'not sure yet'}\n"
        f"For:    {req['type']}\n\n"
        f"{req['message'] or '(no message)'}\n\n"
        "Reply to this email to answer them directly.\n"
    )

    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            s.login(user, password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.starttls(context=ctx)
            s.login(user, password)
            s.send_message(msg)


def clean(data):
    """Return (request dict, error message)."""
    if not isinstance(data, dict):
        return None, "Bad request."
    if str(data.get("website", "")).strip():  # honeypot field, humans never see it
        return "spam", None
    req = {}
    for key, limit in LIMITS.items():
        val = str(data.get(key, "") or "").strip()
        if len(val) > limit:
            return None, f"The {key} field is too long."
        req[key] = val.replace("\r", "")
    for key in ("name", "email", "date", "guests", "type"):
        req[key] = " ".join(req[key].split())  # no line breaks in header-ish fields
    if not req["name"]:
        return None, "Please add your name."
    if not EMAIL_RE.match(req["email"]):
        return None, "Please add a valid email so I can reply."
    if req["date"] and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", req["date"]):
        return None, "Please pick a date from the calendar."
    if req["guests"] and not req["guests"].isdigit():
        return None, "Guests should be a number."
    if req["type"] not in TYPES:
        req["type"] = "Something else"
    return req, None


class Handler(BaseHTTPRequestHandler):
    server_version = "TurcoPorto"
    sys_version = ""

    def log_message(self, fmt, *args):
        pass  # keep logs for form events only

    # ---------- helpers
    def client_ip(self):
        fwd = self.headers.get("X-Forwarded-For", "")
        return fwd.split(",")[0].strip() or self.client_address[0]

    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def security_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        self.send_header("X-Frame-Options", "SAMEORIGIN")

    # ---------- static files
    def serve_static(self, head_only=False):
        path = unquote(self.path.split("?", 1)[0].split("#", 1)[0])
        if path.endswith("/"):
            path += "index.html"
        target = (ROOT / path.lstrip("/")).resolve()
        if ROOT not in target.parents and target != ROOT:
            return self.send_error(HTTPStatus.NOT_FOUND)
        status = HTTPStatus.OK
        if not target.is_file():
            if "." in Path(path).name:  # a missing file, not a page
                return self.send_error(HTTPStatus.NOT_FOUND)
            target = ROOT / "index.html"
        data = target.read_bytes()
        ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if ctype.startswith("text/") and "charset" not in ctype:
            ctype += "; charset=utf-8"
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        if target.name == "index.html":
            self.send_header("Cache-Control", "no-cache")
        elif "/images/" in str(target):
            self.send_header("Cache-Control", "public, max-age=2592000")
        else:
            self.send_header("Cache-Control", "public, max-age=3600")
        self.security_headers()
        self.end_headers()
        if not head_only:
            self.wfile.write(data)

    def do_GET(self):
        if self.path.startswith("/api/health"):
            return self.send_json(200, {"ok": True, "mail": smtp_configured()})
        self.serve_static()

    def do_HEAD(self):
        self.serve_static(head_only=True)

    # ---------- form
    def do_POST(self):
        if self.path.split("?", 1)[0] != "/api/request":
            return self.send_json(404, {"ok": False, "error": "Not found."})
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if length <= 0 or length > 20000:
            return self.send_json(400, {"ok": False, "error": "Bad request."})
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return self.send_json(400, {"ok": False, "error": "Bad request."})

        req, err = clean(data)
        if req == "spam":
            return self.send_json(200, {"ok": True})
        if err:
            return self.send_json(400, {"ok": False, "error": err})

        ip = self.client_ip()
        if rate_limited(ip):
            return self.send_json(429, {"ok": False, "error": "Too many requests from here. Please try again later or write to me directly."})

        # Always keep a copy in the logs, so nothing is lost if email fails.
        log("REQUEST", json.dumps(req, ensure_ascii=False))

        if not smtp_configured():
            log("MAIL not configured, request only logged")
            return self.send_json(503, {"ok": False, "error": "The form can't send right now."})
        try:
            send_mail(req)
        except Exception as e:  # noqa: BLE001
            log("MAIL FAILED", type(e).__name__, str(e)[:200])
            return self.send_json(502, {"ok": False, "error": "The form can't send right now."})
        log("MAIL SENT to", MAIL_TO)
        return self.send_json(200, {"ok": True})


if __name__ == "__main__":
    log(f"Turco Porto listening on :{PORT}, mail {'on' if smtp_configured() else 'OFF (set SMTP_* env vars)'}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
