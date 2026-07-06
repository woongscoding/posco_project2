"""배치 상태 버전 스냅샷 저장 + 비교(지표/변경목록).

정교한 시각 diff 대신 표 + 변경목록 위주로 구현한다(구현 부담 최소화).
"""
from datetime import datetime

from logic.placement import summary_metrics


def create_snapshot(state, label):
    return {
        "label": label,
        "occupant": dict(state["occupant"]),
        "unplaced": list(state["unplaced"]),
        "saved_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def compare_versions(version_a, version_b, slots, people_df):
    slot_lookup = {s["slot_id"]: s for s in slots}
    name_lookup = people_df.set_index("직번")["성명"].to_dict()

    diffs = []
    all_slot_ids = set(version_a["occupant"]) | set(version_b["occupant"])
    for sid in sorted(all_slot_ids):
        before = version_a["occupant"].get(sid)
        after = version_b["occupant"].get(sid)
        if before != after:
            slot = slot_lookup.get(sid, {})
            title = slot.get("직책명") or sid
            path_parts = [p for p in [slot.get("본부"), slot.get("부서명")] if isinstance(p, str) and p]
            diffs.append({
                "slot_id": sid,
                "label": f"{' > '.join(path_parts)} > {title}" if path_parts else title,
                "before": name_lookup.get(before, "-") if before else "공석",
                "after": name_lookup.get(after, "-") if after else "공석",
            })

    metrics = {}
    for track in ("A", "B"):
        metrics[track] = {
            "before": summary_metrics(version_a, slots, track),
            "after": summary_metrics(version_b, slots, track),
        }

    return {"move_count": len(diffs), "diffs": diffs, "metrics": metrics}
