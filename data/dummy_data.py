"""더미 인력/조직 데이터 생성 모듈.

⚠️ 고정 seed(42)로 1회만 생성되어야 한다. app.py에서 st.session_state에
저장한 뒤에는 이 모듈의 생성 함수를 다시 호출하지 않는다 (rerun 방어).

실제 클라이언트 인력 데이터의 컬럼 스키마를 반영하되 값은 전부 가명/가상이다.
"""
import random
from datetime import date, timedelta

import pandas as pd

SEED = 42
REFERENCE_DATE = date(2026, 7, 6)  # 데모 기준일 (고정값, datetime.now() 사용 금지)

# ---------------------------------------------------------------------------
# 조직 트리 정의 (본부 > 부서명 > 담당)
# ---------------------------------------------------------------------------
# 본부 구성은 두 법인이 동일하다 (클라이언트 명시 3개 본부만 사용).
# 본부명에 "홀딩스_"/"포스코_" 접두어를 붙여 법인을 마킹해 표시한다.
_BASE_DIVS = {
    "경영지원본부": {
        "인사실": ["인사기획담당", "인재개발담당"],
        "재무실": ["재무기획담당", "자금담당"],
    },
    "그룹DX전략실": {
        "DX기획부": ["DX기획담당", "DX거버넌스담당"],
        "데이터플랫폼부": ["데이터기획담당", "AI서비스담당"],
    },
    "미래전략본부": {
        "전략기획실": ["전략1담당", "전략2담당"],
        "미래사업부": ["신사업개발담당", "투자전략담당"],
    },
}
ORG_TREES = {
    corp: {f"{corp}_{div}": depts for div, depts in _BASE_DIVS.items()}
    for corp in ("홀딩스", "포스코")
}
CORP_LIST = list(ORG_TREES)
DIV_CORP = {div: corp for corp, tree in ORG_TREES.items() for div in tree}

# 하위 호환: 전체 본부 → 부서 트리 (법인 구분 없이 합친 뷰)
ORG_TREE = {div: depts for tree in ORG_TREES.values() for div, depts in tree.items()}

EVAL_GRADES = ["S", "A+", "A", "B+", "B", "C"]
EVAL_WEIGHTS = [5, 12, 28, 28, 20, 7]
EVAL_NUMERIC = {"S": 100, "A+": 95, "A": 88, "B+": 80, "B": 70, "C": 55, "D": 40}

MULTI_GRADES = ["최우수", "우수", "양호", "보통", "미흡"]
MULTI_WEIGHTS = [8, 27, 40, 20, 5]
MULTI_NUMERIC = {"최우수": 100, "우수": 85, "양호": 70, "보통": 55, "미흡": 35}

UNIV_LIST = [
    "한빛대학교", "동화대학교", "청람대학교", "미래공과대학교", "온새미대학교",
    "가온대학교", "해솔대학교", "누리공업대학교", "은하대학교", "별빛대학교",
]
MAJOR_LIST = [
    "경영학", "경제학", "기계공학", "전자공학", "화학공학",
    "산업공학", "컴퓨터공학", "신소재공학", "행정학", "통계학",
]

BOJIK_OPINIONS = [
    "차기 리더 후보로 적극 추천할 만한 역량을 보임",
    "현 직책에서 안정적으로 성과를 내고 있어 유지 의견",
    "신규 보직 부여 시 적응 기간이 필요할 것으로 판단",
    "전문성은 우수하나 관리 경험 확대가 필요",
    "조직 장악력이 뛰어나 상위 직책 조기 발탁 검토 가능",
    "직무 전문성 대비 리더십 검증 데이터 부족",
]
HR_OPINIONS = [
    "최근 3개년 평가 상승 추세로 승진 요건 충족",
    "다면평가 대비 정량평가 편차가 있어 추가 확인 필요",
    "순환보직 경험이 부족하여 폭넓은 시각 보완 권고",
    "핵심인재 Pool 등재 대상, 별도 육성 트랙 권장",
    "직급경력 대비 현직책 수행기간이 짧아 안정화 필요",
    "이전 평가 대비 유의미한 변화 없음, 현상 유지 권고",
]
EXEC_SESSION_COMMENTS = [
    "차기 임원 후보 Pool 확정", "중장기 육성 대상으로 재검토", "안정적 수행, 유지 권고",
]
DEPT_SESSION_COMMENTS = [
    "차기 부장 후보로 확정", "1년 내 발탁 검토 대상", "추가 검증 필요",
]


def _weighted_choice(rng, items, weights):
    return rng.choices(items, weights=weights, k=1)[0]


def _rand_date(rng, start_year, end_year):
    start = date(start_year, 1, 1)
    end = date(end_year, 12, 31)
    delta = (end - start).days
    return start + timedelta(days=rng.randint(0, max(delta, 1)))


def _dept_head_title(dept_name):
    if dept_name.endswith("실"):
        return dept_name + "장"
    if dept_name.endswith("소"):
        return dept_name + "장"
    if dept_name.endswith("부"):
        return dept_name + "장"
    return dept_name + " 부서장"


def _team_head_title(team_name):
    base = team_name.replace("담당", "")
    return f"{base}팀장"


def _div_head_title(div_name):
    # 본부명의 법인 접두어("홀딩스_" 등)는 직책명에서 제외한다
    return div_name.split("_")[-1] + "장"


# ---------------------------------------------------------------------------
# 1) 조직/포지션 마스터 (조직개편안_26년 = 목표 조직 출처)
# ---------------------------------------------------------------------------
def build_positions(rng):
    positions = []
    div_idx = 0
    for corp, tree in ORG_TREES.items():
        for div_name, depts in tree.items():
            div_id = f"P-DIV-{div_idx}"
            positions.append({
                "position_id": div_id,
                "level": "임원",
                "법인": corp,
                "본부": div_name,
                "부서명": None,
                "담당": None,
                "직책명": _div_head_title(div_name),
                "TO정원": 1,
                "parent_id": None,
                "팀TO정원": None,
            })
            for dept_idx, (dept_name, teams) in enumerate(depts.items()):
                dept_id = f"P-DEPT-{div_idx}-{dept_idx}"
                positions.append({
                    "position_id": dept_id,
                    "level": "부장",
                    "법인": corp,
                    "본부": div_name,
                    "부서명": dept_name,
                    "담당": None,
                    "직책명": _dept_head_title(dept_name),
                    "TO정원": 1,
                    "parent_id": div_id,
                    "팀TO정원": None,
                })
                for team_idx, team_name in enumerate(teams):
                    team_id = f"P-TEAM-{div_idx}-{dept_idx}-{team_idx}"
                    positions.append({
                        "position_id": team_id,
                        "level": "리더",
                        "법인": corp,
                        "본부": div_name,
                        "부서명": dept_name,
                        "담당": team_name,
                        "직책명": _team_head_title(team_name),
                        "TO정원": 1,
                        "parent_id": dept_id,
                        "팀TO정원": rng.randint(5, 8),
                    })
            div_idx += 1
    return pd.DataFrame(positions)


# ---------------------------------------------------------------------------
# 2) 인력 데이터프레임 (트랙 A: 임원/부장/리더, 트랙 B: 일반직원)
# ---------------------------------------------------------------------------
_LEVEL_GRADE_POOL = {
    "임원": ["전무", "상무"],
    "부장": ["부장", "수석부장"],
    "리더": ["차장", "과장"],
    "직원": ["대리", "사원", "과장"],
}


def _make_person(rng, emp_seq, level, name, home_div, home_dept, home_team,
                  current_position_id=None, current_title="-", 담당부장="-"):
    직급 = _weighted_choice(rng, _LEVEL_GRADE_POOL[level if level in _LEVEL_GRADE_POOL else "직원"],
                            [6, 4] if level in ("임원", "부장") else [5, 5] if level == "리더" else [3, 5, 2])
    birth_year = REFERENCE_DATE.year - rng.randint(28, 58)
    birth_month = rng.randint(1, 12)
    연령 = REFERENCE_DATE.year - birth_year

    eval_years = {}
    base_ability = rng.uniform(45, 95)
    drift = rng.uniform(-3, 6)
    for i, yr in enumerate(["25년평가", "24년평가", "23년평가", "22년평가"]):
        level_score = base_ability + drift * (3 - i) / 3 + rng.uniform(-8, 8)
        level_score = max(30, min(100, level_score))
        closest = min(EVAL_GRADES, key=lambda g: abs(EVAL_NUMERIC[g] - level_score))
        eval_years[yr] = closest

    multi_years = {}
    for key in ["25다면평가", "24다면평가"]:
        m_score = base_ability + rng.uniform(-10, 10)
        m_score = max(20, min(100, m_score))
        closest = min(MULTI_GRADES, key=lambda g: abs(MULTI_NUMERIC[g] - m_score))
        multi_years[key] = closest

    직급경력 = rng.randint(1, 15)
    현직책경력 = rng.randint(0, 5) if current_position_id else 0
    홀딩스입사 = _rand_date(rng, 1998, 2020)
    그룹입사 = 홀딩스입사 - timedelta(days=rng.randint(0, 1500))
    직급변경일 = _rand_date(rng, 2020, 2025)
    직책변경일 = _rand_date(rng, 2022, 2026) if current_position_id else None

    if level == "임원":
        임원세션 = _weighted_choice(rng, EXEC_SESSION_COMMENTS, [3, 4, 3])
        부장세션 = "-"
    elif level == "부장":
        임원세션 = _weighted_choice(rng, EXEC_SESSION_COMMENTS, [3, 4, 3])
        부장세션 = _weighted_choice(rng, DEPT_SESSION_COMMENTS, [3, 4, 3])
    elif level == "리더":
        임원세션 = "-"
        부장세션 = _weighted_choice(rng, DEPT_SESSION_COMMENTS, [3, 4, 3])
    else:
        임원세션 = "-"
        부장세션 = "-"

    row = {
        "직번": f"E{emp_seq:05d}",
        "본부": home_div,
        "부서명": home_dept,
        "담당": home_team,
        "성명": name,
        "직급": 직급,
        "직급변경일": 직급변경일,
        "직급경력": 직급경력,
        "직책": level if level != "직원" else "-",
        "생년월": f"{birth_year}-{birth_month:02d}",
        "연령": 연령,
        "출신교(대학)": rng.choice(UNIV_LIST),
        "전공": rng.choice(MAJOR_LIST),
        "신분": "정규직",
        "원소속": home_div,
        "홀딩스입사일": 홀딩스입사,
        "그룹입사일": 그룹입사,
        "직책변경일": 직책변경일,
        "현직책": current_title,
        "보임일": 직책변경일,
        "현직책경력": 현직책경력,
        "담당부장": 담당부장,
        "25년평가": eval_years["25년평가"],
        "24년평가": eval_years["24년평가"],
        "23년평가": eval_years["23년평가"],
        "22년평가": eval_years["22년평가"],
        "25다면평가": multi_years["25다면평가"],
        "24다면평가": multi_years["24다면평가"],
        "보직의견": rng.choice(BOJIK_OPINIONS),
        "사업회사": DIV_CORP.get(home_div, CORP_LIST[0]),
        "법인": DIV_CORP.get(home_div, CORP_LIST[0]),  # 소속 본부의 법인을 따른다
        "지주사": "Y" if DIV_CORP.get(home_div) == "홀딩스" else "N",
        "순환": _weighted_choice(rng, ["Y", "N"], [2, 8]),
        "신규전입": _weighted_choice(rng, ["Y", "N"], [15, 85]) if level != "직원" else "N",
        "조직개편안_25년": current_position_id or "-",
        "조직개편안_26년": current_position_id or "-",
        "HR검토의견": rng.choice(HR_OPINIONS),
        "승진": "N",
        "후임": "-",
        "신규보임": _weighted_choice(rng, ["Y", "N"], [12, 88]) if current_position_id else "N",
        "부장세션": 부장세션,
        "임원세션": 임원세션,
        "current_position_id": current_position_id,
        "level": level,
    }
    return row


def generate_people(rng, positions_df):
    people = []
    emp_seq = 1
    name_counters = {"임원": 0, "부장": 0, "리더": 0}
    ALPHA = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

    def next_name(level):
        idx = name_counters[level]
        name_counters[level] += 1
        letter = ALPHA[idx % 26] + ("" if idx < 26 else str(idx // 26))
        return f"{level}{letter}"

    dept_head_holder = {}  # dept_id -> 성명 (담당부장 lookup용, 2-pass)
    pos_rows = positions_df.to_dict("records")

    # ---- Track A: 임원/부장/리더 현재 보임자 + 후임 + 여유 pool ----
    for pos in pos_rows:
        level = pos["level"]
        div, dept, team = pos["본부"], pos["부서명"], pos["담당"]
        is_vacant_now = rng.random() < 0.32  # 일부 포지션은 현재도 공석(자동배치 데모 효과용)

        담당부장 = dept_head_holder.get(pos["parent_id"], "-") if level == "리더" else (
            dept_head_holder.get(pos["parent_id"], "-") if level == "부장" else "-"
        )

        holder_name = None
        if not is_vacant_now:
            holder_name = next_name(level)
            row = _make_person(
                rng, emp_seq, level, holder_name, div, dept, team,
                current_position_id=pos["position_id"], current_title=pos["직책명"],
                담당부장=담당부장,
            )
            if level == "부장":
                dept_head_holder[pos["position_id"]] = holder_name
            people.append(row)
            emp_seq += 1

        # 후임(successor) - 약 75% 확률로 지정됨
        if rng.random() < 0.75:
            succ_from_same_org = rng.random() < 0.7
            if succ_from_same_org:
                s_div, s_dept, s_team = div, dept, team
            else:
                # 후임은 같은 법인 내 다른 본부에서 온다
                other_div = rng.choice(list(ORG_TREES[DIV_CORP[div]].keys()))
                s_div = other_div
                s_dept, s_team = None, None
            succ_name = next_name(level)
            succ_row = _make_person(
                rng, emp_seq, level, succ_name, s_div, s_dept, s_team,
                current_position_id=None, current_title="-", 담당부장="-",
            )
            succ_row["후임"] = pos["position_id"]
            people.append(succ_row)
            emp_seq += 1

        # 여유 pool 후보 (동일 레벨의 대체 후보, 약 40% 확률, 같은 법인 소속)
        if rng.random() < 0.4:
            other_div = rng.choice(list(ORG_TREES[DIV_CORP[div]].keys()))
            pool_name = next_name(level)
            pool_row = _make_person(
                rng, emp_seq, level, pool_name, other_div, None, None,
                current_position_id=None, current_title="-", 담당부장="-",
            )
            people.append(pool_row)
            emp_seq += 1

    # 담당부장 재보정 (2-pass: 부장 보임자가 늦게 확정된 경우)
    for p in people:
        if p["level"] == "리더" and p["current_position_id"]:
            team_pos = positions_df[positions_df["position_id"] == p["current_position_id"]].iloc[0]
            p["담당부장"] = dept_head_holder.get(team_pos["parent_id"], "-")

    # 레벨별 미배치 후보 보충: 공석 수보다 후보가 적으면 ①자동배치가 공석을
    # 남겨 "조직도 꽉 찬 스크린샷"을 확보할 수 없다. 항상 여유 1명 이상 유지.
    placed_positions = {p["current_position_id"] for p in people if p["current_position_id"]}
    for level in ("임원", "부장", "리더"):
        vacant_count = sum(
            1 for pos in pos_rows
            if pos["level"] == level and pos["position_id"] not in placed_positions
        )
        unplaced_count = sum(
            1 for p in people if p["level"] == level and not p["current_position_id"]
        )
        for _ in range(max(0, vacant_count + 1 - unplaced_count)):
            extra_row = _make_person(
                rng, emp_seq, level, next_name(level),
                rng.choice(list(DIV_CORP.keys())), None, None,
                current_position_id=None, current_title="-", 담당부장="-",
            )
            people.append(extra_row)
            emp_seq += 1

    # ---- Track B: 일반직원 (담당별 팀TO정원 기반) ----
    staff_seq = 1
    for pos in pos_rows:
        if pos["level"] != "리더":
            continue
        team_to = int(pos["팀TO정원"])
        occupied_count = max(1, team_to - rng.randint(0, 2))
        for _ in range(occupied_count):
            name = f"직원{staff_seq:03d}"
            row = _make_person(
                rng, emp_seq, "직원", name, pos["본부"], pos["부서명"], pos["담당"],
                current_position_id=None, current_title="담당원",
                담당부장=dept_head_holder.get(pos["parent_id"], "-"),
            )
            row["승진"] = _weighted_choice(rng, ["Y", "N"], [10, 90])
            people.append(row)
            emp_seq += 1
            staff_seq += 1

    # 부서별 여유 핵심인재 pool (특정 담당에 소속되지 않은 채 회사 전체 공석에 추천되는 후보)
    # 부서명이 법인 간 중복되므로 (본부, 부서명) 쌍으로 순회한다
    dept_pairs = sorted({(pos["본부"], pos["부서명"]) for pos in pos_rows if pos["level"] == "리더"})
    for div, dept in dept_pairs:
        for _ in range(rng.randint(2, 4)):
            name = f"직원{staff_seq:03d}"
            row = _make_person(
                rng, emp_seq, "직원", name, div, dept, None,
                current_position_id=None, current_title="-",
                담당부장="-",
            )
            row["승진"] = _weighted_choice(rng, ["Y", "N"], [15, 85])
            people.append(row)
            emp_seq += 1
            staff_seq += 1

    return pd.DataFrame(people)


# ---------------------------------------------------------------------------
# 3) 적합도 매트릭스 (Track A: position_id x 직번 → 0~100, 출처: 적임자 Agent)
# ---------------------------------------------------------------------------
def _eval_composite(row):
    eval_score = (
        EVAL_NUMERIC[row["25년평가"]] * 0.4
        + EVAL_NUMERIC[row["24년평가"]] * 0.3
        + EVAL_NUMERIC[row["23년평가"]] * 0.2
        + EVAL_NUMERIC[row["22년평가"]] * 0.1
    )
    multi_score = (MULTI_NUMERIC[row["25다면평가"]] + MULTI_NUMERIC[row["24다면평가"]]) / 2
    return eval_score, multi_score


_SESSION_BONUS = {
    "차기 임원 후보 Pool 확정": 12, "중장기 육성 대상으로 재검토": 0, "안정적 수행, 유지 권고": 4,
    "차기 부장 후보로 확정": 12, "1년 내 발탁 검토 대상": 6, "추가 검증 필요": -4,
    "-": 0,
}


def compute_fit_score(row, position_row):
    eval_score, multi_score = _eval_composite(row)
    session_bonus = _SESSION_BONUS.get(row.get("임원세션", "-"), 0) + _SESSION_BONUS.get(row.get("부장세션", "-"), 0)
    career_component = min(row.get("직급경력", 0), 10) * 2
    org_match = 5 if row.get("본부") == position_row.get("본부") else -5
    successor_bonus = 8 if row.get("후임") == position_row.get("position_id") else 0

    score = (
        0.45 * eval_score
        + 0.25 * multi_score
        + 0.15 * (eval_score + session_bonus)
        + 0.10 * career_component
        + 0.05 * (50 + org_match)
        + successor_bonus
    )
    return int(max(0, min(100, round(score))))


def build_fit_matrix(people_df, positions_df):
    matrix = {}
    pos_by_id = positions_df.set_index("position_id").to_dict("index")
    for pos_id, pos_row in pos_by_id.items():
        level = pos_row["level"]
        candidates = people_df[
            (people_df["level"] == level)
            & ((people_df["current_position_id"] == pos_id) | (people_df["후임"] == pos_id))
        ]
        # 동일 레벨 pool 후보도 소수 추가 (교차 배치 데모용)
        pool_pool = people_df[
            (people_df["level"] == level)
            & (people_df["current_position_id"].isna() | (people_df["current_position_id"] == ""))
            & (people_df["후임"] == "-")
        ]
        pool_candidates = pool_pool.sample(n=min(2, len(pool_pool)), random_state=SEED) if len(pool_pool) else pool_pool

        for _, r in pd.concat([candidates, pool_candidates]).drop_duplicates(subset=["직번"]).iterrows():
            matrix[(pos_id, r["직번"])] = compute_fit_score(r, pos_row)
    return matrix


# ---------------------------------------------------------------------------
# 진입점: 전체 데이터 1회 생성
# ---------------------------------------------------------------------------
def load_all_data(seed=SEED):
    rng = random.Random(seed)
    positions_df = build_positions(rng)
    people_df = generate_people(rng, positions_df)
    people_df["current_position_id"] = people_df["current_position_id"].fillna("")
    fit_matrix = build_fit_matrix(people_df, positions_df)
    return {
        "positions_df": positions_df,
        "people_df": people_df,
        "fit_matrix": fit_matrix,
        "org_tree": ORG_TREE,
    }
