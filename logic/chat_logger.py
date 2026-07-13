"""대화기록을 '내 로컬 수집 서버'로 전송하는 클라이언트.

여러 PC에서 각각 Streamlit을 실행해도, 각 인스턴스가 이 모듈을 통해
대화 한 턴(사용자/어시스턴트)을 로컬 수집 서버(FastAPI, logserver/)로
HTTP POST 한다. 로컬 서버는 cloudflared 등 터널로 공개 주소를 갖고,
그 주소를 CHAT_LOG_ENDPOINT 로 설정한다.

설계 원칙:
- **절대 UI를 막지 않는다**: 백그라운드 스레드 + 짧은 타임아웃.
- **절대 예외로 앱을 죽이지 않는다**: 모든 오류를 조용히 삼킨다.
- **설정이 없으면 아무 것도 안 한다**: CHAT_LOG_ENDPOINT 미설정 시 no-op.

의존성 없이 표준 라이브러리(urllib)만 사용한다.
"""
import json
import os
import socket
import threading
import urllib.request
import uuid

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _endpoint():
    """수집 서버의 /log 엔드포인트. 없으면 None(=로깅 비활성)."""
    ep = os.environ.get("CHAT_LOG_ENDPOINT")
    if not ep:
        try:
            import streamlit as st
            ep = st.secrets.get("CHAT_LOG_ENDPOINT")
        except Exception:
            ep = None
    return ep.rstrip("/") if ep else None


def _token():
    tok = os.environ.get("CHAT_LOG_TOKEN")
    if not tok:
        try:
            import streamlit as st
            tok = st.secrets.get("CHAT_LOG_TOKEN")
        except Exception:
            tok = None
    return tok


def _machine():
    """이 대화가 어느 PC에서 나왔는지 식별하는 라벨.
    CHAT_LOG_MACHINE 로 사람이 알아보기 쉬운 이름을 줄 수 있고,
    없으면 호스트명을 쓴다."""
    name = os.environ.get("CHAT_LOG_MACHINE")
    if name:
        return name
    try:
        return socket.gethostname()
    except Exception:
        return "unknown"


def get_session_id():
    """이 브라우저 세션의 대화 묶음 ID. session_state에 1회 생성해 재사용한다.
    (Streamlit 밖에서 호출되면 프로세스 단위 임시 ID로 대체)"""
    try:
        import streamlit as st
        sid = st.session_state.get("_chat_log_session_id")
        if not sid:
            sid = uuid.uuid4().hex
            st.session_state["_chat_log_session_id"] = sid
        return sid
    except Exception:
        return "no-session"


def is_logging_enabled():
    return _endpoint() is not None


def _post(url, payload, token):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json; charset=utf-8")
    if token:
        req.add_header("X-Log-Token", token)
    try:
        urllib.request.urlopen(req, timeout=4)
    except Exception:
        # 수집 서버가 꺼져 있거나 네트워크 오류 — 대화 흐름을 막지 않는다.
        pass


def log_turn(role, text, session_id=None, machine=None, ts=None):
    """대화 한 턴을 수집 서버로 비동기 전송한다. 설정 없으면 즉시 반환.

    role: "user" | "assistant"
    ts:   RFC3339/ISO 문자열(선택). 없으면 서버가 수신 시각을 찍는다.
    """
    endpoint = _endpoint()
    if not endpoint:
        return

    payload = {
        "session_id": session_id or get_session_id(),
        "machine": machine or _machine(),
        "role": role,
        "text": text,
    }
    if ts is not None:
        payload["ts"] = ts

    url = endpoint + "/log"
    token = _token()
    # 백그라운드로 던지고 UI는 즉시 진행.
    threading.Thread(target=_post, args=(url, payload, token), daemon=True).start()
