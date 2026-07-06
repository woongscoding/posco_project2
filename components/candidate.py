"""후보/추천근거 패널 — 소프트인 벤치마크.

트랙 A: 후계자(후임)·세션 결과가 핵심 근거.
트랙 B: 평가 추이·적합도가 핵심 근거 (적임자 Agent 출처 라벨).
"""
import pandas as pd
import streamlit as st

from data.dummy_data import compute_fit_score
from logic.placement import compute_core_talent_pool

EVAL_TREND_COLS = ["25년평가", "24년평가", "23년평가", "22년평가"]


def _trend_str(row):
    return " → ".join(row[c] for c in EVAL_TREND_COLS[::-1])


def _rationale_block(row, score, source_label="적임자 Agent"):
    st.markdown(f"**{row['성명']}** · {row['직급']} · {row.get('현직책') or '-'}")
    st.progress(min(max(score, 0), 100) / 100, text=f"적합도 {score}점 (출처: {source_label})")

    c1, c2 = st.columns(2)
    with c1:
        st.caption("평가 추이 (22→25)")
        st.write(_trend_str(row))
        st.caption("다면평가 (24/25)")
        st.write(f"{row['24다면평가']} / {row['25다면평가']}")
        st.caption("직급경력 · 현직책경력")
        st.write(f"{row['직급경력']}년 · {row['현직책경력']}년")
    with c2:
        st.caption("부장세션 / 임원세션")
        st.write(f"{row['부장세션']} / {row['임원세션']}")
        st.caption("출신교 · 전공 (참고)")
        st.write(f"{row['출신교(대학)']} · {row['전공']}")
        st.caption("후임 지정 여부")
        st.write("후임 확정" if row.get("_is_successor") else "-")

    st.caption("보직의견")
    st.write(row["보직의견"])
    st.caption("HR검토의견")
    st.write(row["HR검토의견"])
    st.markdown("---")


def render_track_a_candidates(data, slots, state):
    st.markdown("##### 후계자 / 후보 추천근거")
    a_slots = [s for s in slots if s["track"] == "A"]
    labels = [s["직책명"] for s in a_slots]
    label_to_slot = {s["직책명"]: s for s in a_slots}

    chosen_label = st.selectbox("포지션 선택", labels, key="candidate_position_select")
    slot = label_to_slot[chosen_label]
    position_id = slot["position_id"]

    people_df = data["people_df"]
    current_emp = state["occupant"].get(slot["slot_id"])
    if current_emp:
        current_row = people_df[people_df["직번"] == current_emp].iloc[0]
        st.info(f"현재 배치: **{current_row['성명']}** ({current_row['직급']})")
    else:
        st.warning("현재 공석입니다.")

    candidates = people_df[
        (people_df["level"] == slot["level"])
        & (people_df["직번"] != (current_emp or ""))
    ].copy()
    candidates["_is_successor"] = candidates["후임"] == position_id
    candidates = candidates[
        candidates["_is_successor"] | (candidates["current_position_id"] == "")
    ]
    if candidates.empty:
        st.caption("추천 가능한 후보가 없습니다.")
        return

    candidates["_score"] = candidates.apply(lambda r: compute_fit_score(r, slot), axis=1)
    candidates = candidates.sort_values(["_is_successor", "_score"], ascending=[False, False]).head(4)

    for _, row in candidates.iterrows():
        source = "적임자 Agent (후계자 지정)" if row["_is_successor"] else "적임자 Agent (대체 후보)"
        _rationale_block(row, int(row["_score"]), source)


def render_track_b_candidates(data, slots, state):
    st.markdown("##### 핵심인재 후보군 (상위 50%) 추천근거")
    people_df = data["people_df"]
    leader_slots = [s for s in slots if s["track"] == "A" and s["level"] == "리더"]
    team_labels = [s["담당"] for s in leader_slots]
    label_to_slot = {s["담당"]: s for s in leader_slots}

    chosen_team = st.selectbox("담당(팀) 선택", team_labels, key="candidate_team_select")
    team_slot = label_to_slot[chosen_team]

    dept = team_slot["부서명"]
    core_pool = compute_core_talent_pool(people_df)

    staff = people_df[(people_df["level"] == "직원") & (people_df["부서명"] == dept)].copy()
    staff["_score"] = staff.apply(lambda r: compute_fit_score(r, team_slot), axis=1)
    staff["_is_successor"] = False
    staff = staff[staff["직번"].isin(core_pool)]
    staff = staff.sort_values("_score", ascending=False).head(5)

    if staff.empty:
        st.caption("해당 부서에 핵심인재 후보가 없습니다.")
        return

    st.caption(f"'{dept}' 부서명 소속 일반직원 상위 50% (평가 구성점수 기준)")
    for _, row in staff.iterrows():
        _rationale_block(row, int(row["_score"]), "적임자 Agent (핵심인재 Pool)")


def render_candidate_panel(track, data, slots, state):
    if track == "A":
        render_track_a_candidates(data, slots, state)
    else:
        render_track_b_candidates(data, slots, state)
