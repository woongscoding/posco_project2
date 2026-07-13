"""편집 패널: P-GPT 챗봇(Claude API) 대화 UI + 자동배치 버튼(헤더용).

우측 컬럼은 P-GPT 전용이다 — 조직도를 보면서 대화로 배치를 조정한다.
자동배치 버튼은 render_auto_place_button()으로 분리되어 헤더에 놓인다.
후보 추천근거는 조직도 카드 호버 팝업(org_dnd/index.html)으로 이동했다.

모든 조작은 st.session_state["placement"] (단일 source of truth)를 갱신하고,
갱신 시 즉시 st.rerun()하여 조직도가 다시 그려지도록 한다.
"""
from pathlib import Path

import streamlit as st

from logic import chat_logger
from logic import nlp_agent
from logic import placement as pl

# 챗봇 아바타: 파란 원 + 흰색 P (POSCO P-GPT 브랜딩)
_PGPT_AVATAR = str(Path(__file__).parent.parent / "assets" / "pgpt_avatar.svg")


def _record(history, role, text):
    """대화 히스토리에 추가하면서, 설정돼 있으면 로컬 수집 서버로도 전송한다.
    (수집 서버 미설정·오류 시에도 대화 흐름에는 영향 없음)"""
    history.append({"role": role, "text": text})
    chat_logger.log_turn(role, text)


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
    if not commands:
        commands.append("공석인 포지션에 적합한 후보를 배치해줘")
    # 인사이트 예시 — 단순 이동 외 능력 시연용. 추천 문구는 총 2개만 노출한다.
    commands.append("현재 배치안의 리스크를 분석해줘")
    return commands[:2]


_TRACK_LABEL = {"A": "임원·부장·리더", "B": "일반직원"}


def _run_auto_place(data, slots, tracks):
    """지정한 트랙들의 공석을 자동으로 채운다. 확정된 트랙은 건드리지 않는다."""
    confirmed = st.session_state.get("confirmed", {})
    tracks = [t for t in tracks if not confirmed.get(t)]
    state = st.session_state["placement"]
    counts = {}
    for t in tracks:
        state, changes = pl.auto_place(state, data["people_df"], data["fit_matrix"], t, slots=slots)
        counts[t] = len(changes)
    total = sum(counts.values())
    if total:
        detail = ", ".join(f"{_TRACK_LABEL[t]} {n}건" for t, n in counts.items())
        set_placement(state, [("toast", f"{total}건 자동 배치 완료 ({detail})")])
    else:
        st.session_state.setdefault("flash", []).append(("info", "추가로 배치할 공석/후보가 없습니다."))
    st.rerun()


def render_track_auto_place_button(data, slots, track):
    """현재 트랙 전용 자동배치 버튼 (임원 자동배치 / 직원 자동배치)."""
    confirmed = st.session_state.get("confirmed", {})
    label = "임원 자동배치" if track == "A" else "직원 자동배치"
    if st.button(f"⚡ {label}", key="auto_place_track", type="primary", width="stretch",
                 disabled=confirmed.get(track, False),
                 help=f"{_TRACK_LABEL[track]} 트랙의 공석만 자동으로 채웁니다."):
        _run_auto_place(data, slots, [track])


def render_auto_place_button(data, slots, key="auto_place_all"):
    """전체 자동배치 버튼 (두 트랙 공석 일괄 채움, 확정된 트랙은 제외)."""
    confirmed = st.session_state.get("confirmed", {})
    if st.button("⚡ 전체 자동배치", key=key, width="stretch",
                 disabled=confirmed.get("A", False) and confirmed.get("B", False),
                 help="임원·부장·리더 + 일반직원 두 트랙의 모든 공석을 한 번에 채웁니다."):
        _run_auto_place(data, slots, ["A", "B"])


def render_clear_all_button(data, slots, key="clear_all"):
    """전체 공석화 버튼: 배치 전원을 미배치 트레이로 되돌리고 확정 상태도 초기화."""
    if st.button("🗑 전체 공석화", key=key, width="stretch",
                 help="모든 슬롯을 공석으로 되돌리고 전원을 미배치 트레이로 보냅니다. 확정 상태도 초기화됩니다."):
        new_state = pl.clear_all_placements(st.session_state["placement"])
        st.session_state["confirmed"] = {"A": False, "B": False}
        set_placement(new_state, [("toast", "전체 인원을 공석(미배치)으로 되돌렸습니다.")])
        st.rerun()


def _run_chat_command(command, data, slots):
    """챗봇 명령/질문 1건을 처리해 대화 히스토리에 결과를 남기고 rerun한다.
    이동 명령·조건부 배치(암묵지 조건)·인사이트 질문을 모두 지원한다."""
    history = st.session_state["chat_history"]
    _record(history, "user", command)

    with st.spinner("P-GPT가 검토 중입니다..."):
        reply, actions, err = nlp_agent.ask_agent(
            command, st.session_state["placement"], data["people_df"], slots
        )
    if err:
        _record(history, "assistant", f"⚠️ {err}")
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

    _record(history, "assistant", "\n\n".join(parts) or "응답이 없습니다.")
    st.rerun()


# 실제 대화가 시작되기 전 채팅창을 채우는 목업 대화 (스크롤 동작 확인용)
_MOCK_CHAT = [
    ("user", "공석인 포지션 현황 알려줘"),
    ("assistant",
     "현재 임원·부장·리더 트랙의 공석 현황을 확인했습니다. "
     "조직도에서 빨간 점선 카드가 공석 포지션이며, 카드에 마우스를 올리면 "
     "적임자 Agent가 추천하는 후보 TOP3와 적합도 점수를 바로 확인할 수 있습니다."),
    ("user", "평가 하락 추세인 사람은 제외하고 배치해줘"),
    ("assistant",
     "네, 최근 4개년 평가가 하락 추세인 인원을 제외한 배치안을 구성할 수 있습니다. "
     "조건을 확정해 주시면 해당 조건으로 공석을 채우고 결과를 요약해 드리겠습니다."),
]


def render_chat_panel(data, slots):
    """우측 전용 P-GPT 챗봇: 조직도를 보면서 자연어로 배치를 조정하는 대화 UI."""
    st.markdown(
        "<div style='display:flex; align-items:center; gap:8px; margin-bottom:4px;'>"
        "<span style='display:inline-flex; width:26px; height:26px; border-radius:50%;"
        " background:#0072CE; color:#fff; font-weight:800; align-items:center;"
        " justify-content:center; font-size:15px;'>P</span>"
        "<span style='font-size:1.05rem; font-weight:700; color:#003C71;'>P-GPT</span>"
        "</div>",
        unsafe_allow_html=True,
    )
    chatbot_on = nlp_agent.is_chatbot_available()
    if not chatbot_on:
        st.caption("⚠️ API 키가 설정되지 않아 P-GPT가 비활성화되었습니다. (자동배치·D&D는 정상 동작)")

    history = st.session_state.setdefault("chat_history", [])

    chat_box = st.container(height=420)
    with chat_box:
        with st.chat_message("assistant", avatar=_PGPT_AVATAR):
            st.markdown(
                "안녕하세요, **P-GPT**입니다.\n\n"
                "이동 지시뿐 아니라 **조건을 건 배치**"
                "(예: 평가 하락자는 제외하고 공석 채우기)와 "
                "**배치안 분석·리스크 진단**도 도와드립니다."
            )
        if not history:
            # 목업 대화 — 실제 대화가 시작되면 사라진다
            for role, text in _MOCK_CHAT:
                with st.chat_message(role, avatar=_PGPT_AVATAR if role == "assistant" else None):
                    st.markdown(text)
        for msg in history:
            avatar = _PGPT_AVATAR if msg["role"] == "assistant" else None
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["text"])

    example_commands = _example_commands(data, slots)
    example_clicked = None
    for i, cmd in enumerate(example_commands):
        if st.button(cmd, key=f"example_cmd::{i}", width="stretch", disabled=not chatbot_on):
            example_clicked = cmd

    # 카카오톡형 입력창: 넓은 멀티라인 입력 + 아래 전송 버튼
    with st.form(key="chat_command_form", clear_on_submit=True):
        user_command = st.text_area(
            "메시지 입력",
            placeholder="P-GPT에게 메시지를 입력하세요…",
            height=80,
            label_visibility="collapsed",
            disabled=not chatbot_on,
        )
        submitted = st.form_submit_button(
            "전송 ➤", type="primary", width="stretch", disabled=not chatbot_on
        )

    command = example_clicked or (user_command.strip() if submitted and user_command else None)
    if command:
        _run_chat_command(command, data, slots)
