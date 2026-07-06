# 맞춤형 인재 시뮬레이션 Agent (PoC 목업)

HR AX 프로젝트 — 정기인사 배치 시뮬레이션을 시연하기 위한 Streamlit 목업입니다.
Simulation Agent 하나만 다루며, 조직도(명함형)의 가독성과 완성도가 최우선입니다.

**조직도 자체가 Drag&Drop 표면입니다** — 카드 속 인물(또는 트레이 후보)을 드래그해
다른 포지션 카드에 놓으면 이동되고, 점유된 자리에 놓으면 기존 인원이 미배치
트레이로 밀려납니다. 우측 패널에서 후보 추천근거를 보면서 시뮬레이션합니다.

## 1. 실행 방법

```bash
pip install -r requirements.txt
streamlit run app.py
```

조직도는 자체 HTML/CSS 커스텀 컴포넌트(`components/org_dnd/`)로 렌더링되므로
별도 설치가 필요 없습니다.

## 2. Claude API 키 설정 (선택 — 챗봇 기능)

키가 없어도 자동배치 · Drag&Drop 기능은 정상 동작합니다(②챗봇만 비활성화).

**로컬 실행 (권장)**: 프로젝트 루트에 `.env` 파일 생성 — 따옴표 없이:

```env
ANTHROPIC_API_KEY=sk-ant-api03-...
```

또는 `.streamlit/secrets.toml` (TOML이므로 여기는 따옴표 필요):

```toml
ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

또는 환경변수:

```powershell
$env:ANTHROPIC_API_KEY = "sk-ant-api03-..."
```

`.env`와 `secrets.toml`은 `.gitignore`에 등록되어 있습니다(커밋 금지).

**Streamlit Community Cloud 배포 시**: 앱 설정 → Secrets 에 위 TOML 내용을 동일하게 등록합니다.

## 3. 배포 시 참고 (Streamlit Community Cloud)

- 조직도 렌더링은 클라이언트(브라우저)에서 이루어지므로 서버 측 apt 패키지는 필수가
  아닙니다. `packages.txt`는 만약을 위해 유지합니다.
- 조직도 폰트는 font-family 스택("Malgun Gothic, NanumGothic, …")으로, 보는 사람의
  OS에 맞는 한글 폰트가 자동 적용됩니다.
- 배포 시 Secrets에 `ANTHROPIC_API_KEY`를 등록하면 챗봇이 활성화됩니다.

## 4. 데모 / 스크린샷 시나리오

장표에 넣을 스크린샷은 아래 순서로 확보하는 것을 권장합니다.

1. **트랙 A(임원·부장·리더)** 선택 → 초기 화면(일부 공석 빨강) 스크린샷
2. **① 자동배치** 클릭 → 조직도가 채워지는 화면(후계자/후보 반영) 스크린샷
3. 우측 **후보/추천근거 패널**에서 포지션 선택 → 후계자 근거(세션 결과·평가 추이) 스크린샷
4. **② 챗봇**의 예시 명령 버튼(현재 배치 상태에 맞게 자동 생성됨) 실행 → 변경된 조직도 스크린샷
5. **③ 조직도에서 직접 Drag&Drop** — 카드 속 인물을 끌어 다른 포지션 카드에 놓기 →
   기존 점유자가 미배치 트레이로 밀려나는 화면 스크린샷
6. 현재 배치를 **v1**로 저장 → 몇 가지 조정 후 **v2**로 저장 → **버전 비교** 표/변경목록 스크린샷
7. **트랙 B(일반직원)** 전환 → 리더 카드 안 팀원 로스터(핵심인재 ★보라, 공석 빨강)와 TO 충족
   뱃지가 표시된 조직도 + 핵심인재 후보 패널 스크린샷

## 5. 파일 구조

```
app.py                        # 엔트리 (헤더, 트랙 토글, 버전 셀렉터, 레이아웃)
data/dummy_data.py            # 더미 데이터 (고정 seed, 1회 생성)
logic/placement.py            # 자동배치 + 이동 재계산 순수 로직
logic/versioning.py           # 스냅샷 저장 + 버전 비교
logic/nlp_agent.py            # Claude API 호출 + 파싱 + 액션 검증
components/org_dnd/index.html # 명함형 조직도 + Drag&Drop 커스텀 컴포넌트 (HTML/CSS/JS)
components/org_dnd_chart.py   # 조직도 payload 빌더 + 드롭 이벤트 처리
components/edit_panel.py      # ①자동배치 + ②챗봇 패널
components/candidate.py       # 후계자/후보군 + 추천근거 패널
components/org_chart.py       # (legacy) graphviz 정적 조직도 — 현재 미사용
requirements.txt
packages.txt                  # Streamlit Cloud apt 패키지 (선택)
```

## 6. 데이터 안내

모든 인력/조직 데이터는 **고정 seed(42)로 1회 생성된 가상 데이터**입니다(개인정보 없음, 성명은
"임원A/부장B/리더C" 형식). 실제 클라이언트 데이터의 컬럼 스키마(직번, 본부, 부서명, 담당, 평가,
후임, 조직개편안_25년/26년 등)를 반영했지만 값은 전부 가명입니다.
