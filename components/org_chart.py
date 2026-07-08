"""명함형(business-card) 조직도 렌더러 (graphviz HTML-like label).

⚠️ 이 프로젝트의 최우선 목표: 조직도가 크고 또렷해야 한다. 노드 텍스트를
크게, 여백을 충분히 두어 장표 축소에도 읽히도록 한다.

한글 폰트: st.graphviz_chart는 브라우저(클라이언트)에서 SVG로 렌더링하므로
서버 OS가 아니라 "보는 사람"의 브라우저 폰트가 중요하다 → CSS font-family
스택으로 지정해 Windows(맑은 고딕)/Linux(나눔고딕)/macOS(애플고딕) 모두 대응.

트랙 A/B 모두 임원/부장/리더 계층 트리를 그린다(가독성을 위해 동일한 구조 유지).
트랙 B에서는 리더(팀장) 카드 안에 팀원 로스터(핵심인재=보라, 공석=빨강)와
"TO 충족" 뱃지를 표시해, 드래그/자동배치 결과가 조직도에서 바로 보이게 한다.
"""
import html

import graphviz

from logic.placement import badges_for_person

FONT_FACE = "Malgun Gothic, NanumGothic, AppleGothic, sans-serif"

COLOR_FILLED = "#2e7d32"       # 배치완료 (초록)
COLOR_VACANT = "#c62828"       # 공석 (빨강)
COLOR_SUCCESSOR_BORDER = "#1565c0"  # 후계자 확정 (파랑 테두리)
COLOR_CORE_TALENT = "#6a1b9a"  # 핵심인재 (보라)
COLOR_TO_PARTIAL = "#ef6c00"   # TO 부분 충족 (주황)
DEFAULT_BORDER = "#37474f"

BADGE_COLORS = {
    "후임확정": "#1565c0",
    "승진": "#ef6c00",
    "신규보임": "#00838f",
    "순환": "#8d6e63",
    "핵심인재": COLOR_CORE_TALENT,
}


def _esc(text):
    return html.escape(str(text), quote=False)


def _font_open(color=None, size=None, bold=False):
    attrs = f'FACE="{FONT_FACE}"'
    if color:
        attrs += f' COLOR="{color}"'
    if size:
        attrs += f' POINT-SIZE="{size}"'
    tag = f"<FONT {attrs}>"
    return tag + "<B>" if bold else tag


def _font_close(bold=False):
    return ("</B>" if bold else "") + "</FONT>"


def _font(text, color=None, size=None, bold=False):
    return f"{_font_open(color, size, bold)}{text}{_font_close(bold)}"


def _badge_cell(text, bgcolor):
    return (f'<TD BGCOLOR="{bgcolor}" BORDER="0" CELLPADDING="4">'
            f'{_font(f" {_esc(text)} ", color="white", size=10, bold=True)}</TD>')


def _initial_circle(name):
    initial = name[-1] if name and name != "공석" else "-"
    return (f'<TD WIDTH="50" HEIGHT="50" BGCOLOR="#cfd8dc" '
            f'ALIGN="CENTER" VALIGN="MIDDLE">'
            f'{_font(_esc(initial), size=20, bold=True)}</TD>')


def _card_label(title_text, strip_color, name, sub1, sub2, badge_cells,
                border_color=DEFAULT_BORDER, roster_html=None):
    badge_row = "".join(badge_cells) or (
        f'<TD BORDER="0">{_font("-", color="#bbbbbb", size=10)}</TD>'
    )
    roster_row = ""
    if roster_html:
        roster_row = (
            f'<TR><TD COLSPAN="2" ALIGN="LEFT" BGCOLOR="#f5f7f9" CELLPADDING="6">'
            f'{roster_html}</TD></TR>'
        )
    return (
        f'<<TABLE BORDER="3" CELLBORDER="0" CELLSPACING="0" CELLPADDING="8" '
        f'COLOR="{border_color}" BGCOLOR="white">'
        f'<TR><TD COLSPAN="2" BGCOLOR="{strip_color}">'
        f'{_font(_esc(title_text), color="white", size=13, bold=True)}</TD></TR>'
        f'<TR>{_initial_circle(name)}'
        f'<TD ALIGN="LEFT" VALIGN="MIDDLE">'
        f'{_font(_esc(name), size=20, bold=True)}<BR/>'
        f'{_font(_esc(sub1), color="#444444", size=12)}</TD></TR>'
        f'<TR><TD COLSPAN="2" ALIGN="LEFT">'
        f'{_font(sub2, color="#666666", size=11)}</TD></TR>'
        f'{roster_row}'
        f'<TR>{badge_row}</TR>'
        f'</TABLE>>'
    )


def _path_text(*parts):
    return " &gt; ".join(_esc(p) for p in parts if isinstance(p, str) and p)


def _new_digraph(name):
    dot = graphviz.Digraph(name)
    dot.attr(rankdir="TB", bgcolor="white", nodesep="0.5", ranksep="0.7", splines="line")
    dot.attr("node", shape="plaintext", fontname=FONT_FACE)
    dot.attr("edge", color="#9e9e9e", arrowsize="0.7", penwidth="1.5")
    return dot


def _to_fill_badge(filled, total):
    if total == 0:
        return None
    if filled >= total:
        color = COLOR_FILLED
    elif filled >= total / 2:
        color = COLOR_TO_PARTIAL
    else:
        color = COLOR_VACANT
    return _badge_cell(f"TO {filled}/{total}", color)


def _render_leader_cards(dot, positions_df, people_df, a_slots, state,
                         team_fill=None, team_roster=None):
    """임원/부장/리더 명함형 카드 + 상위-하위 연결선을 dot에 추가.

    team_fill: {position_id: (filled, total)} — 트랙 B에서 리더 카드에
    TO 충족 뱃지를 추가로 표시하기 위한 정보(선택).
    team_roster: {position_id: roster_html} — 트랙 B에서 리더 카드 안에
    팀원 명단(핵심인재/공석 강조)을 표시하기 위한 정보(선택).
    """
    people_by_id = people_df.set_index("직번").to_dict("index")
    a_slot_ids = {s["slot_id"] for s in a_slots}
    team_fill = team_fill or {}
    team_roster = team_roster or {}

    for s in a_slots:
        emp_id = state["occupant"].get(s["slot_id"])
        if emp_id:
            person = people_by_id[emp_id]
            badges = badges_for_person(person, s["position_id"])
            name = person["성명"]
            sub1 = f"{person['직급']} · {s['직책명']}"
            strip_color = COLOR_FILLED
            border_color = COLOR_SUCCESSOR_BORDER if "후임확정" in badges else DEFAULT_BORDER
        else:
            badges = []
            name = "공석"
            sub1 = s["직책명"]
            strip_color = COLOR_VACANT
            border_color = COLOR_VACANT
        sub2 = _path_text(s["본부"], s["부서명"])
        badge_cells = [_badge_cell(b, BADGE_COLORS.get(b, "#757575")) for b in badges]
        fill_info = team_fill.get(s["position_id"])
        if fill_info:
            to_badge = _to_fill_badge(*fill_info)
            if to_badge:
                badge_cells.append(to_badge)
        label = _card_label(
            s["직책명"], strip_color, name, sub1, sub2, badge_cells, border_color,
            roster_html=team_roster.get(s["position_id"]),
        )
        dot.node(s["slot_id"], label=label)

    pos_lookup = positions_df.set_index("position_id").to_dict("index")
    for s in a_slots:
        parent = pos_lookup[s["position_id"]]["parent_id"]
        if parent and parent in a_slot_ids:
            dot.edge(parent, s["slot_id"])


def render_track_a(positions_df, people_df, slots, state):
    """트랙 A(임원/부장/리더) 명함형 조직도."""
    dot = _new_digraph("orgchart_a")
    a_slots = [s for s in slots if s["track"] == "A"]
    _render_leader_cards(dot, positions_df, people_df, a_slots, state)
    return dot


def _staff_roster_html(b_slots, state, people_by_id, core_talent_pool):
    """팀원 명단 HTML: 핵심인재=보라 굵게(●), 일반=회색(●), 공석=빨강(○)."""
    core_talent_pool = core_talent_pool or set()
    lines = []
    for bs in sorted(b_slots, key=lambda x: x["slot_index"]):
        emp_id = state["occupant"].get(bs["slot_id"])
        if emp_id and emp_id in people_by_id:
            person = people_by_id[emp_id]
            text = f"● {_esc(person['성명'])} · {_esc(person['직급'])}"
            if emp_id in core_talent_pool:
                lines.append(_font(text + " ★", color=COLOR_CORE_TALENT, size=12, bold=True))
            else:
                lines.append(_font(text, color="#455a64", size=12))
        else:
            lines.append(_font("○ 공석", color=COLOR_VACANT, size=12, bold=True))
    br = '<BR ALIGN="LEFT"/>'
    return br.join(lines) + br if lines else None


def render_track_b(positions_df, people_df, slots, state, core_talent_pool=None):
    """트랙 B(일반직원) 조직도: 임원/부장/리더 체계 + 리더 카드 안에
    팀원 로스터(핵심인재 보라 ★, 공석 빨강)와 TO 충족 뱃지를 표시한다.
    → 자동배치/D&D로 팀원이 바뀌면 조직도에서 바로 보인다."""
    dot = _new_digraph("orgchart_b")
    a_slots = [s for s in slots if s["track"] == "A"]
    people_by_id = people_df.set_index("직번").to_dict("index")

    team_fill = {}
    team_roster = {}
    for s in a_slots:
        if s["level"] != "리더":
            continue
        b_slots = [x for x in slots if x["track"] == "B" and x["position_id"] == s["position_id"]]
        total = len(b_slots)
        filled = sum(1 for x in b_slots if state["occupant"].get(x["slot_id"]))
        team_fill[s["position_id"]] = (filled, total)
        team_roster[s["position_id"]] = _staff_roster_html(
            b_slots, state, people_by_id, core_talent_pool
        )

    _render_leader_cards(
        dot, positions_df, people_df, a_slots, state,
        team_fill=team_fill, team_roster=team_roster,
    )
    return dot


def render_org_chart(track, positions_df, people_df, slots, state, core_talent_pool=None):
    if track == "B":
        return render_track_b(positions_df, people_df, slots, state, core_talent_pool)
    return render_track_a(positions_df, people_df, slots, state)
