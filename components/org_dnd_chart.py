"""조직도 자체가 Drag&Drop 표면인 명함형 조직도 커스텀 컴포넌트.

st.graphviz_chart(정적 SVG)로는 조직도 위 드래그가 불가능하므로, HTML/CSS
카드 트리를 그리는 경량 커스텀 컴포넌트(components/org_dnd/index.html)를 쓴다.
카드 위 드롭 → {"id","action","emp","slot"} 이벤트가 반환되고, 이 모듈이
검증 후 placement 로직을 호출한다. rerun 방어: 이벤트 id를 세션에 기억해
같은 이벤트를 두 번 처리하지 않는다.
"""
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from components.edit_panel import set_placement
from data.dummy_data import EVAL_NUMERIC, compute_fit_score
from logic import placement as pl
from logic.placement import badges_for_person

_component = components.declare_component(
    "org_dnd_chart", path=str(Path(__file__).parent / "org_dnd")
)

# POSCO 브랜드 톤: 딥 네이비(#003C71) 기조. 공석(빨강)·발탁(핑크) 등
# 의미 색상은 식별을 위해 유지한다.
COLOR_FILLED = "#003C71"            # 배치완료 카드 스트립 (POSCO 네이비)
COLOR_VACANT = "#c62828"            # 공석 (빨강 유지 — 반드시 눈에 띄어야 함)
COLOR_SUCCESSOR_BORDER = "#00A0E9"  # 후임확정 (스카이 블루)
DEFAULT_BORDER = "#2C4A66"          # 카드 기본 테두리 (네이비 그레이)
COLOR_TO_PARTIAL = "#F59E0B"        # TO 부분 충족 (앰버)
COLOR_CORE_TALENT = "#6a1b9a"       # 핵심인재 (보라 유지 — 블루와 구분)

BADGE_COLORS = {
    "후임확정": "#00A0E9",
    "승진": "#F57C00",
    "신규보임": "#0072CE",
    "순환": "#607D8B",
    "★ IDP부합": "#F9A825",
    "발탁": "#d81b60",
}

LEVEL_CHIP_COLORS = {"임원": "#002B5B", "부장": "#1B4F8A", "리더": "#4878A8", "직원": "#7C9CBF"}
LEVEL_RANK = {"임원": 3, "부장": 2, "리더": 1, "직원": 0}


EVAL_TREND_COLS = ["22년평가", "23년평가", "24년평가", "25년평가"]


def _base_profile(person):
    """인물 공통 프로필 필드 (배치/미배치 팝업에서 공용)."""
    return {
        "grade": person["직급"],
        "trend": " → ".join(str(person[c]) for c in EVAL_TREND_COLS),
        "multi": f"{person['24다면평가']} / {person['25다면평가']}",
        "sessions": f"{person['부장세션']} / {person['임원세션']}",
        "career": f"직급 {person['직급경력']}년 · 현직책 {person['현직책경력']}년",
        "edu": f"{person['출신교(대학)']} · {person['전공']}",
        "age": f"{person['연령']}세",
        "bojik": person.get("보직의견", ""),
        "hr": person.get("HR검토의견", ""),
    }


def _common_reasons(person):
    """포지션과 무관하게 성립하는 추천 근거들."""
    reasons = []
    if EVAL_NUMERIC.get(person["25년평가"], 0) > EVAL_NUMERIC.get(person["22년평가"], 0):
        reasons.append("최근 4개년 평가 상승 추세")
    for key in ("부장세션", "임원세션"):
        val = str(person.get(key, "-"))
        if val != "-" and ("확정" in val or "발탁" in val):
            reasons.append(f"{key} 결과: {val}")
    opinion = str(person.get("보직의견", ""))
    if "추천" in opinion or "발탁" in opinion:
        reasons.append("보직의견에서 차기 리더/발탁 추천")
    return reasons


def _profile_payload(slot, person, badges):
    """배치된 인물의 호버 팝업 데이터: 핵심 지표 + 추천이유 문장 목록."""
    fit = compute_fit_score(person, slot)

    reasons = []
    if "후임확정" in badges:
        reasons.append("해당 포지션의 후계자(후임)로 사전 지정된 인재")
    if "발탁" in badges:
        reasons.append(f"{person['직급']} 직급에서 상위 직책({slot['직책명']})으로 발탁 배치")
    reasons += _common_reasons(person)
    if not reasons:
        reasons.append(f"동일 레벨 후보군 중 적합도 상위 ({fit}점, 적임자 Agent)")

    profile = _base_profile(person)
    profile["fit"] = fit
    profile["reasons"] = reasons
    return profile


def _tray_targets(person, slots, state, title_by_pos):
    """미배치 인원의 추천 포지션 TOP3 (후임 지정 → 공석 → 적합도순)."""
    if person["level"] == "직원":
        scored = []
        for s in slots:
            if s["track"] != "A" or s["level"] != "리더":
                continue
            b_ids = [x["slot_id"] for x in slots
                     if x["track"] == "B" and x["position_id"] == s["position_id"]]
            free = sum(1 for sid in b_ids if state["occupant"].get(sid) is None)
            scored.append({
                "title": s["담당"], "score": compute_fit_score(person, s),
                "vacant": free > 0, "succ": False,
            })
    else:
        scored = [
            {
                "title": s["직책명"], "score": compute_fit_score(person, s),
                "vacant": state["occupant"].get(s["slot_id"]) is None,
                "succ": person.get("후임") == s["position_id"],
            }
            for s in slots
            if s["track"] == "A" and s["level"] == person["level"]
        ]
    scored.sort(key=lambda x: (x["succ"], x["vacant"], x["score"]), reverse=True)
    return scored[:3]


def _tray_profile(person, slots, state, title_by_pos):
    """미배치 인원의 호버 팝업 데이터: 프로필 + 추천 근거 + 추천 포지션 TOP3."""
    reasons = []
    succ_pos = person.get("후임")
    if succ_pos and succ_pos != "-" and succ_pos in title_by_pos:
        reasons.append(f"'{title_by_pos[succ_pos]}' 포지션의 후계자(후임)로 지정됨")
    reasons += _common_reasons(person)
    if not reasons:
        reasons.append("적임자 Agent 후보군 등록 인원")

    profile = _base_profile(person)
    profile["fit"] = None  # 배치 전이라 단일 적합도 없음 → 포지션별 점수로 표시
    profile["reasons"] = reasons
    profile["targets"] = _tray_targets(person, slots, state, title_by_pos)
    return profile


def _vacant_candidates(people_df, state, slot):
    """공석 카드 호버 시 보여줄 추천 후보 TOP3 (미배치 인원 중 후임 우선 → 적합도순)."""
    unplaced = set(state["unplaced"])
    pool = people_df[
        (people_df["level"] == slot["level"]) & (people_df["직번"].isin(unplaced))
    ].copy()
    if pool.empty:
        return []
    pool["_succ"] = pool["후임"] == slot["position_id"]
    pool["_score"] = pool.apply(lambda r: compute_fit_score(r, slot), axis=1)
    pool = pool.sort_values(["_succ", "_score"], ascending=[False, False]).head(3)
    return [
        {"name": r["성명"], "grade": r["직급"], "score": int(r["_score"]), "succ": bool(r["_succ"])}
        for _, r in pool.iterrows()
    ]


def _card_payload(slot, person, emp_id, track, roster=None, to_fill=None, candidates=None):
    vacant = person is None
    badges = badges_for_person(person, slot["position_id"]) if person else []
    # 자기 레벨보다 높은 직책에 배치된 경우 → 발탁 배치 표시
    if person is not None and LEVEL_RANK.get(person["level"], 0) < LEVEL_RANK.get(slot["level"], 0):
        badges.append("발탁")
    badge_items = [{"text": b, "color": BADGE_COLORS.get(b, "#757575")} for b in badges]
    if to_fill:
        filled, total = to_fill
        color = COLOR_FILLED if filled >= total else (
            COLOR_TO_PARTIAL if filled >= total / 2 else COLOR_VACANT
        )
        badge_items.append({"text": f"TO {filled}/{total}", "color": color})

    border = DEFAULT_BORDER
    if vacant:
        border = COLOR_VACANT
    elif "후임확정" in badges:
        border = COLOR_SUCCESSOR_BORDER

    if person is not None:
        profile = _profile_payload(slot, person, badges)
    else:
        profile = {"cands": candidates or []}

    return {
        "profile": profile,
        "slot_id": slot["slot_id"],
        "position_id": slot["position_id"],
        "level": slot["level"],
        "title": slot["직책명"],
        "name": person["성명"] if person else "공석",
        "sub": f"{person['직급']} · {slot['직책명']}" if person else slot["직책명"],
        "initial": person["성명"][-1] if person else "-",
        "path": " > ".join(p for p in [slot["본부"], slot["부서명"]] if isinstance(p, str) and p),
        "strip": COLOR_FILLED if person else COLOR_VACANT,
        "border": border,
        "vacant": vacant,
        "emp": emp_id,
        "draggable": bool(person) and track == "A",
        "badges": badge_items,
        "roster": roster or [],
    }


def build_org_payload(track, data, slots, state, core_talent_pool=None, scope="전체"):
    """positions 계층(본부>부서>담당)을 컴포넌트용 트리 JSON으로 변환."""
    people_by_id = data["people_df"].set_index("직번").to_dict("index")
    positions_df = data["positions_df"]
    core_talent_pool = core_talent_pool or set()
    a_slots = {s["slot_id"]: s for s in slots if s["track"] == "A"}
    title_by_pos = {sid: s["직책명"] for sid, s in a_slots.items()}

    def node_for(pos_id):
        slot = a_slots[pos_id]
        emp_id = state["occupant"].get(pos_id)
        person = people_by_id.get(emp_id) if emp_id else None
        candidates = None
        if person is None:
            candidates = _vacant_candidates(data["people_df"], state, slot)

        roster, to_fill = None, None
        if track == "B" and slot["level"] == "리더":
            b_slots = sorted(
                (x for x in slots if x["track"] == "B" and x["position_id"] == pos_id),
                key=lambda x: x["slot_index"],
            )
            roster = []
            filled = 0
            for bs in b_slots:
                seid = state["occupant"].get(bs["slot_id"])
                sp = people_by_id.get(seid) if seid else None
                if sp:
                    filled += 1
                    roster.append({
                        "emp": seid, "name": sp["성명"], "grade": sp["직급"],
                        "core": seid in core_talent_pool, "vacant": False,
                    })
                else:
                    roster.append({"emp": None, "name": None, "grade": None,
                                   "core": False, "vacant": True})
            to_fill = (filled, len(b_slots))

        children = [
            node_for(child_id)
            for child_id in positions_df[positions_df["parent_id"] == pos_id]["position_id"]
        ]
        return {
            "card": _card_payload(
                slot, person, emp_id, track,
                roster=roster, to_fill=to_fill, candidates=candidates,
            ),
            "children": children,
        }

    roots = positions_df[positions_df["parent_id"].isna()]
    if scope != "전체":
        roots = roots[roots["본부"] == scope]
    tree = [node_for(pid) for pid in roots["position_id"]]

    tray = []
    for eid in state["unplaced"]:
        p = people_by_id.get(eid)
        if not p:
            continue
        home = " · ".join(
            str(v) for v in (p.get("본부"), p.get("부서명")) if isinstance(v, str) and v
        )
        if track == "A" and p["level"] in ("임원", "부장", "리더"):
            succ = p.get("후임")
            tray.append({
                "emp": eid, "name": p["성명"], "grade": p["직급"], "level": p["level"],
                "lv_color": LEVEL_CHIP_COLORS[p["level"]],
                "succ": title_by_pos.get(succ) if succ and succ != "-" else None,
                "core": False, "home": home,
                "profile": _tray_profile(p, slots, state, title_by_pos),
            })
        elif track == "B" and p["level"] == "직원":
            tray.append({
                "emp": eid, "name": p["성명"], "grade": p["직급"], "level": "직원",
                "lv_color": LEVEL_CHIP_COLORS["직원"],
                "succ": None, "core": eid in core_talent_pool, "home": home,
                "profile": _tray_profile(p, slots, state, title_by_pos),
            })

    return {"track": track, "tree": tree, "tray": tray}


def render_org_dnd_chart(payload, key="org_dnd"):
    return _component(data=payload, key=key, default=None)


def handle_org_event(event, data, slots):
    """컴포넌트 드롭 이벤트 → placement 갱신(중복 방지 + 레벨 재검증)."""
    if not event or not isinstance(event, dict):
        return
    if st.session_state.get("org_dnd_last_id") == event.get("id"):
        return  # 이미 처리한 이벤트 (rerun 방어)
    st.session_state["org_dnd_last_id"] = event.get("id")

    people_by_id = data["people_df"].set_index("직번").to_dict("index")
    emp_id = event.get("emp")
    person = people_by_id.get(emp_id)
    if person is None:
        return
    action = event.get("action")
    state = st.session_state["placement"]

    if action == "tray":
        new_state = pl.remove_to_tray(state, emp_id)
        set_placement(new_state, [("toast", f"{person['성명']}을(를) 미배치 트레이로 이동했습니다.")])
        st.rerun()

    elif action == "move":
        slot = next((s for s in slots if s["slot_id"] == event.get("slot")), None)
        # 임원/부장/리더는 트랙 A 어느 포지션으로든 이동 가능(발탁 배치 허용).
        # 직원은 트랙 A 포지션에 배치 불가(트랙 경계만 유지).
        if slot is None or person["level"] == "직원":
            return  # JS에서 이미 막지만 이중 방어
        new_state, info = pl.move_person(state, emp_id, slot["slot_id"])
        if info.get("ok"):
            promoted = LEVEL_RANK.get(person["level"], 0) < LEVEL_RANK.get(slot["level"], 0)
            msg = "발탁 배치를 반영했습니다." if promoted else "이동을 반영했습니다."
            flash = [("toast", f"{person['성명']} → {slot['직책명']} {msg}")]
            if info.get("bumped"):
                bumped = people_by_id.get(info["bumped"], {})
                flash.append(("info", f"기존 점유자 {bumped.get('성명', '')}이(가) 미배치 트레이로 이동했습니다."))
            set_placement(new_state, flash)
            st.rerun()

    elif action == "team":
        if person["level"] != "직원":
            return
        team_slot = next(
            (s for s in slots if s["track"] == "A" and s["position_id"] == event.get("slot")), None
        )
        new_state, info = pl.move_to_team(state, emp_id, event.get("slot"), slots)
        if info.get("ok"):
            team_name = team_slot["담당"] if team_slot else "해당 팀"
            flash = [("toast", f"{person['성명']} → {team_name} 배치를 반영했습니다.")]
            if info.get("bumped"):
                bumped = people_by_id.get(info["bumped"], {})
                flash.append(("info", f"기존 팀원 {bumped.get('성명', '')}이(가) 미배치 트레이로 이동했습니다."))
            set_placement(new_state, flash)
            st.rerun()
