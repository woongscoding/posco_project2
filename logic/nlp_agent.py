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

SYSTEM_PROMPT = """당신은 인사배치 시뮬레이션의 배치 조정 어시스턴트입니다.
현재 배치 상태(JSON)와 사용자의 자연어 명령을 받아, 수행할 "이동" 액션만 JSON 배열로 반환합니다.

입력 JSON 구조:
- positions: 임원/부장/리더 포지션 목록. 각 항목은 {"position": 직책명, "level": 임원|부장|리더, "occupant": 현재 보임자 성명 또는 "공석"}.
- candidates: 미배치 후보 목록. 각 항목은 {"name": 성명, "level": 레벨, "grade": 직급, "successor_for": 후임으로 지정된 직책명 또는 null}.

규칙:
- 반드시 JSON 배열만 출력하세요. 설명, 코드펜스, 다른 텍스트를 포함하지 마세요.
- 각 액션은 {"action": "move", "emp": "<성명>", "to": "<positions의 position 값>"} 형태입니다.
- positions/candidates에 실제로 존재하는 사람/포지션만 사용하세요. 임의로 만들지 마세요.
- 기본적으로 같은 level끼리 배치하되(임원↔임원, 부장↔부장, 리더↔리더), 사용자가 명시적으로
  요청하면 하위 level 인원을 상위 포지션에 배치(발탁)할 수 있습니다.
- "공석에 배치해줘"류 명령은 occupant가 "공석"인 포지션에 successor_for가 그 포지션인 후보를 우선 배치하세요.
- 명령이 배치와 무관하거나 수행 불가능하면 빈 배열 []을 반환하세요.
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


def _extract_json_array(text):
    text = re.sub(r"```(?:json)?", "", text).strip()
    match = re.search(r"\[.*\]", text, re.DOTALL)
    if not match:
        return None
    try:
        return json.loads(match.group(0))
    except json.JSONDecodeError:
        return None


def _build_context_snapshot(state, people_df, slots):
    """챗봇에 전달할 컨텍스트: 트랙 A 포지션 현황 + 미배치 후보 목록.
    후보 정보가 없으면 '공석에 적합한 후보 배치'류 명령을 수행할 수 없다."""
    slot_lookup = {s["slot_id"]: s for s in slots}
    people_by_id = people_df.set_index("직번").to_dict("index")
    title_by_pos = {s["slot_id"]: s["직책명"] for s in slots if s["track"] == "A"}

    positions = []
    for sid, emp_id in state["occupant"].items():
        slot = slot_lookup.get(sid, {})
        if slot.get("track") != "A":
            continue  # 챗봇 조정 대상은 임원/부장/리더 포지션(트랙 A)
        occupant = people_by_id[emp_id]["성명"] if emp_id else "공석"
        positions.append({
            "position": slot.get("직책명") or sid,
            "level": slot.get("level"),
            "occupant": occupant,
        })

    candidates = []
    for eid in state["unplaced"]:
        p = people_by_id.get(eid)
        if not p or p.get("level") not in ("임원", "부장", "리더"):
            continue
        succ_pos = p.get("후임")
        candidates.append({
            "name": p["성명"],
            "level": p["level"],
            "grade": p.get("직급"),
            "successor_for": title_by_pos.get(succ_pos) if succ_pos and succ_pos != "-" else None,
        })

    return {"positions": positions, "candidates": candidates}


def get_move_actions(user_command, state, people_df, slots):
    """사용자 명령 → 파싱된 (검증 전) 액션 리스트. 실패 시 (None, 에러메시지)."""
    client = _get_client()
    if client is None:
        return None, "Claude API 키가 설정되지 않아 챗봇을 사용할 수 없습니다."

    snapshot = _build_context_snapshot(state, people_df, slots)
    try:
        response = client.messages.create(
            model=MODEL,
            max_tokens=1024,
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
        return None, f"Claude API 호출 실패: {e}"

    text = "".join(b.text for b in response.content if b.type == "text")
    actions = _extract_json_array(text)
    if actions is None:
        return None, "응답에서 유효한 JSON 액션을 찾지 못했습니다."
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
