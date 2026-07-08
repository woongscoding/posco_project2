"""배치 순수 로직: 슬롯 정의, 자동배치, 이동/공석/밀어내기 재계산.

UI(streamlit)와 완전히 분리되어 있다. 모든 함수는 상태(dict)를 입력받아
새 상태를 반환하거나 in-place로 갱신한다. 단일 source of truth는
st.session_state["placement"] 이며, 이 모듈은 그 dict의 구조를 정의한다.

placement state 구조:
{
  "occupant": {slot_id: emp_id | None, ...},
  "unplaced": [emp_id, ...],   # 트레이(배치 안 된 / 밀려난 인물)
}
"""
from collections import defaultdict

from data.dummy_data import EVAL_NUMERIC, MULTI_NUMERIC, compute_fit_score

LEADER_LEVELS = {"임원", "부장", "리더"}


# ---------------------------------------------------------------------------
# 슬롯 정의: Track A(포지션=슬롯 1개) + Track B(담당별 팀TO정원 개수만큼 슬롯)
# ---------------------------------------------------------------------------
def build_slots(positions_df):
    slots = []
    for _, pos in positions_df.iterrows():
        slots.append({
            "slot_id": pos["position_id"],
            "position_id": pos["position_id"],
            "level": pos["level"],
            "법인": pos.get("법인", "-"),
            "본부": pos["본부"],
            "부서명": pos["부서명"],
            "담당": pos["담당"],
            "직책명": pos["직책명"],
            "track": "A",
            "slot_index": 0,
        })
        if pos["level"] == "리더" and pos["팀TO정원"] and not pos.isna()["팀TO정원"]:
            for i in range(int(pos["팀TO정원"])):
                slots.append({
                    "slot_id": f"{pos['position_id']}::staff{i}",
                    "position_id": pos["position_id"],
                    "level": "직원",
                    "법인": pos.get("법인", "-"),
                    "본부": pos["본부"],
                    "부서명": pos["부서명"],
                    "담당": pos["담당"],
                    "직책명": "담당원",
                    "track": "B",
                    "slot_index": i,
                })
    return slots


def slots_for_track(slots, track):
    return [s for s in slots if s["track"] == track]


# ---------------------------------------------------------------------------
# 핵심인재 Pool (Track B, 부서명별 상위 50% by 평가 구성점수) — 적임자 Agent mock
# ---------------------------------------------------------------------------
def eval_composite_score(row):
    return (
        EVAL_NUMERIC[row["25년평가"]] * 0.4
        + EVAL_NUMERIC[row["24년평가"]] * 0.3
        + EVAL_NUMERIC[row["23년평가"]] * 0.2
        + EVAL_NUMERIC[row["22년평가"]] * 0.1
        + (MULTI_NUMERIC[row["25다면평가"]] + MULTI_NUMERIC[row["24다면평가"]]) / 2 * 0.0
    )


def compute_core_talent_pool(people_df):
    """부서별 일반직원 상위 50%(평가 구성점수 기준) 직번 집합을 반환.
    부서명이 법인 간 중복되므로 (법인, 부서명) 단위로 묶는다."""
    staff = people_df[people_df["level"] == "직원"].copy()
    staff["_score"] = staff.apply(eval_composite_score, axis=1)
    group_keys = ["법인", "부서명"] if "법인" in staff.columns else ["부서명"]
    core_ids = set()
    for _, grp in staff.groupby(group_keys):
        n = max(1, len(grp) // 2)
        top = grp.sort_values("_score", ascending=False).head(n)
        core_ids.update(top["직번"].tolist())
    return core_ids


# ---------------------------------------------------------------------------
# 초기 상태: 데이터 생성 시점의 "현재" 보임자를 기본 배치로 반영
# ---------------------------------------------------------------------------
def init_state(slots, people_df):
    occupant = {s["slot_id"]: None for s in slots}
    placed_emp_ids = set()

    # Track A: current_position_id 로 이미 보임 중인 사람을 그대로 배치
    for _, p in people_df.iterrows():
        if p["level"] in LEADER_LEVELS and p["current_position_id"]:
            slot_id = p["current_position_id"]
            if slot_id in occupant and occupant[slot_id] is None:
                occupant[slot_id] = p["직번"]
                placed_emp_ids.add(p["직번"])

    # Track B: 담당별 팀TO정원 중 이미 생성된 "직원" 인원을 순서대로 슬롯에 배치.
    # 담당(팀)명이 법인 간 중복되므로 (본부, 담당) 쌍으로 묶는다.
    staff_by_team = defaultdict(list)
    for _, p in people_df.iterrows():
        if p["level"] == "직원":
            staff_by_team[(p["본부"], p["담당"])].append(p["직번"])

    team_slots = defaultdict(list)
    for s in slots:
        if s["track"] == "B":
            team_slots[(s["본부"], s["담당"])].append(s["slot_id"])

    for team, emp_ids in staff_by_team.items():
        for slot_id, emp_id in zip(sorted(team_slots.get(team, [])), emp_ids):
            occupant[slot_id] = emp_id
            placed_emp_ids.add(emp_id)

    # 미배치 트레이: 아직 어느 슬롯에도 없는 후계자/후보/핵심인재 pool
    unplaced = [eid for eid in people_df["직번"].tolist() if eid not in placed_emp_ids]

    return {"occupant": occupant, "unplaced": unplaced}


# ---------------------------------------------------------------------------
# ① 자동배치: 공석 슬롯을 후임 우선 → 적합도 최고 후보 순으로 채움
# ---------------------------------------------------------------------------
def auto_place(state, people_df, fit_matrix, track, slots=None):
    """공석 슬롯 자동 채움. 우선순위: ①후임(successor) ②적합도 매트릭스 후보
    ③(트랙A) 동일 레벨 미배치 인원 중 적합도 최고 — 데모에서 조직도가
    꽉 찬 스크린샷을 확보할 수 있도록 폴백까지 시도한다.

    법인 경계 유지: 자동배치는 슬롯과 같은 법인 소속 인원만 채운다.
    (법인 간 교차 배치는 의도적 전출입이므로 수동 드래그로만 가능)"""
    occupant = dict(state["occupant"])
    unplaced = list(state["unplaced"])
    people_by_id = people_df.set_index("직번").to_dict("index")
    slot_by_id = {s["slot_id"]: s for s in (slots or [])}
    changes = []

    def corp_ok(eid, slot_id):
        slot = slot_by_id.get(slot_id)
        slot_corp = slot.get("법인") if slot else None
        if not slot_corp or slot_corp == "-":
            return True  # 슬롯 정보가 없으면 제한하지 않음 (하위 호환)
        return people_by_id.get(eid, {}).get("법인") == slot_corp

    if track == "A":
        vacant_slots = [sid for sid, occ in occupant.items() if occ is None and "::staff" not in sid]
        for slot_id in vacant_slots:
            candidate = None
            successors = [
                eid for eid in people_df[people_df["후임"] == slot_id]["직번"].tolist()
                if eid in unplaced and corp_ok(eid, slot_id)
            ]
            if successors:
                candidate = successors[0]
            if candidate is None:
                scored = [(eid, score) for (pid, eid), score in fit_matrix.items()
                          if pid == slot_id and eid in unplaced and corp_ok(eid, slot_id)]
                if scored:
                    candidate = max(scored, key=lambda x: x[1])[0]
            if candidate is None and slot_id in slot_by_id:
                slot = slot_by_id[slot_id]
                pool = [eid for eid in unplaced
                        if people_by_id.get(eid, {}).get("level") == slot["level"]
                        and corp_ok(eid, slot_id)]
                if pool:
                    candidate = max(pool, key=lambda eid: compute_fit_score(people_by_id[eid], slot))
            if candidate:
                occupant[slot_id] = candidate
                unplaced.remove(candidate)
                changes.append({"slot_id": slot_id, "emp_id": candidate, "action": "auto_place"})
    else:
        core_pool = compute_core_talent_pool(people_df)
        vacant_slots = [sid for sid, occ in occupant.items() if occ is None and "::staff" in sid]
        available = [eid for eid in unplaced if eid in core_pool and people_by_id.get(eid, {}).get("level") == "직원"]
        available.sort(key=lambda eid: eval_composite_score(people_by_id[eid]), reverse=True)
        for slot_id in vacant_slots:
            if not available:
                break
            idx = next((i for i, eid in enumerate(available) if corp_ok(eid, slot_id)), None)
            if idx is None:
                continue  # 이 슬롯의 법인에 맞는 후보가 없음
            candidate = available.pop(idx)
            occupant[slot_id] = candidate
            unplaced.remove(candidate)
            changes.append({"slot_id": slot_id, "emp_id": candidate, "action": "auto_place"})

    return {"occupant": occupant, "unplaced": unplaced}, changes


# ---------------------------------------------------------------------------
# 이동/재계산: 특정 인원을 특정 슬롯으로 이동. 대상 슬롯 점유자는 트레이로 밀림.
# ---------------------------------------------------------------------------
def move_person(state, emp_id, target_slot_id):
    occupant = dict(state["occupant"])
    unplaced = list(state["unplaced"])

    if target_slot_id not in occupant:
        return state, {"ok": False, "reason": f"슬롯 '{target_slot_id}' 를 찾을 수 없습니다."}

    current_slot_id = next((sid for sid, occ in occupant.items() if occ == emp_id), None)

    bumped_emp = occupant.get(target_slot_id)
    if bumped_emp == emp_id:
        return state, {"ok": True, "reason": "이미 해당 슬롯에 배치되어 있습니다.", "bumped": None}

    if current_slot_id:
        occupant[current_slot_id] = None
    elif emp_id in unplaced:
        unplaced.remove(emp_id)

    if bumped_emp:
        unplaced.append(bumped_emp)

    occupant[target_slot_id] = emp_id
    if emp_id in unplaced:
        unplaced.remove(emp_id)

    return {"occupant": occupant, "unplaced": unplaced}, {
        "ok": True,
        "bumped": bumped_emp,
        "from_slot": current_slot_id,
        "to_slot": target_slot_id,
    }


def move_to_team(state, emp_id, team_position_id, slots):
    """일반직원(Track B)을 특정 담당(팀) 내 빈 슬롯으로 이동. 슬롯이 모두 차 있으면 첫 슬롯 점유자를 밀어낸다."""
    b_slot_ids = sorted(
        s["slot_id"] for s in slots if s["track"] == "B" and s["position_id"] == team_position_id
    )
    occupant = state["occupant"]
    target_slot = next((sid for sid in b_slot_ids if occupant.get(sid) is None), None)
    if target_slot is None and b_slot_ids:
        target_slot = b_slot_ids[0]
    if target_slot is None:
        return state, {"ok": False, "reason": "해당 담당에 슬롯이 없습니다."}
    return move_person(state, emp_id, target_slot)


def clear_all_placements(state):
    """모든 슬롯을 공석으로 되돌리고 배치돼 있던 전원을 미배치 트레이로 보낸다."""
    occupant = {sid: None for sid in state["occupant"]}
    unplaced = list(state["unplaced"])
    for occ in state["occupant"].values():
        if occ and occ not in unplaced:
            unplaced.append(occ)
    return {"occupant": occupant, "unplaced": unplaced}


def remove_to_tray(state, emp_id):
    """특정 인원을 현재 슬롯에서 빼내 미배치 트레이로 보낸다."""
    occupant = dict(state["occupant"])
    unplaced = list(state["unplaced"])
    current_slot_id = next((sid for sid, occ in occupant.items() if occ == emp_id), None)
    if current_slot_id:
        occupant[current_slot_id] = None
    if emp_id not in unplaced:
        unplaced.append(emp_id)
    return {"occupant": occupant, "unplaced": unplaced}


# ---------------------------------------------------------------------------
# 요약 지표
# ---------------------------------------------------------------------------
def summary_metrics(state, slots, track):
    track_slots = [s["slot_id"] for s in slots if s["track"] == track]
    total = len(track_slots)
    filled = sum(1 for sid in track_slots if state["occupant"].get(sid))
    vacant = total - filled
    fill_rate = round(filled / total * 100, 1) if total else 0.0
    return {"total": total, "filled": filled, "vacant": vacant, "fill_rate": fill_rate}


def badges_for_person(person_row, slot_position_id=None):
    badges = []
    if slot_position_id and person_row.get("후임") == slot_position_id:
        badges.append("후임확정")
    if person_row.get("승진") == "Y":
        badges.append("승진")
    if person_row.get("신규보임") == "Y":
        badges.append("신규보임")
    if person_row.get("순환") == "Y":
        badges.append("순환")
    return badges
