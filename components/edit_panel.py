"""편집 패널: 챗봇(Claude API) 대화 UI + 자동배치 버튼(헤더용).

우측 컬럼은 챗봇 전용이다 — 조직도를 보면서 대화로 배치를 조정한다.
자동배치 버튼은 render_auto_place_button()으로 분리되어 헤더에 놓인다.
후보 추천근거는 조직도 카드 호버 팝업(org_dnd/index.html)으로 이동했다.

모든 조작은 st.session_state["placement"] (단일 source of truth)를 갱신하고,
갱신 시 즉시 st.rerun()하여 조직도가 다시 그려지도록 한다.
"""
import streamlit as st

from logic import nlp_agent
from logic import placement as pl


def set_placement(new_state, flash_msgs=None):
    """배치 상태 갱신의 단일 통로. placement_rev를 올려 조직도/위젯이
    다음 rerun에서 새 상태 기준으로 다시 그려지게 한다."""
    st.session_state["placement"] = new_state
    st.session_state["placement_rev"] = st.session_state.get("placement_rev", 0) + 1
    if flash_msgs:
        st.session_state.setdefault("flash", []).extend(flash_msgs)


def _example_commands(data, slots):
    """현재 배치 상태에서 실제로 실행 가능한 예시 명령을 만든다.
    (하드코딩 예시는 seed 데이터와 어긋나 레벨 불일치/미존재 인물 오류를 냈음)"""
    state = st.session_state["placement"]
    people_by_id = data["people_df"].set_index("직번").to_dict("index")
    a_slots = [s for s in slots if s["track"] == "A"]
    unplaced_by_level = {}
    for eid in state["unplaced"]:
        p = people_by_id.get(eid)
        if p and p["level"] in ("임원", "부장", "리더"):
            unplaced_by_level.setdefault(p["level"], []).append(p["성명"])

    commands = []
    for s in a_slots:  # 공석 채우기 예시
        if state["occupant"].get(s["slot_id"]) is None and unplaced_by_level.get(s["level"]):
            commands.append(f"공석인 {s['직책명']} 자리에 {unplaced_by_level[s['level']][0]}을(를) 배치해줘")
            break
    for s in a_slots:  # 교체 예시
        occ = state["occupant"].get(s["slot_id"])
        if occ:
            occ_name = people_by_id[occ]["성명"]
            others = [n for n in unplaced_by_level.get(s["level"], []) if n != occ_name]
            if others:
                commands.append(f"{s['직책명']}은 {occ_name} 대신 {others[0]}(으)로 교체해줘")
                break
    if not commands:
        commands.append("공석인 포지션에 적합한 후보를 배치해줘")
    commands = commands[:2]
    # 인사이트/조건부 배치(암묵지 조건) 예시 — 단순 이동 외 능력 시연용
    commands.append("평가 하락 추세인 사람은 제외하고 공석을 채워줘")
    commands.append("현재 배치안의 리스크를 분석해줘")
    return commands


def render_auto_place_button(data, slots, key="auto_place_all"):
    """전체 자동배치 버튼 (헤더 배치용, 두 트랙 공석 일괄 채움)."""
    if st.button("⚡ 전체 자동배치", key=key, type="primary", width="stretch",
                 help="임원·부장·리더 + 일반직원 두 트랙의 모든 공석을 한 번에 채웁니다."):
        state = st.session_state["placement"]
        state_a, changes_a = pl.auto_place(
            state, data["people_df"], data["fit_matrix"], "A", slots=slots
        )
        state_b, changes_b = pl.auto_place(
            state_a, data["people_df"], data["fit_matrix"], "B", slots=slots
        )
        total = len(changes_a) + len(changes_b)
        if total:
            set_placement(state_b, [(
                "toast",
                f"{total}건 자동 배치 완료 (임원·부장·리더 {len(changes_a)}건, 일반직원 {len(changes_b)}건)",
            )])
        else:
            st.session_state.setdefault("flash", []).append(("info", "추가로 배치할 공석/후보가 없습니다."))
        st.rerun()


def _run_chat_command(command, data, slots):
    """챗봇 명령/질문 1건을 처리해 대화 히스토리에 결과를 남기고 rerun한다.
    이동 명령·조건부 배치(암묵지 조건)·인사이트 질문을 모두 지원한다."""
    history = st.session_state["chat_history"]
    history.append({"role": "user", "text": command})

    with st.spinner("Claude가 검토 중입니다..."):
        reply, actions, err = nlp_agent.ask_agent(
            command, st.session_state["placement"], data["people_df"], slots
        )
    if err:
        history.append({"role": "assistant", "text": f"⚠️ {err}"})
        st.rerun()

    valid_actions, warnings = nlp_agent.validate_actions(actions, data["people_df"], slots)

    parts = []
    if reply:
        parts.append(reply)

    if valid_actions:
        people_by_id = data["people_df"].set_index("직번").to_dict("index")
        slot_by_id = {s["slot_id"]: s for s in slots}
        state = st.session_state["placement"]
        lines = []
        for va in valid_actions:
            state, _ = pl.move_person(state, va["emp_id"], va["slot_id"])
            name = people_by_id.get(va["emp_id"], {}).get("성명", va["emp_id"])
            title = slot_by_id.get(va["slot_id"], {}).get("직책명", va["slot_id"])
            lines.append(f"- **{name}** → {title}")
        parts.append(f"✅ {len(valid_actions)}건의 이동을 반영했습니다.\n" + "\n".join(lines))
        set_placement(state)
    elif actions and not valid_actions:
        pass  # 전부 검증 탈락 → 경고만 표시
    elif not reply:
        parts.append("수행할 이동이 없습니다.")

    if warnings:
        parts.append("\n".join(f"⚠️ {w}" for w in warnings))

    history.append({"role": "assistant", "text": "\n\n".join(parts) or "응답이 없습니다."})
    st.rerun()


def render_chat_panel(data, slots):
    """우측 전용 챗봇: 조직도를 보면서 자연어로 배치를 조정하는 대화 UI."""
    st.markdown("##### 💬 AI 배치 어시스턴트")
    chatbot_on = nlp_agent.is_chatbot_available()
    if not chatbot_on:
        st.caption("⚠️ Claude API 키가 설정되지 않아 챗봇이 비활성화되었습니다. (자동배치·D&D는 정상 동작)")

    history = st.session_state.setdefault("chat_history", [])

    chat_box = st.container(height=430)
    with chat_box:
        if not history:
            with st.chat_message("assistant"):
                st.markdown(
                    "안녕하세요, 인재 배치 어시스턴트입니다.\n\n"
                    "이동 지시뿐 아니라 **조건을 건 배치**"
                    "(예: 평가 하락자는 제외하고 공석 채우기)와 "
                    "**배치안 분석·리스크 진단**도 도와드립니다."
                )
        for msg in history:
            with st.chat_message(msg["role"]):
                st.markdown(msg["text"])

    example_commands = _example_commands(data, slots)
    example_clicked = None
    for i, cmd in enumerate(example_commands):
        if st.button(cmd, key=f"example_cmd::{i}", width="stretch", disabled=not chatbot_on):
            example_clicked = cmd

    with st.form(key="chat_command_form", clear_on_submit=True):
        in_col, btn_col = st.columns([4, 1])
        user_command = in_col.text_input(
            "이동 명령",
            placeholder="이동 명령을 입력하세요",
            label_visibility="collapsed",
            disabled=not chatbot_on,
        )
        submitted = btn_col.form_submit_button("전송", disabled=not chatbot_on)

    command = example_clicked or (user_command.strip() if submitted and user_command else None)
    if command:
        _run_chat_command(command, data, slots)
