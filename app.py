import hashlib
import hmac
import os
from functools import wraps
import re
import secrets
import sqlite3
import struct
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote, urlencode

from flask import Flask, abort, jsonify, make_response, request, send_from_directory

STATE = Path(os.environ.get("TRANSIT_STATE", "/var/lib/transit-privat"))
SECRET = Path(os.environ.get("TRANSIT_SECRET", "/etc/transit-privat/totp.key"))
MAX_FILE = 25 * 1024**2
MAX_TEXT = 256 * 1024
QUOTA = 500 * 1024**2
IDLE = 900
COOKIE = "__Host-transit"
app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = MAX_FILE


@contextmanager
def database(write=False):
    db = sqlite3.connect(STATE / "transit.sqlite3", timeout=10)
    try:
        db.execute("PRAGMA secure_delete=ON")
        if write:
            db.execute("BEGIN IMMEDIATE")
        yield db
        db.commit()
    finally:
        db.close()


def initialize():
    with database() as db:
        db.executescript("""
            PRAGMA auto_vacuum=FULL;
            CREATE TABLE IF NOT EXISTS items (
                id TEXT PRIMARY KEY, kind TEXT, name TEXT, expires INTEGER,
                size INTEGER, content BLOB
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token TEXT PRIMARY KEY, seen INTEGER, started INTEGER
            );
            CREATE TABLE IF NOT EXISTS attempts (ip TEXT, at INTEGER);
            CREATE TABLE IF NOT EXISTS totp (slot INTEGER PRIMARY KEY);
        """)


def cleanup():
    now = int(time.time())
    with database(write=True) as db:
        db.execute("DELETE FROM items WHERE expires <= ?", (now,))
        db.execute("DELETE FROM sessions WHERE seen <= ? OR started <= ?",
                   (now - IDLE, now - 28800))
        db.execute("DELETE FROM attempts WHERE at <= ?", (now - 300,))


def code_for(key, slot):
    digest = hmac.digest(key, struct.pack(">Q", slot), "sha1")
    offset = digest[-1] & 15
    value = int.from_bytes(digest[offset:offset + 4], "big") & 0x7fffffff
    return f"{value % 1000000:06d}"


def session_key():
    token = request.cookies.get(COOKIE, "")
    return hashlib.sha256(token.encode()).hexdigest()


def require_session(handler):
    @wraps(handler)
    def protected(*args, **kwargs):
        now = int(time.time())
        with database(write=True) as db:
            valid = db.execute(
                "UPDATE sessions SET seen=? WHERE token=? AND seen>? AND started>?",
                (now, session_key(), now - IDLE, now - 28800),
            ).rowcount
        if not valid:
            abort(401)
        return handler(*args, **kwargs)
    return protected


@app.before_request
def protect_writes():
    if request.method in {"POST", "DELETE"}:
        if request.headers.get("X-Transit-Request") != "1":
            abort(403)


@app.after_request
def headers(response):
    response.headers.update({
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
        "Content-Security-Policy": "default-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    })
    return response


@app.get("/")
def home():
    return send_from_directory("web", "index.html")


@app.get("/assets/<any(app.js,style.css):name>")
def assets(name):
    return send_from_directory("web", name)


@app.post("/login")
def login():
    key = SECRET.read_bytes()
    ip = request.headers.get("X-Real-IP") or request.remote_addr or ""
    now = int(time.time())
    slot = now // 30
    with database(write=True) as db:
        db.execute("DELETE FROM attempts WHERE at <= ?", (now - 300,))
        total, per_ip = db.execute(
            "SELECT COUNT(*), COUNT(CASE WHEN ip=? THEN 1 END) FROM attempts", (ip,)
        ).fetchone()
        if total >= 20 or per_ip >= 5:
            return "", 429
        code = request.get_data(cache=False, as_text=True) if request.content_length == 6 else ""
        last = db.execute("SELECT MAX(slot) FROM totp").fetchone()[0]
        accepted = None
        if re.fullmatch(r"[0-9]{6}", code):
            for candidate in (slot, slot - 1, slot + 1):
                if (last is None or candidate > last) and hmac.compare_digest(
                    code, code_for(key, candidate)
                ):
                    accepted = candidate
                    break
        if accepted is None:
            db.execute("INSERT INTO attempts VALUES (?,?)", (ip, now))
            return "", 401
        db.execute("DELETE FROM totp")
        db.execute("INSERT INTO totp VALUES (?)", (accepted,))
        db.execute("DELETE FROM sessions WHERE token=?", (session_key(),))
        token = secrets.token_urlsafe(32)
        db.execute("INSERT INTO sessions VALUES (?,?,?)",
                   (hashlib.sha256(token.encode()).hexdigest(), now, now))
    response = make_response("", 204)
    response.set_cookie(COOKIE, token, secure=True, httponly=True, samesite="Strict", path="/")
    return response


@app.post("/logout")
def logout():
    with database(write=True) as db:
        db.execute("DELETE FROM sessions WHERE token=?", (session_key(),))
    response = make_response("", 204)
    response.delete_cookie(COOKIE, secure=True, httponly=True, samesite="Strict", path="/")
    return response


@app.get("/items")
@require_session
def items():
    with database() as db:
        rows = db.execute("SELECT id,kind,name,expires,size FROM items WHERE expires>? ORDER BY rowid DESC",
                          (int(time.time()),)).fetchall()
    return jsonify([dict(zip(("id", "kind", "name", "expires", "size"), row)) for row in rows])


@app.post("/items")
@require_session
def create_item():
    kind = request.args.get("kind")
    minutes = request.args.get("minutes", "60")
    if not re.fullmatch(r"[0-9]{1,4}", minutes):
        abort(400)
    minutes = int(minutes)
    if kind not in {"text", "file"} or not 1 <= minutes <= 1440:
        abort(400)
    limit = MAX_TEXT if kind == "text" else MAX_FILE
    if request.content_length is None or request.content_length > limit:
        abort(413)
    content = request.get_data(cache=False)
    if not content:
        abort(400)
    if kind == "text":
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            abort(400)
    name = request.args.get("name", "")[:200]
    name = re.sub(r"[\x00-\x1f\x7f/\\]", "_", name).strip()
    name = name or ("Catatan" if kind == "text" else "Unduhan")
    with database(write=True) as db:
        used, count = db.execute("SELECT COALESCE(SUM(size),0),COUNT(*) FROM items").fetchone()
        if used + len(content) > QUOTA or count >= 1000:
            abort(507)
        db.execute("INSERT INTO items VALUES (?,?,?,?,?,?)", (
            secrets.token_hex(16), kind, name, int(time.time()) + minutes * 60,
            len(content), content,
        ))
    return "", 201


@app.get("/items/<item_id>")
@require_session
def read_item(item_id):
    with database() as db:
        row = db.execute("SELECT kind,name,content FROM items WHERE id=? AND expires>?",
                         (item_id, int(time.time()))).fetchone()
    if row is None:
        abort(404)
    kind, name, content = row
    if kind == "text":
        return app.response_class(content, content_type="text/plain; charset=utf-8")
    response = app.response_class(content, content_type="application/octet-stream")
    response.headers["Content-Disposition"] = "attachment; filename*=UTF-8''" + quote(name, safe="")
    return response


@app.delete("/items/<item_id>")
@require_session
def delete_item(item_id):
    with database(write=True) as db:
        db.execute("DELETE FROM items WHERE id=?", (item_id,))
    return "", 204


if __name__ == "__main__":
    command = sys.argv[1]
    if command == "init":
        initialize()
    elif command == "cleanup":
        cleanup()
    elif command == "reset":
        import base64
        key = secrets.token_bytes(20)
        temporary = SECRET.with_suffix(".new")
        os.umask(0o077)
        with temporary.open("xb") as handle:
            handle.write(key)
        temporary.replace(SECRET)
        with database(write=True) as db:
            for table in ("sessions", "totp", "attempts"):
                db.execute(f"DELETE FROM {table}")
        params = urlencode({
            "secret": base64.b32encode(key).decode(), "issuer": "Transit Privat",
        })
        sys.stdout.write(f"otpauth://totp/Transit%20Privat:VPS?{params}")
    else:
        raise SystemExit("Perintah: init, cleanup, reset")
