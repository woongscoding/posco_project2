# 로컬 대화기록 수집 서버

여러 PC에서 각각 Streamlit 앱을 실행해도, 각 앱이 대화 한 턴씩을 **내 PC의 이
수집 서버**로 전송해 한곳(SQLite)에 모읍니다. 브라우저에서 바로 조회할 수 있습니다.

```
[다른 PC의 Streamlit 앱]  ──HTTP POST /log──▶  [내 PC: FastAPI 수집서버]  ──▶  chatlogs.db
                              (cloudflared 터널)                └─ 브라우저 http://localhost:8000/ 로 조회
```

---

## 1. 내 PC에서 수집 서버 실행

```bash
pip install -r logserver/requirements.txt

# (선택) 아무나 기록을 못 넣게 공유 토큰 지정 — 앱에도 같은 값을 설정해야 함
export CHAT_LOG_TOKEN=my-secret-1234          # Windows PowerShell: $env:CHAT_LOG_TOKEN="my-secret-1234"

# 저장소 루트에서 실행
uvicorn logserver.server:app --host 0.0.0.0 --port 8000
```

- 조회: 브라우저에서 <http://localhost:8000/>
- 원본 JSON: <http://localhost:8000/logs.json>
- 저장 파일: 실행 폴더의 `chatlogs.db` (경로는 `CHAT_LOG_DB`로 변경 가능)

## 2. 외부(다른 PC)에서 접근하도록 터널 열기

내 PC는 보통 외부에서 직접 접근이 안 되므로 **cloudflared 터널**로 공개 주소를 만듭니다.
(무설정 임시 터널 예시 — 계정 없이 바로 사용 가능)

```bash
# cloudflared 설치 후
cloudflared tunnel --url http://localhost:8000
```

실행하면 `https://<랜덤>.trycloudflare.com` 같은 공개 주소가 출력됩니다.
이 주소가 각 앱이 기록을 보낼 `CHAT_LOG_ENDPOINT` 입니다.

> 참고: `trycloudflare.com` 임시 주소는 실행할 때마다 바뀝니다. 고정 주소가 필요하면
> cloudflared named tunnel(무료, 도메인 필요) 또는 ngrok 고정 도메인을 쓰세요.
> **대화가 일어날 때 내 PC와 이 서버가 켜져 있어야** 기록이 저장됩니다(꺼져 있으면 그 턴은 유실).

## 3. 각 PC의 Streamlit 앱 설정

앱을 실행하는 각 PC에서 아래 값을 지정하면, 그 앱의 대화가 수집 서버로 전송됩니다.
설정하지 않으면 로깅은 그냥 꺼진 채 앱은 정상 동작합니다(기존과 동일).

`.env` (프로젝트 루트) 예시:

```env
CHAT_LOG_ENDPOINT=https://<랜덤>.trycloudflare.com
CHAT_LOG_TOKEN=my-secret-1234      # 서버에 토큰을 설정한 경우 동일하게
CHAT_LOG_MACHINE=집-노트북           # (선택) 뷰어에서 어느 PC인지 알아보기 쉬운 이름
```

또는 `.streamlit/secrets.toml`:

```toml
CHAT_LOG_ENDPOINT = "https://<랜덤>.trycloudflare.com"
CHAT_LOG_TOKEN = "my-secret-1234"
CHAT_LOG_MACHINE = "회사-데스크탑"
```

Streamlit Cloud에 배포한 인스턴스라면 **App settings → Secrets** 에 같은 키를 넣으면 됩니다.

## 동작/설계 메모

- 앱→서버 전송은 **백그라운드 스레드 + 4초 타임아웃**이라 UI를 막지 않습니다.
- 서버가 꺼져 있거나 오류가 나도 **대화는 정상 진행**되고 그 턴만 기록되지 않습니다.
- 대화는 브라우저 세션 단위(`session_id`)로 묶이고, `machine` 라벨로 어느 PC에서
  온 대화인지 구분해 뷰어에 표시됩니다.
