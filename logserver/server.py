"""로컬 대화기록 수집 서버 (FastAPI + SQLite).

여러 PC에서 실행되는 Streamlit 앱들이 대화 한 턴씩 이 서버의 /log 로
POST 한다. 기록은 이 PC의 SQLite 파일(chatlogs.db)에 영구 저장되고,
브라우저에서 http://localhost:8000/ 로 열어 조회할 수 있다.

외부(다른 PC의 배포앱)에서 접근하게 하려면 cloudflared 터널로 이 서버를
공개 주소로 노출하고(README 참고), 그 주소를 각 앱의 CHAT_LOG_ENDPOINT 로
설정한다.

실행:
    pip install -r logserver/requirements.txt
    export CHAT_LOG_TOKEN=아무_비밀문자열   # (선택) 인증 토큰
    uvicorn logserver.server:app --host 0.0.0.0 --port 8000
"""
import html
import os
import sqlite3
import threading
from datetime import datetime, timezone

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

DB_PATH = os.environ.get("CHAT_LOG_DB", "chatlogs.db")
TOKEN = os.environ.get("CHAT_LOG_TOKEN")  # 설정하면 클라이언트도 같은 값을 보내야 함

app = FastAPI(title="대화기록 수집 서버")
_lock = threading.Lock()


def _db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db():
    with _db() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS logs (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         TEXT NOT NULL,
                session_id TEXT NOT NULL,
                machine    TEXT NOT NULL,
                role       TEXT NOT NULL,
                text       TEXT NOT NULL
            )
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_session ON logs(session_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_ts ON logs(ts)")


_init_db()


def _check_token(sent):
    if TOKEN and sent != TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


@app.post("/log")
async def log(request: Request, x_log_token: str = Header(default=None)):
    _check_token(x_log_token)
    try:
        data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid json")

    role = str(data.get("role", ""))[:32]
    text = data.get("text")
    session_id = str(data.get("session_id", "no-session"))[:128]
    machine = str(data.get("machine", "unknown"))[:128]
    if not text or role not in ("user", "assistant"):
        raise HTTPException(status_code=400, detail="role/text required")

    ts = data.get("ts") or datetime.now(timezone.utc).isoformat()

    with _lock, _db() as conn:
        conn.execute(
            "INSERT INTO logs (ts, session_id, machine, role, text) VALUES (?,?,?,?,?)",
            (ts, session_id, machine, role, str(text)),
        )
    return {"ok": True}


@app.get("/logs.json")
def logs_json(limit: int = 500, session_id: str = None, x_log_token: str = Header(default=None)):
    _check_token(x_log_token)
    q = "SELECT * FROM logs"
    params = []
    if session_id:
        q += " WHERE session_id = ?"
        params.append(session_id)
    q += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, min(limit, 5000)))
    with _db() as conn:
        rows = [dict(r) for r in conn.execute(q, params).fetchall()]
    return JSONResponse(list(reversed(rows)))


def _render_viewer():
    """세션(대화 묶음)별로 그룹핑해 최신순으로 보여주는 단순 HTML 뷰어."""
    with _db() as conn:
        sessions = conn.execute(
            """
            SELECT session_id, machine,
                   MIN(ts) AS started, MAX(ts) AS ended, COUNT(*) AS n
            FROM logs GROUP BY session_id ORDER BY MAX(id) DESC LIMIT 200
            """
        ).fetchall()
        rows = conn.execute("SELECT * FROM logs ORDER BY id ASC").fetchall()

    by_session = {}
    for r in rows:
        by_session.setdefault(r["session_id"], []).append(r)

    parts = [
        "<h1>💬 대화기록</h1>",
        f"<p class='meta'>총 세션 {len(sessions)}개 · DB: {html.escape(DB_PATH)}</p>",
    ]
    for s in sessions:
        sid = s["session_id"]
        parts.append("<details open>")
        parts.append(
            "<summary><b>{machine}</b> · {n}턴 · {started} ~ {ended} "
            "<span class='sid'>{sid}</span></summary>".format(
                machine=html.escape(s["machine"]),
                n=s["n"],
                started=html.escape((s["started"] or "")[:19]),
                ended=html.escape((s["ended"] or "")[:19]),
                sid=html.escape(sid[:8]),
            )
        )
        for m in by_session.get(sid, []):
            cls = "user" if m["role"] == "user" else "assistant"
            parts.append(
                "<div class='msg {cls}'><div class='role'>{role}</div>"
                "<div class='txt'>{txt}</div>"
                "<div class='t'>{t}</div></div>".format(
                    cls=cls,
                    role="🙋 사용자" if m["role"] == "user" else "🤖 어시스턴트",
                    txt=html.escape(m["text"]).replace("\n", "<br>"),
                    t=html.escape((m["ts"] or "")[:19]),
                )
            )
        parts.append("</details>")

    style = """
    <style>
      body { font-family: 'Malgun Gothic', sans-serif; max-width: 900px;
             margin: 24px auto; padding: 0 16px; color: #1A2B3C; }
      h1 { color: #003C71; }
      .meta { color: #7C93A9; font-size: 13px; }
      details { border: 1px solid #DCE6F0; border-radius: 8px; margin: 10px 0;
                padding: 8px 12px; background: #F7FAFD; }
      summary { cursor: pointer; color: #12406B; }
      .sid { color: #9FB3C8; font-size: 11px; margin-left: 6px; }
      .msg { margin: 8px 0; padding: 8px 10px; border-radius: 8px; }
      .msg.user { background: #E8F1FA; }
      .msg.assistant { background: #fff; border: 1px solid #E1EAF4; }
      .role { font-size: 11px; font-weight: bold; color: #4878A8; }
      .txt { margin: 2px 0; font-size: 14px; line-height: 1.5; }
      .t { font-size: 10px; color: #9FB3C8; text-align: right; }
    </style>
    """
    return "<!doctype html><meta charset='utf-8'><title>대화기록</title>" + style + "".join(parts)


@app.get("/", response_class=HTMLResponse)
def viewer():
    return _render_viewer()


@app.get("/health")
def health():
    return {"ok": True}
