"""맞춤형 인재 시뮬레이션 Agent — PoC 목업 엔트리.

Streamlit rerun 방어: 더미 데이터/슬롯/초기 배치 상태는 세션 최초 1회만
생성하여 st.session_state에 저장하고, 이후에는 참조만 한다.
"""
import streamlit as st

from components.candidate import render_candidate_panel
from components.edit_panel import render_edit_panel
from components.org_dnd_chart import (
    build_org_payload,
    handle_org_event,
    render_org_dnd_chart,
)
from data.dummy_data import load_all_data
from logic import placement as pl
from logic import versioning as ver

st.set_page_config(page_title="맞춤형 인재 시뮬레이션 Agent", layout="wide")


def _disable_browser_translate():
    """브라우저 자동번역이 Streamlit의 React DOM과 충돌해 발생하는
    'removeChild' 오류/텍스트 오염을 예방한다(가능한 브라우저에서).

    st.iframe은 '<'가 포함된 문자열을 HTML(srcdoc)로 임베드한다.
    srcdoc iframe은 부모와 같은 origin이라 window.parent.document 접근 가능.
    """
    st.iframe(
        """
        <script>
        try {
            const doc = window.parent.document;
            if (!doc.querySelector('meta[name="google"]')) {
                const meta = doc.createElement('meta');
                meta.name = 'google';
                meta.content = 'notranslate';
                doc.head.appendChild(meta);
            }
            doc.documentElement.setAttribute('translate', 'no');
            doc.documentElement.classList.add('notranslate');
        } catch (e) {}
        </script>
        """,
        height=1,
    )


def _show_flash():
    """직전 액션(자동배치/챗봇/D&D/버전저장)이 st.rerun() 이후에도
    사용자에게 보이도록, 세션에 쌓아둔 메시지를 rerun 직후 렌더한다."""
    for kind, msg in st.session_state.pop("flash", []):
        if kind == "toast":
            st.toast(msg, icon="✅")
        elif kind == "warning":
            st.warning(msg)
        else:
            st.info(msg)


def _init_session_state():
    if "data" not in st.session_state:
        st.session_state["data"] = load_all_data()
    if "slots" not in st.session_state:
        st.session_state["slots"] = pl.build_slots(st.session_state["data"]["positions_df"])
    if "placement" not in st.session_state:
        st.session_state["placement"] = pl.init_state(
            st.session_state["slots"], st.session_state["data"]["people_df"]
        )
    if "track" not in st.session_state:
        st.session_state["track"] = "A"
    if "versions" not in st.session_state:
        st.session_state["versions"] = {}
    if "version_counter" not in st.session_state:
        st.session_state["version_counter"] = 0
    if "placement_rev" not in st.session_state:
        # 배치 상태가 바뀔 때마다 +1 → D&D(sortables) 위젯 key에 섞어
        # 오래된 프론트엔드 상태가 되돌림(diff 오탐)을 일으키지 않게 한다.
        st.session_state["placement_rev"] = 0


def _render_header(data, slots, state, track):
    st.title("맞춤형 인재 시뮬레이션 Agent")
    st.caption("정기인사 배치 시뮬레이션 PoC · HR AX 프로젝트")

    top_l, top_r = st.columns([3, 2])
    with top_l:
        track_display = st.radio(
            "배치 대상 트랙",
            options=["A", "B"],
            format_func=lambda t: "임원 · 부장 · 리더" if t == "A" else "일반직원",
            horizontal=True,
            key="track",
        )
    with top_r:
        st.markdown(
            "<div style='text-align:right; padding-top:0.6rem; color:#888;'>"
            "① 자동배치 → ② 챗봇 조정 → ③ 조직도에서 Drag&amp;Drop</div>",
            unsafe_allow_html=True,
        )

    metrics = pl.summary_metrics(state, slots, track_display)
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("TO 충족률", f"{metrics['fill_rate']}%")
    m2.metric("공석 수", metrics["vacant"])
    m3.metric("배치 완료 수", metrics["filled"])
    m4.metric("전체 정원(TO)", metrics["total"])

    _render_version_bar(data, slots)
    st.divider()
    return track_display


def _render_version_bar(data, slots):
    versions = st.session_state["versions"]
    with st.expander("📌 버전 스냅샷 & 비교", expanded=False):
        v_col1, v_col2 = st.columns([2, 1])
        with v_col1:
            new_label = st.text_input(
                "새 버전 이름", value=f"v{st.session_state['version_counter'] + 1}", key="new_version_label"
            )
        with v_col2:
            st.markdown("<div style='padding-top:1.8rem;'></div>", unsafe_allow_html=True)
            if st.button("현재 배치를 새 버전으로 저장", width="stretch"):
                label = (new_label or "").strip() or f"v{st.session_state['version_counter'] + 1}"
                if label in versions:
                    st.warning(f"'{label}' 버전이 이미 있습니다. 다른 이름을 입력하세요.")
                else:
                    versions[label] = ver.create_snapshot(st.session_state["placement"], label)
                    st.session_state["version_counter"] += 1
                    st.session_state.setdefault("flash", []).append(
                        ("toast", f"'{label}' 버전으로 저장했습니다.")
                    )
                    # 라벨 입력값을 초기화해 다음 기본값(v2, v3…)이 반영되게 한다.
                    del st.session_state["new_version_label"]
                    st.rerun()

        if len(versions) < 2:
            st.caption("두 개 이상의 버전을 저장하면 비교할 수 있습니다.")
            return

        labels = list(versions.keys())
        c1, c2 = st.columns(2)
        with c1:
            va_label = st.selectbox("버전 A", labels, index=max(0, len(labels) - 2), key="version_a")
        with c2:
            vb_label = st.selectbox("버전 B", labels, index=len(labels) - 1, key="version_b")

        if va_label == vb_label:
            st.caption("서로 다른 두 버전을 선택하세요.")
            return

        comparison = ver.compare_versions(versions[va_label], versions[vb_label], slots, data["people_df"])
        st.markdown(f"**{va_label} → {vb_label}** · 변경 {comparison['move_count']}건")

        table_rows = []
        for track_key, m in comparison["metrics"].items():
            track_name = "임원·부장·리더" if track_key == "A" else "일반직원"
            table_rows.append({
                "트랙": track_name,
                "공석수(A)": m["before"]["vacant"], "공석수(B)": m["after"]["vacant"],
                "TO충족률(A)": f"{m['before']['fill_rate']}%", "TO충족률(B)": f"{m['after']['fill_rate']}%",
            })
        st.table(table_rows)

        if comparison["diffs"]:
            st.markdown("**변경된 포지션**")
            st.table([
                {"포지션": d["label"], "변경 전": d["before"], "변경 후": d["after"]}
                for d in comparison["diffs"]
            ])
        else:
            st.caption("두 버전 간 배치 변경이 없습니다.")


def main():
    _disable_browser_translate()
    _init_session_state()
    _show_flash()
    data = st.session_state["data"]
    slots = st.session_state["slots"]

    track = _render_header(data, slots, st.session_state["placement"], st.session_state["track"])
    state = st.session_state["placement"]

    core_talent_pool = None
    if track == "B":
        core_talent_pool = pl.compute_core_talent_pool(data["people_df"])

    # 좌: 큰 조직도(카드에서 직접 Drag&Drop) / 우: 편집 컨트롤 + 후보 추천근거
    chart_col, side_col = st.columns([7, 3], gap="medium")

    with chart_col:
        title_col, scope_col = st.columns([3, 1])
        title_col.subheader("조직도 — 카드에서 바로 Drag & Drop")
        divisions = ["전체"] + sorted({s["본부"] for s in slots if s["track"] == "A"})
        scope = scope_col.selectbox(
            "표시 범위", divisions, key="org_scope", label_visibility="collapsed"
        )
        payload = build_org_payload(track, data, slots, state, core_talent_pool, scope)
        event = render_org_dnd_chart(payload, key="org_dnd")
        handle_org_event(event, data, slots)

    with side_col:
        render_edit_panel(track, data, slots)
        st.divider()
        render_candidate_panel(track, data, slots, state)


if __name__ == "__main__":
    main()
