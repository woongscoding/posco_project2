"""편집 패널: ① 자동배치 버튼 ② 챗봇(Claude API).

③ Drag&Drop은 조직도 컴포넌트(components/org_dnd_chart.py)에서 직접 수행한다
— 조직도 카드 위에 드래그해 배치하는 방식(분리형 sortables 리스트 제거).

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
    return commands[:2]


def render_auto_place_section(track, data, slots):
    st.markdown("##### ① 자동배치")
    st.caption("한 번에 두 트랙(임원·부장·리더 + 일반직원)의 모든 공석을 채웁니다.")
    if st.button("전체 자동배치 — 모든 공석 채우기", key="auto_place_all",
                 type="primary", width="stretch"):
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


def render_chatbot_section(data, slots):
    st.markdown("##### ② 사용자 질의배치 (챗봇)")
    chatbot_on = nlp_agent.is_chatbot_available()
    if not chatbot_on:
        st.caption("⚠️ Claude API 키가 설정되지 않아 챗봇이 비활성화되었습니다. (자동배치·D&D는 정상 동작)")
    st.caption("챗봇은 임원/부장/리더 포지션(트랙 A)을 조정합니다.")

    example_commands = _example_commands(data, slots)
    example_clicked = None
    for i, cmd in enumerate(example_commands):
        if st.button(cmd, key=f"example_cmd::{i}", width="stretch", disabled=not chatbot_on):
            example_clicked = cmd

    with st.form(key="chat_command_form", clear_on_submit=True):
        user_command = st.text_input(
            "이동 명령을 입력하세요",
            placeholder=f"예: {example_commands[0]}",
            disabled=not chatbot_on,
        )
        submitted = st.form_submit_button("전송", disabled=not chatbot_on)

    command_to_run = example_clicked or (user_command if submitted else None)

    if command_to_run:
        with st.spinner("Claude가 배치안을 검토 중입니다..."):
            actions, err = nlp_agent.get_move_actions(
                command_to_run, st.session_state["placement"], data["people_df"], slots
            )
        if err:
            st.warning(err)
            return

        valid_actions, warnings = nlp_agent.validate_actions(actions, data["people_df"], slots)

        if valid_actions:
            state = st.session_state["placement"]
            for va in valid_actions:
                state, _ = pl.move_person(state, va["emp_id"], va["slot_id"])
            flash = [("toast", f"{len(valid_actions)}건의 이동을 반영했습니다.")]
            flash += [("warning", w) for w in warnings]
            set_placement(state, flash)
            st.rerun()
        else:
            for w in warnings:
                st.warning(w)
            if not warnings:
                st.info("수행할 이동이 없습니다.")


def render_edit_panel(track, data, slots):
    render_auto_place_section(track, data, slots)
    st.divider()
    render_chatbot_section(data, slots)
