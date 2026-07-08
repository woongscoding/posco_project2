"""챗봇(②) — 실제 Claude API 연동.

현재 배치 상태(JSON) + 사용자 명령 → Claude → 이동 액션 JSON만 반환 → 파싱 →
검증(emp/position 실재 확인) → 실행. 키가 없거나 호출이 실패하면 챗봇만
비활성화되고 나머지 기능(자동배치/D&D)은 정상 동작해야 한다(graceful degradation).
"""
import json
import os
import re

try:
    from dotenv import load_dotenv
    load_dotenv()  # 프로젝트 루트의 .env 파일을 os.environ으로 로드
except ImportError:
    pass

MODEL = "claude-sonnet-5"  # 없으면 최신 sonnet으로 교체

SYSTEM_PROMPT = """당신은 인사배치 시뮬레이션의 AI 어시스턴트입니다. 세 가지를 수행합니다:
① 이동 명령 수행: "A를 B 자리로 옮겨줘" 같은 명시적 이동
② 조건부 배치: "평가 하락 추세인 사람은 빼고 공석을 채워줘"처럼 정성적 조건(암묵지)을
   프로필 데이터로 검증해 만족하는 후보만 배치하고, 제외한 사람은 사유와 함께 설명
③ 인사이트: 현재 배치안의 리스크, 특정 인물의 적합성, 배치 근거 등 분석 답변

입력 JSON 구조:
- positions: 임원/부장/리더 포지션 목록.
  {"position": 직책명, "level": 임원|부장|리더, "occupant": 보임자 성명 또는 "공석", "occupant_profile": 프로필 또는 null}
- candidates: 미배치 후보 목록. 각 항목에 프로필 필드가 포함됨.
- 프로필 필드: grade(직급), eval_trend(22→25년 평가 추이), multi_eval(24/25 다면평가),
  session(부장세션/임원세션 결과), career(직급경력/현직책경력 년수), opinion(보직의견),
  hr_review(HR검토의견), successor_for(후임으로 지정된 직책명 또는 null)

응답 규칙 — 반드시 아래 형태의 JSON 객체 "하나만" 출력하세요 (코드펜스/다른 텍스트 금지):
{"reply": "<사용자에게 보여줄 한국어 답변>", "actions": [{"action": "move", "emp": "<성명>", "to": "<positions의 position 값>"}]}
- reply: 간결하게. 조건부 배치 시 누구를 왜 배치/제외했는지 근거(평가·세션·의견)를 명시.
  분석 요청이면 데이터에 근거한 인사이트를 작성. 목록이 필요하면 "- " 불릿 사용.
- actions: 실제 이동이 필요할 때만 채우고, 질문/분석만 요청받으면 빈 배열 [].
- positions/candidates에 실제로 존재하는 사람/포지션만 사용하세요. 임의로 만들지 마세요.
- 기본적으로 같은 level끼리 배치하되(임원↔임원, 부장↔부장, 리더↔리더), 사용자가 명시적으로
  요청하면 하위 level 인원을 상위 포지션에 배치(발탁)할 수 있습니다.
- 공석 채우기는 successor_for가 해당 직책인 후보를 우선하되, 사용자 조건과 충돌하면 조건이 우선입니다.
- 데이터에 없는 사실을 지어내지 마세요. 판단 근거는 반드시 입력 프로필에서 인용하세요.
"""


def _get_client():
    try:
        import anthropic
    except ImportError:
        return None

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        try:
            import streamlit as st
            api_key = st.secrets.get("ANTHROPIC_API_KEY")
        except Exception:
            api_key = None
    if not api_key:
        return None
    return anthropic.Anthropic(api_key=api_key)


def is_chatbot_available():
    return _get_client() is not None


def _extract_json_object(text):
    """응답에서 {"reply":..., "actions":[...]} 객체를 최대한 관대하게 추출."""
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    # 구버전 호환: 액션 배열만 온 경우
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if match:
        try:
            actions = json.loads(match.group(0))
            if isinstance(actions, list):
                return {"reply": "", "actions": actions}
        except json.JSONDecodeError:
            pass
    return None


def _person_brief(p, title_by_pos):
    """인사이트/조건부 배치 판단에 필요한 인물 프로필 요약(암묵지 재료)."""
    succ_pos = p.get("후임")
    return {
        "name": p["성명"],
        "level": p["level"],
        "grade": p.get("직급"),
        "eval_trend": " → ".join(
            str(p.get(c, "-")) for c in ("22년평가", "23년평가", "24년평가", "25년평가")
        ),
        "multi_eval": f"{p.get('24다면평가', '-')} / {p.get('25다면평가', '-')}",
        "session": f"{p.get('부장세션', '-')} / {p.get('임원세션', '-')}",
        "career": f"직급 {p.get('직급경력', 0)}년 · 현직책 {p.get('현직책경력', 0)}년",
        "opinion": p.get("보직의견", ""),
        "hr_review": p.get("HR검토의견", ""),
        "successor_for": title_by_pos.get(succ_pos) if succ_pos and succ_pos != "-" else None,
    }


def _build_context_snapshot(state, people_df, slots):
    """챗봇에 전달할 컨텍스트: 트랙 A 포지션 현황(보임자 프로필 포함) +
    미배치 후보 목록(프로필 포함). 프로필이 있어야 '평가 하락자는 제외'류의
    정성적 조건 판단과 인사이트 답변이 가능하다."""
    slot_lookup = {s["slot_id"]: s for s in slots}
    people_by_id = people_df.set_index("직번").to_dict("index")
    title_by_pos = {s["slot_id"]: s["직책명"] for s in slots if s["track"] == "A"}

    positions = []
    for sid, emp_id in state["occupant"].items():
        slot = slot_lookup.get(sid, {})
        if slot.get("track") != "A":
            continue  # 챗봇 조정 대상은 임원/부장/리더 포지션(트랙 A)
        person = people_by_id.get(emp_id) if emp_id else None
        positions.append({
            "position": slot.get("직책명") or sid,
            "level": slot.get("level"),
            "occupant": person["성명"] if person else "공석",
            "occupant_profile": _person_brief(person, title_by_pos) if person else None,
        })

    candidates = []
    for eid in state["unplaced"]:
        p = people_by_id.get(eid)
        if not p or p.get("level") not in ("임원", "부장", "리더"):
            continue
        candidates.append(_person_brief(p, title_by_pos))

    return {"positions": positions, "candidates": candidates}


def ask_agent(user_command, state, people_df, slots):
    """사용자 명령/질문 → (답변 텍스트, 검증 전 액션 리스트, 에러).
    이동 명령·조건부 배치·인사이트 질문을 모두 처리한다."""
    client = _get_client()
    if client is None:
        return None, None, "Claude API 키가 설정되지 않아 챗봇을 사용할 수 없습니다."

    snapshot = _build_context_snapshot(state, people_df, slots)
    try:
        response = client.messages.create(
            model=MODEL,
            # sonnet-5는 thinking 생략 시 adaptive thinking이 기본 —
            # 출력 토큰이 추론에 소진돼 빈 응답이 되므로 명시적으로 끈다.
            # (구조화 JSON 생성 작업이라 thinking 불필요 + 데모 응답속도 확보)
            thinking={"type": "disabled"},
            max_tokens=8000,
            # 응답을 {"reply","actions"} 스키마로 강제 → 파싱 실패 원천 차단
            output_config={
                "format": {
                    "type": "json_schema",
                    "schema": {
                        "type": "object",
                        "properties": {
                            "reply": {"type": "string"},
                            "actions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "action": {"type": "string", "const": "move"},
                                        "emp": {"type": "string"},
                                        "to": {"type": "string"},
                                    },
                                    "required": ["action", "emp", "to"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["reply", "actions"],
                        "additionalProperties": False,
                    },
                }
            },
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": (
                    f"[현재 배치 상태]\n{json.dumps(snapshot, ensure_ascii=False)}\n\n"
                    f"[사용자 명령]\n{user_command}"
                ),
            }],
        )
    except Exception as e:
        return None, None, f"Claude API 호출 실패: {e}"

    text = "".join(b.text for b in response.content if b.type == "text")
    parsed = _extract_json_object(text)
    if parsed is None:
        return None, None, "응답에서 유효한 JSON을 찾지 못했습니다."
    reply = str(parsed.get("reply") or "").strip()
    actions = parsed.get("actions") or []
    if not isinstance(actions, list):
        actions = []
    return reply, actions, None


def get_move_actions(user_command, state, people_df, slots):
    """(구 인터페이스 호환) 사용자 명령 → 액션 리스트만 반환."""
    reply, actions, err = ask_agent(user_command, state, people_df, slots)
    if err:
        return None, err
    return actions, None


def validate_actions(actions, people_df, slots):
    """액션의 emp/position 실재 + 트랙 경계 확인. (유효 액션, 경고) 반환.
    임원/부장/리더는 트랙 A 어느 포지션으로든 이동 가능(발탁 배치 허용).
    일반직원(직원)을 트랙 A 포지션에 넣는 것만 차단한다."""
    name_to_emp = {}
    level_by_emp = {}
    for _, row in people_df.iterrows():
        name_to_emp.setdefault(row["성명"], row["직번"])
        name_to_emp[row["직번"]] = row["직번"]
        level_by_emp[row["직번"]] = row["level"]

    slot_by_title = {}
    for s in slots:
        if s["track"] != "A":
            continue
        slot_by_title.setdefault(s["직책명"], s["slot_id"])
        slot_by_title[s["slot_id"]] = s["slot_id"]

    valid_actions = []
    warnings = []
    for a in actions:
        if a.get("action") != "move":
            warnings.append(f"지원하지 않는 액션 유형: {a}")
            continue
        emp_key, to_key = a.get("emp"), a.get("to")
        emp_id = name_to_emp.get(emp_key)
        slot_id = slot_by_title.get(to_key)
        if not emp_id:
            warnings.append(f"'{emp_key}' 인물을 찾을 수 없어 이동을 건너뜁니다.")
            continue
        if not slot_id:
            warnings.append(f"'{to_key}' 포지션을 찾을 수 없어 이동을 건너뜁니다.")
            continue
        if level_by_emp.get(emp_id) == "직원":
            warnings.append(
                f"'{emp_key}'은(는) 일반직원이라 임원/부장/리더 포지션"
                f"('{to_key}')에 배치할 수 없어 건너뜁니다."
            )
            continue
        valid_actions.append({"emp_id": emp_id, "slot_id": slot_id, "raw": a})
    return valid_actions, warnings
