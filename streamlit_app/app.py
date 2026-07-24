# -*- coding: utf-8 -*-
"""
「눈 떠보니 지원 대상이었습니다」 — 공공데이터 기반 AI 맞춤형 청년정책 추천
Streamlit UI: 입력 화면 → 결과 대시보드 (2단계)

실행: streamlit run app.py
"""
import base64
import os
import re

import streamlit as st

from recommender import (UserProfile, load_policies, recommend, InterestMatcher,
                         estimate_total_support, format_amount, generate_one_liner,
                         get_collected_at, is_direct_benefit)
from chatbot import answer as chat_answer

st.set_page_config(page_title="눈 떠보니 지원 대상이었습니다", page_icon="👀",
                   layout="wide", initial_sidebar_state="collapsed")

# ──────────────────────────────────────────────
# 디자인 토큰 & 전역 CSS (기본 크롬 숨김 + 카드 스타일)
# ──────────────────────────────────────────────
PURPLE, PURPLE2 = "#6C5CE7", "#8B7CF6"
BG, LINE = "#F5F6FB", "#EEF0F5"
GREEN, ORANGE = "#10B981", "#F59E0B"

st.markdown(f"""
<style>
#MainMenu, header, footer {{visibility: hidden; height: 0;}}
[data-testid="stToolbar"], [data-testid="stDecoration"], [data-testid="stStatusWidget"],
[data-testid="stSidebarCollapsedControl"], [data-testid="stSidebar"] {{display: none;}}
.stApp {{background: {BG}; font-family: Pretendard, "맑은 고딕", sans-serif;}}
.block-container {{padding: 0.7rem 2.2rem 3rem 2.2rem; max-width: 1500px;}}

/* 입력 폼 압축 — 한 화면에 들어가도록 세로 간격 축소 */
div[data-testid="stForm"] div[data-testid="stVerticalBlock"] {{gap: 0.55rem;}}
div[data-testid="stForm"] [data-testid="stWidgetLabel"] {{margin-bottom: 0;}}
div[data-testid="stForm"] label p {{font-size: 13px !important;}}

/* 챗봇 — 말풍선 글자는 헤더 흰 안내문구와 같은 급으로 */
div[data-testid="stChatMessage"] {{padding: 0.55rem 0.7rem;}}
div[data-testid="stChatMessage"] p,
div[data-testid="stChatMessage"] li {{font-size: 12px !important; line-height: 1.6;}}
div[data-testid="stChatMessage"] strong {{font-size: 12.5px;}}
div[data-testid="stChatInput"] textarea {{font-size: 12.5px !important;}}

/* 카드 공통 */
.yf-card {{background:#fff; border:1px solid {LINE}; border-radius:16px; padding:18px 20px;}}
.yf-muted {{color:#6B7280; font-size:12.5px;}}

/* 버튼 */
.stButton>button {{
  background: linear-gradient(135deg, {PURPLE}, {PURPLE2}); color:#fff; border:none;
  border-radius:12px; padding:0.55rem 1.1rem; font-weight:700; font-size:14px;
}}
.stButton>button:hover {{filter: brightness(1.07); color:#fff;}}
div[data-testid="stForm"] .stButton>button {{width:100%; padding:0.8rem; font-size:16px;}}

/* 필터 칩 (st.pills → stButtonGroup, data-variant="pills") */
div[data-testid="stButtonGroup"] button[data-variant="pills"] {{
  border-radius:999px !important; border:1.4px solid {LINE} !important;
  background:#fff !important; color:#6B7280 !important; font-weight:600 !important;
  padding:0.25rem 0.95rem !important;
}}
div[data-testid="stButtonGroup"] button[data-variant="pills"][aria-checked="true"] {{
  background:{PURPLE} !important; border-color:{PURPLE} !important; color:#fff !important;
}}
div[data-testid="stButtonGroup"] button[data-variant="pills"] p {{color:inherit !important;}}

/* 정책명 링크 */
a.yf-plink {{color:#2D2A45; text-decoration:none;}}
a.yf-plink:hover {{color:{PURPLE}; text-decoration:underline;}}

/* 아웃라인 버튼 (다시 분석하기) — 콘텐츠 폭, 우측 정렬 */
.st-key-reanalyze_btn {{display:flex; justify-content:flex-end; width:100% !important;}}
.st-key-reanalyze_btn .stButton {{width:auto !important;}}
.st-key-reanalyze_btn button {{
  background:#fff !important; color:{PURPLE} !important;
  border:1.5px solid #D8D2F8 !important; font-weight:700 !important;
  padding:0.45rem 1.05rem !important; font-size:13.5px !important; white-space:nowrap;
}}
.st-key-reanalyze_btn button:hover {{border-color:{PURPLE} !important; filter:none !important;}}

/* 고스트 버튼 (수정하기) */
.st-key-edit_profile_btn button {{
  background:#F0EEFD !important; color:{PURPLE} !important; border:none !important;
  padding:0.28rem 0.5rem !important; font-size:12px !important; font-weight:700 !important;
}}

/* 흰 카드형 컨테이너 — .yf-box-marker를 품은 border 컨테이너만 카드화
   (Streamlit 1.59는 border=True를 stVerticalBlock에 그림) */
div[data-testid="stVerticalBlock"]:has(> div[data-testid="stElementContainer"] .yf-box-marker) {{
  background:#fff; border:1px solid {LINE} !important; border-radius:16px !important;
  padding:10px 14px 14px 14px;
}}

/* 책갈피 저장 버튼 — 카드 우상단에 겹쳐 배치 (내 적합도 위) */
div[class*="st-key-bm_"] {{
  display:flex; justify-content:flex-end; position:relative; z-index:5;
  width:100% !important; margin-bottom:-40px; padding-right:10px;
}}
div[class*="st-key-bm_"] .stButton button {{transform:translateY(20px);}}
div[class*="st-key-bm_"] .stButton {{width:auto !important;}}
div[class*="st-key-bm_"] button {{
  background:transparent !important; background-image:none !important;
  border:none !important; padding:4px 8px !important; min-height:0 !important;
  font-size:21px !important; line-height:1 !important; box-shadow:none !important;
}}
div[class*="st-key-bm_"] button span,
div[class*="st-key-bm_"] button p {{font-size:21px !important;}}
div[class*="st-key-bm_"][class*="_off"] button {{color:#B7B3D7 !important;}}
div[class*="st-key-bm_"][class*="_on"] button {{color:{PURPLE} !important;}}
div[class*="st-key-bm_"] button:hover {{
  color:{PURPLE} !important; transform:translateY(20px) scale(1.12);
}}

/* 정렬·분야 셀렉트 컴팩트 */
.st-key-sort_by div[data-baseweb="select"] > div,
.st-key-cat_flt div[data-baseweb="select"] > div {{
  border-radius:999px; border-color:{LINE}; font-size:12.5px; min-height:34px;
}}

/* expander — '자세히 보기'를 카드 우하단 링크처럼 */
div[data-testid="stExpander"] {{
  border:none; background:transparent; margin-top:-52px; position:relative; z-index:4;
}}
div[data-testid="stExpander"] summary {{
  font-size:12.5px; color:{PURPLE}; font-weight:700;
  padding:0.2rem 0.6rem; justify-content:flex-end; gap:2px;
}}
div[data-testid="stExpander"] summary:hover {{text-decoration:underline; color:{PURPLE};}}
div[data-testid="stExpanderDetails"] {{
  background:#FBFBFE; border:1px solid {LINE}; border-radius:12px;
  padding:0.7rem 1rem; margin-top:2px;
}}

/* 입력 폼 */
div[data-testid="stForm"] {{
  background:#fff; border:1px solid {LINE}; border-radius:18px; padding:1.1rem 1.6rem;
  box-shadow:0 6px 24px rgba(108,92,231,.07);
}}
div[data-testid="stForm"] .stButton>button {{padding:0.55rem; font-size:15px;}}
</style>
""", unsafe_allow_html=True)

# ──────────────────────────────────────────────
# 데이터 & 매처 캐싱
# ──────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load():
    return load_policies()


@st.cache_data(show_spinner=False)
def _asset_b64(name):
    """assets/ 이미지 → base64 (없으면 빈 문자열 → SVG 폴백)"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", name)
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode()
    except OSError:
        return ""


@st.cache_resource(show_spinner="관심분야 매칭 모델 준비 중...")
def _matcher(cache_key):
    """cache_key = (정책 수, 기준일) — 데이터가 갱신되면 자동으로 재생성"""
    policies, _ = _load()
    return InterestMatcher(policies, use_embeddings=True)


SIDO = ["서울", "부산", "대구", "인천", "광주", "대전", "울산", "세종", "경기",
        "강원", "충북", "충남", "전북", "전남", "경북", "경남", "제주"]
STATUS_OPTS = ["대학생", "대학원생", "취업준비생", "사회초년생", "재직자",
               "무직", "자영업자", "프리랜서", "창업자"]
HOUSING_OPTS = ["무주택", "자가(본인·가족 명의 주택)", "기타"]
INCOME_OPTS = {
    "잘 모르겠어요": None, "중위소득 50% 이하": 50, "중위소득 75% 이하": 75,
    "중위소득 100% 이하": 100, "중위소득 120% 이하": 120, "중위소득 150% 이하": 150,
    "중위소득 180% 이하": 180, "중위소득 200% 이하": 200, "중위소득 200% 초과": 999,
}
INTEREST_OPTS = ["주거·독립", "취업·이직", "창업", "학비·장학금",
                 "자기계발·교육", "생활비·교통", "문화·여가", "자산형성"]
# 관심분야 태그 → 정책 분야(카테고리) — 결과 화면 '관심 분야' 필터 옵션 구성용
INTEREST_TO_CATEGORY = {
    "주거·독립": "주거", "취업·이직": "취업·창업", "창업": "취업·창업",
    "학비·장학금": "교육·장학", "자기계발·교육": "교육·역량",
    "생활비·교통": "생활·교통", "문화·여가": "생활·교통", "자산형성": "생활·교통",
}

_STARTUP_KW = ("창업", "스타트업", "사업화")
_ASSET_KW = ("자산형성", "저축", "통장", "적금")
_CULTURE_KW = ("문화", "공연", "전시", "예술")


def matches_interest_tag(r, tag):
    """정책이 관심분야 태그에 해당하는지 — 입력창 태그와 같은 단어·같은 의미로 필터링.
    같은 분야를 공유하는 태그(창업/취업·이직, 자산형성/문화·여가/생활비·교통)는
    키워드로 세분해 구분한다."""
    cat = r.get("category", "")
    kw = " ".join(r.get("keywords", [])) + " " + r.get("name", "")
    if tag == "주거·독립":
        return cat == "주거"
    if tag == "학비·장학금":
        return cat == "교육·장학"
    if tag == "자기계발·교육":
        return cat == "교육·역량"
    if tag == "창업":
        return cat == "취업·창업" and any(k in kw for k in _STARTUP_KW)
    if tag == "취업·이직":
        return cat == "취업·창업" and not any(k in kw for k in _STARTUP_KW)
    if tag == "자산형성":
        return cat == "생활·교통" and any(k in kw for k in _ASSET_KW)
    if tag == "문화·여가":
        return cat == "생활·교통" and any(k in kw for k in _CULTURE_KW)
    if tag == "생활비·교통":
        return (cat == "생활·교통"
                and not any(k in kw for k in _ASSET_KW + _CULTURE_KW))
    return True

st.session_state.setdefault("submitted", False)
st.session_state.setdefault("profile", {})
st.session_state.setdefault("show_n", 8)
st.session_state.setdefault("flt", "전체")
st.session_state.setdefault("chat_open", False)
st.session_state.setdefault("chat_history", [])
st.session_state.setdefault("chat_last_policy", None)
st.session_state.setdefault("reanalyzing", False)
st.session_state.setdefault("sort_by", "적합도순")
st.session_state.setdefault("cat_flt", "관심 분야 (전체)")
st.session_state.setdefault("bookmarks", set())

# 좌측 하단 마스코트 — 예상결과 이미지 구도: 큰 보라 돋보기(왼쪽) + 손 흔드는 흰 고양이(오른쪽)
MASCOT_SVG = f"""
<svg width="186" height="168" viewBox="0 0 186 168" xmlns="http://www.w3.org/2000/svg">
  <ellipse cx="100" cy="158" rx="58" ry="7" fill="#EDEBF7"/>
  <!-- 큰 돋보기 (왼쪽) -->
  <circle cx="48" cy="58" r="30" fill="#EAF2FE" opacity=".75"/>
  <circle cx="48" cy="58" r="30" fill="none" stroke="{PURPLE}" stroke-width="9"/>
  <circle cx="38" cy="47" r="9" fill="#fff" opacity=".65"/>
  <rect x="20" y="84" width="12" height="38" rx="6" transform="rotate(35 26 103)"
    fill="{PURPLE}"/>
  <!-- 고양이 (오른쪽) -->
  <path d="M84 52 L89 28 L107 44 Z" fill="#fff" stroke="#E7E4F6" stroke-width="2.4"/>
  <path d="M152 52 L147 28 L129 44 Z" fill="#fff" stroke="#E7E4F6" stroke-width="2.4"/>
  <path d="M89 46 L92 33 L101 42 Z" fill="#FFCCD9"/>
  <path d="M147 46 L144 33 L135 42 Z" fill="#FFCCD9"/>
  <circle cx="118" cy="84" r="40" fill="#fff" stroke="#E7E4F6" stroke-width="2.6"/>
  <path d="M99 80 q5.5 -7.5 11 0" stroke="#4A4560" stroke-width="3.4" fill="none"
    stroke-linecap="round"/>
  <path d="M126 80 q5.5 -7.5 11 0" stroke="#4A4560" stroke-width="3.4" fill="none"
    stroke-linecap="round"/>
  <path d="M111 93 q3.5 4 7 0 q3.5 4 7 0" stroke="#4A4560" stroke-width="2.4" fill="none"
    stroke-linecap="round"/>
  <circle cx="93" cy="90" r="5.5" fill="#FFD9E1"/>
  <circle cx="143" cy="90" r="5.5" fill="#FFD9E1"/>
  <ellipse cx="118" cy="136" rx="28" ry="20" fill="#fff" stroke="#E7E4F6" stroke-width="2.6"/>
  <!-- 흔드는 오른손 -->
  <path d="M146 128 q14 -4 16 -18" stroke="#fff" stroke-width="9" fill="none"
    stroke-linecap="round"/>
  <path d="M146 128 q14 -4 16 -18" stroke="#E7E4F6" stroke-width="2" fill="none"
    stroke-linecap="round" opacity=".6"/>
  <!-- 꼬리 -->
  <path d="M90 140 q-12 2 -13 -9" stroke="#fff" stroke-width="8" fill="none"
    stroke-linecap="round"/>
  <!-- 별 -->
  <path d="M168 96 l2.8 6.4 6.4 2.8 -6.4 2.8 -2.8 6.4 -2.8 -6.4 -6.4 -2.8 6.4 -2.8 z"
    fill="#FFD34D"/>
  <path d="M74 18 l2.2 5 5 2.2 -5 2.2 -2.2 5 -2.2 -5 -5 -2.2 5 -2.2 z"
    fill="#FFD34D" opacity=".9"/>
  <path d="M160 24 l1.8 4.2 4.2 1.8 -4.2 1.8 -1.8 4.2 -1.8 -4.2 -4.2 -1.8 4.2 -1.8 z"
    fill="#FFD34D" opacity=".75"/>
</svg>"""

# 좌측 브랜드 로고 (보라 행성 + 반짝이)
PLANET_SVG = f"""
<svg width="36" height="36" viewBox="0 0 44 44" xmlns="http://www.w3.org/2000/svg">
  <defs><linearGradient id="pg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{PURPLE}"/><stop offset="1" stop-color="{PURPLE2}"/>
  </linearGradient></defs>
  <circle cx="22" cy="22" r="12" fill="url(#pg)"/>
  <ellipse cx="22" cy="22" rx="19" ry="6.5" fill="none" stroke="#B3A7FA"
    stroke-width="2.6" transform="rotate(-18 22 22)"/>
  <circle cx="17" cy="18" r="3" fill="#fff" opacity=".35"/>
  <path d="M38 6 l1.6 3.6 3.6 1.6 -3.6 1.6 -1.6 3.6 -1.6 -3.6 -3.6 -1.6 3.6 -1.6 z"
    fill="#FFD166"/>
</svg>"""

# 손 흔드는 미니 고양이 (분석 완료 박스용 — 머리+몸통+꼬리)
CAT_MINI_SVG = """
<svg width="54" height="60" viewBox="0 0 58 66" xmlns="http://www.w3.org/2000/svg">
  <path d="M17 17 L21 5 L29 15 Z" fill="#fff"/>
  <path d="M43 17 L39 5 L31 15 Z" fill="#fff"/>
  <path d="M19 14 L21.5 8 L26 13 Z" fill="#FFC9D4"/>
  <path d="M41 14 L38.5 8 L34 13 Z" fill="#FFC9D4"/>
  <circle cx="30" cy="28" r="17.5" fill="#fff"/>
  <path d="M22 26 q3 -4 6 0" stroke="#4A4560" stroke-width="2.2" fill="none" stroke-linecap="round"/>
  <path d="M33 26 q3 -4 6 0" stroke="#4A4560" stroke-width="2.2" fill="none" stroke-linecap="round"/>
  <path d="M25.8 33 q2.2 2.5 4.2 0 q2.2 2.5 4.2 0" stroke="#4A4560" stroke-width="1.8"
    fill="none" stroke-linecap="round"/>
  <circle cx="19" cy="31" r="3" fill="#FFD9E1"/>
  <circle cx="41" cy="31" r="3" fill="#FFD9E1"/>
  <ellipse cx="30" cy="53" rx="13.5" ry="10" fill="#fff"/>
  <path d="M43 49 q7 -3 8 -11" stroke="#fff" stroke-width="5.5" fill="none" stroke-linecap="round"/>
  <path d="M17 56 q-7 1 -7.5 -5" stroke="#fff" stroke-width="4.5" fill="none"
    stroke-linecap="round" opacity=".9"/>
</svg>"""


# ──────────────────────────────────────────────
# 콜백
# ──────────────────────────────────────────────
def go_edit():
    st.session_state.submitted = False


def re_analyze():
    """입력돼 있는 내 정보 그대로 정책을 다시 검색 (결과 화면 유지)"""
    st.session_state.show_n = 8
    st.session_state.flt = "전체"
    st.session_state.sort_by = "적합도순"
    st.session_state.cat_flt = "관심 분야 (전체)"
    st.session_state.reanalyzing = True
    _load.clear()          # 정책 데이터가 갱신됐다면 새 데이터로 재검색


def more_policies():
    st.session_state.show_n += 8


def open_chat():
    st.session_state.chat_open = True


def close_chat():
    st.session_state.chat_open = False


def toggle_bookmark(pid):
    bm = st.session_state.bookmarks
    (bm.discard if pid in bm else bm.add)(pid)


# ──────────────────────────────────────────────
# 1) 입력 화면
# ──────────────────────────────────────────────
def input_view():
    p = st.session_state.profile
    _, mid, _ = st.columns([1.2, 2.6, 1.2])
    with mid:
        st.markdown(f"""
<div style="text-align:center; margin:4px 0 10px 0;">
  <span style="font-size:26px; vertical-align:middle;">👀</span>
  <span style="font-size:24px; font-weight:800; color:#2D2A45; letter-spacing:-1px;
    vertical-align:middle; margin-left:6px;">
    눈 떠보니 <span style="color:{PURPLE};">지원 대상</span>이었습니다</span>
  <div style="color:#5F6883; font-size:13px; margin-top:3px;">
    공공데이터 기반 AI 맞춤형 청년정책 추천 — 내 정보를 입력하면 지금 신청할 수 있는 정책을 찾아드려요</div>
</div>""", unsafe_allow_html=True)

        with st.form("profile_form"):
            st.markdown(f"<div style='font-weight:800; font-size:15.5px; color:#2D2A45;'>"
                        f"📋 기본 정보 <span class='yf-muted' style='font-weight:500;'>— "
                        f"자격 판정에 사용돼요 (규칙 기반, AI가 판정하지 않아요)</span></div>",
                        unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            name = c1.text_input("이름(별명)", value=p.get("name", ""), placeholder="예: 김청년")
            age = c2.number_input("나이(만)", 15, 49, int(p.get("age", 25)))
            c3, c4 = st.columns(2)
            region = c3.selectbox("거주지(시·도)", SIDO, index=SIDO.index(p.get("region", "서울")))
            status = c4.selectbox("직업·상태", STATUS_OPTS,
                                  index=STATUS_OPTS.index(p.get("status", "대학생")))
            c5, c6 = st.columns(2)
            school = c5.text_input("학교(선택)", value=p.get("school", ""), placeholder="예: 광운대학교")
            housing = c6.selectbox("주거 형태", HOUSING_OPTS,
                                   index=HOUSING_OPTS.index(p.get("housing_raw", "무주택")))
            income_keys = list(INCOME_OPTS.keys())
            income_label = st.selectbox(
                "가구 소득 수준 (기준 중위소득)", income_keys,
                index=income_keys.index(p.get("income_label", "잘 모르겠어요")),
                help="잘 모르면 '잘 모르겠어요'를 선택하세요. 소득 조건이 있는 정책은 체크리스트로 안내해 드려요.")

            st.markdown(f"<div style='font-weight:800; font-size:15.5px; color:#2D2A45; "
                        f"margin-top:4px;'>🎯 관심분야 <span class='yf-muted' "
                        f"style='font-weight:500;'>— AI 의미 매칭(ko-sBERT)으로 추천 순위에 "
                        f"반영돼요</span></div>", unsafe_allow_html=True)
            interests = st.multiselect("관심분야 (복수 선택)", INTEREST_OPTS,
                                       default=p.get("interests", ["주거·독립", "취업·이직"]))
            interest_text = st.text_input("지금 상황을 자유롭게 적어주세요 (선택)",
                                          value=p.get("interest_text", ""),
                                          placeholder="예: 자취 중이라 월세가 부담되고, 취업 준비에 필요한 자격증 공부 중이에요")

            if st.form_submit_button("🔍 내가 받을 수 있는 정책 분석하기"):
                st.session_state.profile = {
                    "name": name.strip() or "청년", "age": int(age), "region": region,
                    "status": status, "school": school.strip(),
                    "housing_raw": housing, "housing": "무주택" if housing == "무주택" else "자가",
                    "income_label": income_label, "income_pct": INCOME_OPTS[income_label],
                    "interests": interests, "interest_text": interest_text.strip(),
                }
                st.session_state.submitted = True
                st.session_state.show_n = 8
                st.session_state.flt = "전체"
                st.rerun()

        st.markdown(f"<div class='yf-muted' style='text-align:center; margin-top:8px; "
                    f"font-size:11.5px;'>본 서비스는 사전 자가진단·정책 탐색 도구이며, "
                    f"최종 신청 가능 여부는 각 기관의 공식 심사 기준을 따릅니다.</div>",
                    unsafe_allow_html=True)


# ──────────────────────────────────────────────
# 2) 결과 대시보드 — HTML 조각 생성기
# ──────────────────────────────────────────────
def gauge_html(fit, status_label):
    # 적합도 구간별 색: 85%↑ 초록 / 70~84% 보라 / 70% 미만 주황
    if fit >= 85:
        color = GREEN
    elif fit >= 70:
        color = PURPLE
    else:
        color = ORANGE
    deg = int(fit * 3.6)
    return (f'<div style="display:flex;align-items:center;gap:11px;flex:none;">'
            f'<div style="width:52px;height:52px;border-radius:50%;flex:none;'
            f'background:conic-gradient({color} {deg}deg, {LINE} {deg}deg);'
            f'display:flex;align-items:center;justify-content:center;">'
            f'<div style="width:38px;height:38px;border-radius:50%;background:#fff;"></div></div>'
            f'<div><div style="font-size:11px;color:#6B7280;">내 적합도</div>'
            f'<div style="font-size:20px;font-weight:800;color:{color};line-height:1.15;">'
            f'{fit}%</div></div></div>')


def tag_html(text, bg, fg):
    return (f'<span style="background:{bg};color:{fg};border-radius:999px;'
            f'padding:3px 10px;font-size:11.5px;font-weight:700;margin-right:6px;">{text}</span>')


BOOKMARK_SVG = ('<svg width="15" height="18" viewBox="0 0 15 18" fill="none">'
                '<path d="M1.5 2.5 a2 2 0 0 1 2-2 h8 a2 2 0 0 1 2 2 v14.2 l-6-3.6 -6 3.6 z" '
                'stroke="#C6C2E4" stroke-width="1.6" fill="none"/></svg>')
BOOKMARK_ON_SVG = (f'<svg width="15" height="18" viewBox="0 0 15 18">'
                   f'<path d="M1.5 2.5 a2 2 0 0 1 2-2 h8 a2 2 0 0 1 2 2 v14.2 l-6-3.6 -6 3.6 z" '
                   f'fill="{PURPLE}"/></svg>')


def clean_summary(text):
    """'ㅇ (목적) … ㅇ (대상) … ㅇ (주요내용) …' 식 개조식 원문을 한 줄 요약으로 정리.
    주요내용/지원내용을 우선 추출하고, 없으면 목적을, 그것도 없으면 라벨만 걷어낸다."""
    t = re.sub(r"[ㅇo○□◦▪•·]+\s*", " ", str(text or ""))
    m = (re.search(r"\((?:주요\s*내용|지원\s*내용|사업\s*내용)\)\s*(.+?)(?=\([가-힣\s]{1,7}\)|$)", t)
         or re.search(r"\(목\s*적\)\s*(.+?)(?=\([가-힣\s]{1,7}\)|$)", t))
    if m:
        t = m.group(1)
    else:
        t = re.sub(r"\([가-힣\s]{1,7}\)", " ", t)
    return re.sub(r"\s+", " ", t).strip(" -–·,") or str(text or "")


def policy_card_html(r, saved=False):
    if r.get("not_open_yet"):
        s_bg, s_fg, s_bd = "#EAF2FE", "#3B82F6", "#C3DAF8"
        status_txt = "접수 예정"
    elif "심사" in r["status_label"]:
        s_bg, s_fg, s_bd = "#FEF6EA", ORANGE, "#F5DDB8"
        status_txt = "심사 중"
    elif r["deadline_soon"]:
        s_bg, s_fg, s_bd = "#FDECEC", "#EF4444", "#F6C6C6"
        status_txt = f"마감 D-{r['days_left']}"
    else:
        s_bg, s_fg, s_bd = "#EAF9F2", GREEN, "#C4EBD8"
        status_txt = r["status_label"]
    d = r["days_left"]
    if r.get("not_open_yet"):
        deadline_txt = f"{r.get('apply_start', '')}부터 접수"
    else:
        deadline_txt = "상시 신청" if d is None else f"마감 {r.get('apply_end', '')} (D-{d})"
    amount = r.get("amount_label") or "공고문 참조"
    # 대출·청약·자산형성 상품의 금액은 '받는 돈'이 아님을 명시 (오해 방지)
    kw_text = r.get("name", "") + " " + " ".join(r.get("keywords", []))
    if r.get("amount_max") and any(k in kw_text for k in
                                   ("대출", "융자", "청약", "적금", "저축", "자산형성")):
        amount += ' <span style="color:#6B7280;font-weight:400;font-size:11px;">(한도·만기 기준)</span>'
    summary = clean_summary(r.get("summary")).replace("<", "&lt;")
    url = r.get("url", "")
    name_html = (f'<a class="yf-plink" href="{url}" target="_blank" rel="noopener">'
                 f'{r["name"]} <span style="font-size:11.5px;">🔗</span></a>'
                 if url else r["name"])
    badge = (f'<span style="background:{s_bg};color:{s_fg};border:1px solid {s_bd};'
             f'border-radius:8px;padding:2.5px 9px;font-size:11.5px;font-weight:700;'
             f'margin-right:8px;">{status_txt}</span>')
    cat_tag = (f'<span style="background:#F0EEFD;color:{PURPLE};border-radius:8px;'
               f'padding:2.5px 9px;font-size:11.5px;font-weight:700;margin-left:8px;">'
               f'{r.get("category", "")}</span>')
    if r.get("special_req"):
        cat_tag += (f'<span style="background:#FEF6EA;color:{ORANGE};border-radius:8px;'
                    f'padding:2.5px 9px;font-size:11.5px;font-weight:700;margin-left:6px;">'
                    f'⚠ 특정자격 확인</span>')
    return (
        f'<div style="background:#fff;border:1px solid {LINE};border-radius:15px;'
        f'padding:17px 18px 46px 18px;display:flex;gap:16px;align-items:flex-start;'
        f'position:relative;min-height:140px;margin-bottom:8px;">'
        # 책갈피는 카드 위에 겹쳐지는 실제 st.button이 담당 (saved 인자는 호환용)
        f'<div style="flex:1;min-width:0;">'
        f'<div style="display:flex;align-items:center;flex-wrap:wrap;margin-bottom:7px;">'
        f'{badge}<span style="font-size:16px;font-weight:800;color:#2D2A45;">{name_html}</span>'
        f'{cat_tag}</div>'
        f'<div style="font-size:12.8px;color:#5F6883;line-height:1.55;'
        f'word-break:keep-all;overflow-wrap:break-word;">{summary}</div>'
        f'<div style="margin-top:10px;font-size:12.2px;color:#6B7280;">'
        f'💰 <b style="color:#2D2A45;">{amount}</b>'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;🏢 {r.get("org", "")}'
        f'&nbsp;&nbsp;·&nbsp;&nbsp;⏰ {deadline_txt}</div></div>'
        f'<div style="margin-right:6px;margin-top:26px;">'
        f'{gauge_html(r["fit"], r["status_label"])}</div></div>'
    )


def stat_card_html(icon, icon_bg, label, value, sub="", value_color="#2D2A45"):
    sub_html = (f"<div style='font-size:10.5px;color:#8A93AC;'>({sub})</div>" if sub else "")
    return (
        f'<div style="flex:1;background:#fff;border:1px solid {LINE};border-radius:16px;'
        f'padding:16px 18px;display:flex;gap:13px;align-items:center;min-width:0;">'
        f'<div style="width:50px;height:50px;border-radius:50%;background:{icon_bg};flex:none;'
        f'display:flex;align-items:center;justify-content:center;font-size:23px;">{icon}</div>'
        f'<div style="min-width:0;"><div style="font-size:11.5px;color:#6B7280;">{label}</div>'
        f'<div style="font-size:19px;font-weight:800;color:{value_color};white-space:nowrap;">{value}</div>'
        f'{sub_html}'
        f'</div></div>')


INFO_ICONS = {"이름": "💧", "나이": "🎂", "거주지": "📍", "직업/상태": "💼",
              "학교": "🏫", "주거 형태": "🏠", "소득 구간": "💳", "관심 분야": "💜"}


def left_panel(user, results):
    prof = st.session_state.profile
    rows = [
        ("이름", user.name), ("나이", f"{user.age}세"), ("거주지", user.region),
        ("직업/상태", user.status), ("학교", prof.get("school") or "-"),
        ("주거 형태", prof.get("housing_raw", user.housing)),
        ("소득 구간", prof.get("income_label", "-")),
        ("관심 분야", ", ".join(user.interests) or "-"),
    ]
    info = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;padding:8px 0;'
        f'border-bottom:1px solid {LINE};font-size:12.6px;">'
        f'<span style="width:24px;height:24px;border-radius:50%;background:#F0EEFD;flex:none;'
        f'display:flex;align-items:center;justify-content:center;font-size:12px;">'
        f'{INFO_ICONS.get(k, "•")}</span>'
        f'<span style="color:#6B7280;flex:none;">{k}</span>'
        f'<span style="color:#2D2A45;font-weight:700;text-align:right;flex:1;min-width:0;'
        f'word-break:keep-all;overflow-wrap:break-word;line-height:1.45;">{v}</span></div>'
        for k, v in rows)

    st.markdown(f"""
<div style="display:flex;align-items:center;gap:9px;margin-bottom:5px;">
  <div style="flex:none;">{PLANET_SVG}</div>
  <div style="font-size:18.5px;font-weight:800;color:#2D2A45;line-height:1.25;">
    눈 떠보니<br>지원 대상이었습니다</div>
</div>
<div class="yf-muted" style="margin-bottom:14px;">AI가 당신에게 딱 맞는<br>청년정책을 찾아드려요!</div>
""", unsafe_allow_html=True)

    h1, h2 = st.columns([2.1, 1.1])
    h1.markdown(f"<div style='font-weight:800;font-size:13.5px;color:{PURPLE};"
                f"padding-top:6px;'>{user.name} 님의 정보</div>", unsafe_allow_html=True)
    with h2:
        st.button("✏️ 수정하기", on_click=go_edit, use_container_width=True,
                  key="edit_profile_btn")

    mini_b64 = _asset_b64("cat_mini.png")
    mag_b64 = _asset_b64("cat_magnifier.png")
    mini_html = (f'<img src="data:image/png;base64,{mini_b64}" style="height:74px;" alt="">'
                 if mini_b64 else CAT_MINI_SVG)
    mascot_html = (f'<img src="data:image/png;base64,{mag_b64}" '
                   f'style="width:100%;max-width:230px;border-radius:12px;" alt="">'
                   if mag_b64 else MASCOT_SVG)
    st.markdown(f"""
<div class="yf-card" style="margin-bottom:12px;padding:6px 16px;">{info}</div>
<div style="background:#5951F0;border-radius:15px;
  padding:12px 14px;color:#fff;margin-bottom:12px;display:flex;gap:10px;align-items:center;">
  <div style="flex:none;">{mini_html}</div>
  <div style="font-size:12.6px;line-height:1.55;">
    <b>{user.name}님을 위해<br>분석 완료! 🎉</b><br>
    총 <b>{len(results)}개</b>의 정책을 찾았어요.</div>
</div>
<div class="yf-card" style="background:#F6F5FE;border-color:#E5E1FA;margin-bottom:6px;">
  <div style="font-weight:800;font-size:12.5px;color:{PURPLE};margin-bottom:4px;">📍 TIP</div>
  <div style="font-size:12.2px;color:#4B5163;line-height:1.6;">
    정책은 신청 기간과 조건이 변경될 수 있어요. 자세한 내용은 각 기관 홈페이지에서
    확인해주세요!</div>
</div>
<div style="text-align:center;margin:10px 0 4px 0;">{mascot_html}</div>
""", unsafe_allow_html=True)


def center_panel(user, results):
    # 헤더 + 다시 분석하기 (아웃라인)
    collected = get_collected_at()
    h1, h2 = st.columns([4.6, 1.5])
    with h1:
        st.markdown(f"""
<div style="font-size:22px;font-weight:800;color:#2D2A45;">
  <span style="color:{PURPLE};">{user.name}님</span> 에게 추천하는 청년정책 ✨</div>
<div class="yf-muted" style="margin-top:3px;">{collected} 수집 데이터 기준으로 분석된 결과입니다.</div>
""", unsafe_allow_html=True)
    with h2:
        st.button("🔄 다시 분석하기", on_click=re_analyze, key="reanalyze_btn")

    # 스탯 카드 4개
    total, counted = estimate_total_support(results)
    n_open = sum(1 for r in results
                 if "심사" not in r["status_label"] and not r.get("not_open_yet"))
    soon = sum(1 for r in results if r["deadline_soon"])
    avg_fit = round(sum(r["fit"] for r in results) / len(results)) if results else 0
    st.markdown(
        '<div style="display:flex;gap:12px;margin:14px 0 16px 0;">'
        + stat_card_html("🐷", "#F0EEFD", "추정 지원 규모", f"최대 {format_amount(total)}",
                         f"연간·산정 가능 {counted}건 기준", value_color=PURPLE)
        + stat_card_html("🎁", "#E7F8F1", "추천 정책 수", f"{len(results)}개",
                         f"신청 가능 {n_open}개")
        + stat_card_html("📅", "#FDECEC", "신청 마감 임박", f"{soon}개",
                         "<span style='color:#EF4444;font-weight:700;'>7일 이내 마감</span>")
        + stat_card_html("🛡️", "#E7F8F1", "충족률", f"{avg_fit}%", "내 조건 기준 평균 적합도")
        + "</div>", unsafe_allow_html=True)

    # ── 맞춤 정책 추천 박스 ──
    box = st.container(border=True)
    with box:
        st.markdown("<span class='yf-box-marker'></span>"
                    "<div style='font-weight:800;font-size:16px;color:#2D2A45;"
                    "padding:6px 4px 0 4px;'>맞춤 정책 추천</div>", unsafe_allow_html=True)

        n_all = len(results)
        bm = st.session_state.bookmarks
        n_saved = sum(1 for r in results if r["id"] in bm)
        counts = {"전체": n_all, "신청 가능": n_open, "마감 임박": soon, "저장": n_saved}
        f1, f2, f3 = st.columns([3.4, 1.15, 0.95])
        with f1:
            flt = st.pills("필터", ["전체", "신청 가능", "마감 임박", "저장"],
                           selection_mode="single", label_visibility="collapsed",
                           format_func=lambda o: f"{o} ({counts[o]})", key="flt")
        with f2:
            # 입력창에서 고른 관심분야 태그를 같은 단어 그대로 필터 옵션으로 노출
            my_tags = [t for t in user.interests
                       if any(matches_interest_tag(r, t) for r in results)]
            if not my_tags:                      # 관심분야 미선택 시 전체 태그 폴백
                my_tags = [t for t in INTEREST_OPTS
                           if any(matches_interest_tag(r, t) for r in results)]
            cat_opts = ["관심 분야 (전체)"] + my_tags
            if st.session_state.get("cat_flt") not in cat_opts:
                st.session_state.cat_flt = "관심 분야 (전체)"
            cat = st.selectbox("분야", cat_opts,
                               label_visibility="collapsed", key="cat_flt")
        with f3:
            sort_by = st.selectbox("정렬", ["적합도순", "마감 임박순", "금액순"],
                                   label_visibility="collapsed", key="sort_by")

        flt = flt or "전체"
        if flt == "신청 가능":
            shown = [r for r in results
                     if "심사" not in r["status_label"] and not r.get("not_open_yet")]
        elif flt == "마감 임박":
            shown = [r for r in results if r["deadline_soon"]]
        elif flt == "저장":
            shown = [r for r in results if r["id"] in bm]
        else:
            shown = list(results)
        if cat != "관심 분야 (전체)":
            shown = [r for r in shown if matches_interest_tag(r, cat)]
        if sort_by == "마감 임박순":
            shown.sort(key=lambda r: r["days_left"] if r["days_left"] is not None else 99999)
        elif sort_by == "금액순":
            shown.sort(key=lambda r: -(r.get("amount_max") or 0))

        if shown:
            st.markdown(f"<div class='yf-muted' style='font-size:11.5px;padding:0 4px;'>"
                        f"총 {len(shown)}건 중 {min(st.session_state.show_n, len(shown))}건 "
                        f"표시 중</div>", unsafe_allow_html=True)

        if not shown:
            msg = ("아직 저장한 정책이 없어요. 카드의 '🔖 저장' 버튼으로 관심 정책을 모아보세요."
                   if flt == "저장" else "조건에 맞는 정책이 없어요. 필터를 바꿔보세요.")
            st.markdown(f'<div style="text-align:center;color:#6B7280;padding:36px;">'
                        f'{msg}</div>', unsafe_allow_html=True)

        for r in shown[:st.session_state.show_n]:
            saved = r["id"] in bm
            # 책갈피 저장 버튼 — CSS로 카드 우상단(내 적합도 위)에 겹쳐 배치
            st.button(":material/bookmark_added:" if saved else ":material/bookmark:",
                      key=f"bm_{r['id']}_{'on' if saved else 'off'}",
                      on_click=toggle_bookmark, args=(r["id"],),
                      help="저장됨 — 클릭해서 해제" if saved else "이 정책 저장하기")
            st.markdown(policy_card_html(r, saved=saved), unsafe_allow_html=True)
            with st.expander("자세히 보기"):
                st.markdown("**이 정책을 추천한 이유**")
                for line in r["reason"]:
                    st.markdown(f"- {line}")
                st.markdown("**신청 전 체크리스트**")
                for c in r["checklist"]:
                    st.markdown(f"- {c}")
                if r.get("url"):
                    st.markdown(f"🔗 **신청/상세 링크**: [{r['url']}]({r['url']})")
            st.markdown("<div style='height:6px'></div>", unsafe_allow_html=True)

        if len(shown) > st.session_state.show_n:
            st.button(f"더 많은 정책 보기 ⌄ (+{min(8, len(shown) - st.session_state.show_n)}개)",
                      on_click=more_policies, use_container_width=True, key="more_btn")

    st.markdown(f"<div class='yf-muted' style='text-align:center;font-size:11.5px;"
                f"margin-top:10px;'>※ 본 서비스는 공공데이터를 기반으로 제공되며, "
                f"최종 신청 및 자격 요건은 각 기관의 기준을 따릅니다.</div>",
                unsafe_allow_html=True)


def right_panel(user, results, matcher):
    # TOP 3 혜택 — '직접 받는 지원금' 기준 (대출 한도·만기액·사업예산 제외, 총액 합산과 동일 규칙)
    with_amount = sorted([r for r in results if is_direct_benefit(r)],
                         key=lambda x: -x["amount_max"])[:3]
    def top3_row(i, r):
        url = r.get("url", "")
        name_html = (f'<a class="yf-plink" href="{url}" target="_blank" rel="noopener">'
                     f'{r["name"]}</a>' if url else r["name"])
        return (
            f'<div style="display:flex;gap:9px;align-items:center;padding:10px 0;'
            f'border-bottom:1px solid {LINE};">'
            f'<div style="width:24px;height:24px;border-radius:50%;flex:none;background:'
            f'{[PURPLE, PURPLE2, "#B3A7FA"][i]};color:#fff;display:flex;align-items:center;'
            f'justify-content:center;font-size:12px;font-weight:800;">{i + 1}</div>'
            f'<div style="flex:1;min-width:0;font-size:12.3px;font-weight:700;color:#2D2A45;'
            f'white-space:nowrap;overflow:hidden;text-overflow:ellipsis;">{name_html}</div>'
            f'<div style="flex:none;font-size:12.3px;color:{PURPLE};font-weight:800;">'
            f'{format_amount(r["amount_max"])}</div>'
            f'</div>')

    top3 = "".join(top3_row(i, r) for i, r in enumerate(with_amount)) \
        or '<div class="yf-muted">금액 산정 가능한 정책 없음</div>'

    # 체크리스트 (상위 정책들의 핵심 확인사항 취합, 우측 초록 체크 스타일)
    seen, checks = set(), []
    for r in results[:5]:
        for c in r["checklist"]:
            core = c.split("(")[0].strip()
            if core not in seen and not c.startswith("⚠️"):
                seen.add(core)
                checks.append(c)
    checks = checks[:5]
    check_html = "".join(
        f'<div style="display:flex;align-items:center;gap:8px;padding:7px 0;'
        f'border-bottom:1px solid {LINE};font-size:12.3px;color:#4B5163;line-height:1.45;">'
        f'<span style="flex:1;">{c}</span>'
        f'<span style="width:17px;height:17px;border-radius:50%;background:{GREEN};flex:none;'
        f'color:#fff;font-size:10.5px;display:flex;align-items:center;justify-content:center;'
        f'font-weight:800;">✓</span></div>' for c in checks)

    one_liner = generate_one_liner(results, user)

    st.markdown(f"""
<div class="yf-card" style="margin-bottom:12px;">
  <div style="display:flex;align-items:center;gap:8px;margin-bottom:4px;">
    <span style="width:28px;height:28px;border-radius:9px;background:#F0EEFD;flex:none;
      display:flex;align-items:center;justify-content:center;font-size:14px;">🏠</span>
    <span style="font-weight:800;font-size:13.5px;color:{PURPLE};line-height:1.35;">
      {user.name}님을 위한<br>TOP 3 혜택</span></div>
  {top3}
</div>
<div class="yf-card" style="margin-bottom:12px;">
  <div style="font-weight:800;font-size:13.5px;color:{PURPLE};margin-bottom:4px;">
    📋 신청 전 체크리스트</div>
  {check_html}
</div>
<div style="background:#EBF9F1;border:1px solid #CFF0DD;border-radius:15px;
  padding:15px 17px;margin-bottom:12px;">
  <div style="font-weight:800;font-size:13.5px;color:#0E8A5F;margin-bottom:5px;">🤖 AI 한줄 요약</div>
  <div style="font-size:12.6px;color:#22684C;line-height:1.6;">{one_liner}</div>
</div>
""", unsafe_allow_html=True)

    if st.session_state.chat_open:
        chat_panel(user, results, matcher)
    else:
        st.markdown(f"""
<div style="background:linear-gradient(135deg,{PURPLE},{PURPLE2});border-radius:15px 15px 0 0;
  padding:16px 18px;color:#fff;display:flex;align-items:center;gap:10px;">
  <div style="flex:1;">
    <div style="font-weight:800;font-size:14px;">궁금한 점이 있으신가요?</div>
    <div style="font-size:12.3px;margin-top:4px;">AI 챗봇에게 물어보세요!</div>
  </div>
  <div style="width:34px;height:34px;border-radius:50%;background:rgba(255,255,255,.22);
    display:flex;align-items:center;justify-content:center;font-size:16px;">→</div>
</div>
""", unsafe_allow_html=True)
        st.button("💬 챗봇과 대화하기", on_click=open_chat, use_container_width=True,
                  key="open_chat_btn")


def chat_panel(user, results, matcher):
    """우측 레일 CTA 자리에서 열리는 정책 Q&A 챗봇"""
    st.markdown(f"""
<div style="background:linear-gradient(135deg,{PURPLE},{PURPLE2});border-radius:15px 15px 0 0;
  padding:13px 16px;color:#fff;">
  <div style="font-weight:800;font-size:14px;">💬 정책 Q&amp;A 챗봇</div>
  <div style="font-size:11px;opacity:1;margin-top:3px;line-height:1.45;">
    검색은 AI, 답변은 검증된 정책 데이터만 사용해요</div>
</div>""", unsafe_allow_html=True)
    box = st.container(height=380, border=True)
    with box:
        if not st.session_state.chat_history:
            with st.chat_message("assistant", avatar="🤖"):
                st.markdown(f"안녕하세요 {user.name}님! 추천받은 정책 {len(results)}개에 대해 "
                            "물어보세요.\n\n예시:\n- *청년월세 신청 방법 알려줘*\n"
                            "- *서류는 뭐가 필요해?*\n- *장학금 뭐 있어?*\n"
                            "- *월세랑 장학금 같이 받을 수 있어?*")
        for role, msg in st.session_state.chat_history:
            with st.chat_message(role, avatar="🧑" if role == "user" else "🤖"):
                st.markdown(msg)
    q = st.chat_input("예: 청년월세 신청 방법", key="chat_in")
    if q:
        text, pid = chat_answer(q, results, matcher, user,
                                st.session_state.chat_last_policy)
        st.session_state.chat_history.append(("user", q))
        st.session_state.chat_history.append(("assistant", text))
        st.session_state.chat_last_policy = pid
        st.rerun()
    st.button("챗봇 닫기 ✕", on_click=close_chat, use_container_width=True,
              key="close_chat_btn")


def loading_view(user):
    """다시 분석하기 클릭 직후 보여주는 전용 로딩 화면"""
    st.markdown(f"""
<style>
@keyframes yf-spin {{to {{transform: rotate(360deg);}}}}
@keyframes yf-bounce {{0%,100% {{transform: translateY(0);}} 50% {{transform: translateY(-10px);}}}}
@keyframes yf-dots {{0% {{content:"";}} 33% {{content:".";}} 66% {{content:"..";}} 100% {{content:"...";}}}}
.yf-loading-dots::after {{content:""; animation: yf-dots 1.2s steps(1) infinite;}}
</style>
<div style="display:flex; flex-direction:column; align-items:center; justify-content:center;
  min-height:72vh; text-align:center;">
  <div style="animation: yf-bounce 1.6s ease-in-out infinite;">{
      (lambda b: f'<img src="data:image/png;base64,{b}" style="width:200px;border-radius:12px;" alt="">'
       if b else MASCOT_SVG)(_asset_b64("cat_magnifier.png"))}</div>
  <div style="width:46px; height:46px; border-radius:50%; margin:18px 0 20px 0;
    border:5px solid {LINE}; border-top-color:{PURPLE};
    animation: yf-spin 0.9s linear infinite;"></div>
  <div style="font-size:20px; font-weight:800; color:#2D2A45;">
    {user.name}님의 정보로 정책을 다시 분석하고 있어요<span class="yf-loading-dots"></span></div>
  <div class="yf-muted" style="margin-top:8px; font-size:13.5px; line-height:1.6;">
    최신 정책 데이터를 불러와 자격 판정과 적합도 계산을 다시 실행 중이에요.<br>
    잠시만 기다려 주세요!</div>
</div>""", unsafe_allow_html=True)


def result_view():
    prof = st.session_state.profile
    user = UserProfile(
        name=prof["name"], age=prof["age"], region=prof["region"], status=prof["status"],
        school=prof.get("school", ""), housing=prof["housing"],
        income_pct=prof["income_pct"], interests=prof["interests"],
        interest_text=prof.get("interest_text", ""),
    )

    if st.session_state.reanalyzing:
        # 로딩 화면을 먼저 그려놓고, 그 뒤에서 재분석을 수행한 뒤 결과 화면으로 전환
        loading_view(user)
        import time
        t0 = time.time()
        policies, as_of = _load()
        matcher = _matcher((len(policies), str(as_of)))
        st.session_state._precomputed = (recommend(user, policies, as_of,
                                                   matcher=matcher), str(as_of))
        if (elapsed := time.time() - t0) < 1.2:   # 너무 짧으면 화면이 깜빡이므로 최소 노출
            time.sleep(1.2 - elapsed)
        st.session_state.reanalyzing = False
        st.rerun()

    policies, as_of = _load()
    matcher = _matcher((len(policies), str(as_of)))
    pre = st.session_state.pop("_precomputed", None)
    if pre is not None and pre[1] == str(as_of):   # 로딩 화면에서 미리 계산한 결과 재사용
        results = pre[0]
    else:
        with st.spinner("자격 판정 및 적합도 계산 중..."):
            results = recommend(user, policies, as_of, matcher=matcher)

    left, center, right = st.columns([2.15, 5.75, 2.1], gap="medium")
    with left:
        left_panel(user, results)
    with center:
        if not results:
            st.markdown(f'<div class="yf-card" style="text-align:center;padding:60px;">'
                        f'<div style="font-size:40px;">🥲</div>'
                        f'<div style="font-weight:800;font-size:18px;color:#2D2A45;margin:8px 0;">'
                        f'조건에 맞는 정책을 찾지 못했어요</div>'
                        f'<div class="yf-muted">나이·지역·소득 조건을 조정해 다시 분석해 보세요.</div></div>',
                        unsafe_allow_html=True)
            st.button("✏️ 조건 수정하기", on_click=go_edit)
        else:
            center_panel(user, results)
    with right:
        if results:
            right_panel(user, results, matcher)

    st.markdown(f"""
<div style="text-align:center;margin-top:34px;padding-top:14px;border-top:1px solid {LINE};"
  class="yf-muted">
  추정 총 지원 규모는 금액 산정 가능한 정책 기준 추정치이며(대출·자산형성·창업자금 등 제외),
  최종 신청 가능 여부는 각 기관의 공식 심사 기준을 따릅니다.<br>
  본 서비스는 공공기관 심사를 대체하지 않는 사전 자가진단·정책 탐색 도구입니다.
  · 기준일 {as_of} · 데이터: 온통청년/정부24/복지로/한국장학재단</div>
""", unsafe_allow_html=True)


# ──────────────────────────────────────────────
# 라우팅
# ──────────────────────────────────────────────
if st.session_state.submitted:
    result_view()
else:
    input_view()
