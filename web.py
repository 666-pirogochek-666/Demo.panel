import os
import secrets
import uuid

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

import db

load_dotenv()
ADMIN_PASSWORD = os.environ["1234"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
UPLOADS = "uploads"
SESSION = secrets.token_urlsafe(32)  # после перезапуска панели нужно войти снова

os.makedirs(UPLOADS, exist_ok=True)
db.init()
app = FastAPI(title="Лид-бот")


def auth(request: Request):
    if request.cookies.get("sid") != SESSION:
        raise HTTPException(401, "unauthorized")


AUTH = [Depends(auth)]


def count(c, sql, *args):
    return c.execute(sql, args).fetchone()[0]


class Login(BaseModel):
    password: str


class Step(BaseModel):
    text: str = ""
    file_path: str = ""
    delay_sec: int = 0
    btn_text: str = ""
    btn_url: str = ""


class Reply(BaseModel):
    user_id: int
    text: str


class BotSettings(BaseModel):
    bot_enabled: bool


@app.get("/")
def index():
    return FileResponse("templates/admin.html")


@app.post("/api/login")
def login(body: Login):
    if not secrets.compare_digest(body.password, ADMIN_PASSWORD):
        raise HTTPException(403, "Неверный пароль")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("sid", SESSION, httponly=True, samesite="strict", max_age=60 * 60 * 24 * 14)
    return resp


@app.get("/api/stats", dependencies=AUTH)
def stats():
    with db.conn() as c:
        ev = lambda kind: count(c, "SELECT COUNT(*) FROM events WHERE kind=?", kind)
        return {
            "users": count(c, "SELECT COUNT(*) FROM users"),
            "starts": ev("start"),  # переходы в бота
            "clicks": ev("click"),  # нажатия по кнопкам
            "subs": ev("subscribe") - ev("unsubscribe"),
            "buttons": [dict(r) for r in c.execute("""
                SELECT s.btn_text AS label, COUNT(e.id) AS clicks
                FROM steps s LEFT JOIN events e
                  ON e.kind = 'click' AND e.ref = CAST(s.id AS TEXT)
                WHERE s.btn_url <> '' GROUP BY s.id ORDER BY s.pos, s.id""")],
            "daily": [dict(r) for r in c.execute("""
                SELECT date(created_at, 'unixepoch') AS day, COUNT(*) AS n
                FROM events WHERE kind = 'start' AND created_at > ?
                GROUP BY day ORDER BY day""", (db.now() - 14 * 86400,))],
        }


@app.get("/api/steps", dependencies=AUTH)
def get_steps():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM steps ORDER BY pos, id")]


@app.put("/api/steps", dependencies=AUTH)
def put_steps(steps: list[Step]):
    with db.conn() as c:
        ids = [r[0] for r in c.execute("SELECT id FROM steps ORDER BY pos, id")]
        for i, s in enumerate(steps):
            vals = (i, s.text, s.file_path, s.delay_sec, s.btn_text, s.btn_url)
            if i < len(ids):  # обновляем на месте, чтобы сохранить статистику кнопок
                c.execute(
                    """UPDATE steps SET pos=?, text=?, file_path=?, delay_sec=?,
                       btn_text=?, btn_url=? WHERE id=?""",
                    (*vals, ids[i]),
                )
            else:
                c.execute(
                    """INSERT INTO steps (pos, text, file_path, delay_sec, btn_text, btn_url)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    vals,
                )
        for extra in ids[len(steps):]:
            c.execute("DELETE FROM steps WHERE id=?", (extra,))
    return {"ok": True}


@app.post("/api/upload", dependencies=AUTH)
async def upload(file: UploadFile):
    name = f"{uuid.uuid4().hex}_{os.path.basename(file.filename or 'file')}"
    path = os.path.join(UPLOADS, name)
    with open(path, "wb") as f:
        f.write(await file.read())
    return {"path": path}


@app.get("/api/users", dependencies=AUTH)
def users():
    with db.conn() as c:
        return [dict(r) for r in c.execute("""
            SELECT u.user_id, u.name, u.username, u.last_seen,
              (SELECT text FROM messages m WHERE m.user_id = u.user_id
               ORDER BY m.id DESC LIMIT 1) AS last_text
            FROM users u ORDER BY u.last_seen DESC""")]


@app.get("/api/dialog/{user_id}", dependencies=AUTH)
def dialog(user_id: int):
    with db.conn() as c:
        return [dict(r) for r in c.execute(
            "SELECT direction, text, created_at FROM messages WHERE user_id=? ORDER BY id",
            (user_id,),
        )]


@app.post("/api/send", dependencies=AUTH)
def send(body: Reply):
    r = httpx.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={"chat_id": body.user_id, "text": body.text},
        timeout=15,
    )
    if r.status_code != 200:
        raise HTTPException(400, "Telegram: " + r.json().get("description", "ошибка"))
    with db.conn() as c:
        db.log_msg(c, body.user_id, "out", body.text)
    return {"ok": True}


@app.get("/api/settings", dependencies=AUTH)
def get_settings():
    with db.conn() as c:
        return {"bot_enabled": count(c, "SELECT value FROM settings WHERE key='bot_enabled'") == "1"}


@app.put("/api/settings", dependencies=AUTH)
def put_settings(body: BotSettings):
    with db.conn() as c:
        c.execute(
            "UPDATE settings SET value=? WHERE key='bot_enabled'",
            ("1" if body.bot_enabled else "0",),
        )
    return {"ok": True}


@app.get("/r/{step_id}")
def go(step_id: int, u: int | None = None):
    """Кнопка в сообщении: считаем нажатие и переводим на нужную ссылку."""
    with db.conn() as c:
        row = c.execute("SELECT btn_url FROM steps WHERE id=?", (step_id,)).fetchone()
        if not row or not row["btn_url"]:
            raise HTTPException(404)
        db.log_event(c, u, "click", step_id)
    return RedirectResponse(row["btn_url"])
