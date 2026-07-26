# -*- coding: utf-8 -*-
"""
정책 Q&A 미니 챗봇 — 검색은 AI(ko-sBERT), 답변은 검증된 데이터 필드만 사용

구조 (본 서비스의 '환각 차단' 원칙을 챗봇까지 일관 적용):
  1) 의도 감지  : 키워드 규칙 (신청방법/서류/마감/금액/자격/중복수급/탐색)
  2) 정책 검색  : ①정책명 직접 매칭 ②하이브리드(ko-sBERT 의미 + 어휘 부스트)
                  ③직전 대화 정책 기억(후속 질문 "서류는 뭐 필요해?" 처리)
  3) 답변 생성  : 정책의 구조화 필드(신청기간·URL·자격근거·체크리스트)를
                  템플릿에 채움 — 데이터에 없는 내용은 지어내지 않고
                  "공식 확인 필요"로 안내

단독 테스트: python chatbot.py
"""
import re

# ──────────────────────────────────────────────
# 1) 의도 감지 (키워드 규칙)
# ──────────────────────────────────────────────
INTENT_PATTERNS = {
    "apply":     ["신청 방법", "신청방법", "어떻게 신청", "신청하려면", "신청 어디",
                  "어디서 신청", "신청 절차", "접수"],
    "docs":      ["서류", "준비물", "증빙", "제출", "구비"],
    "deadline":  ["마감", "언제까지", "기한", "며칠 남", "기간"],
    "amount":    ["얼마", "금액", "지원금", "얼마나 받", "수령"],
    "eligible":  ["자격", "조건", "대상", "될까", "되나요", "해당되", "받을 수 있"],
    "duplicate": ["중복", "같이 받", "동시에 받", "겹치"],
}
# 특정 정책이 아니라 "뭐가 있는지" 둘러보는 질문
BROWSE_PATTERNS = ["뭐 있", "뭐가 있", "어떤 게 있", "어떤게 있", "어떤 정책",
                   "추천해", "추천 좀", "알려줘 뭐", "목록", "리스트", "종류"]
# 후속 질문에서 직전 정책을 이어받아도 되는 의도
FOLLOWUP_INTENTS = {"apply", "docs", "deadline", "amount", "eligible"}


def detect_intents(question):
    found = [intent for intent, pats in INTENT_PATTERNS.items()
             if any(p in question for p in pats)]
    return found or ["general"]


def is_browse(question):
    return any(p in question for p in BROWSE_PATTERNS)


# ──────────────────────────────────────────────
# 2) 정책 검색 (이름 매칭 → 하이브리드 → 대화 맥락)
# ──────────────────────────────────────────────
def _norm(s):
    return re.sub(r"[^가-힣A-Za-z0-9]", "", str(s or ""))


# 의도 표현·의문사 등 검색에 도움 안 되는 토큰
_STOP_TOKENS = {"신청", "방법", "서류", "마감", "얼마", "금액", "자격", "조건",
                "대상", "정책", "지원", "알려줘", "알려", "궁금", "필요", "청년",
                "뭐가", "뭔가", "무엇", "어떤", "어떻게", "언제", "어디", "어디서",
                "얼마나", "있어", "있나요", "인가요", "해야", "해줘", "주세요",
                "가능", "받아", "받나요", "받을"}


# 어미·조사 (긴 것부터 벗겨서 대조 — "서류는"→서류, "필요해요"→필요)
_PARTICLES = ("인가요", "이랑", "에서", "으로", "해요", "은", "는", "이", "가",
              "을", "를", "도", "만", "랑", "로", "에", "의", "요", "해")


def _is_stop(t):
    if t in _STOP_TOKENS:
        return True
    for p in _PARTICLES:
        if t.endswith(p) and t[:-len(p)] and t[:-len(p)] in _STOP_TOKENS:
            return True
    return False


def _tokens(question):
    """내용 토큰만 추출 — 의도어·의문사는 조사가 붙은 형태까지 불용어 처리.
    '청년월세' 같은 복합어는 남는다(정확 대조라 '청년' 접두에 안 걸림)."""
    return {t for t in re.findall(r"[가-힣A-Za-z0-9]{2,}", question)
            if not _is_stop(t)}


def _lexical_boost(q_tokens, policy):
    """질문 토큰이 정책명/키워드에 실제로 등장하면 가산 (의미검색 오매칭 보정)"""
    name = _norm(policy.get("name"))
    kws = [_norm(k) for k in policy.get("keywords", [])]
    boost = 0.0
    for t in q_tokens:
        if t in name:
            boost += 0.18
        elif any(t in k or k in t for k in kws if k):
            boost += 0.10
    return min(boost, 0.40)


def hybrid_rank(question, results, matcher):
    """의미 유사도 + 어휘 부스트로 추천 결과를 순위화 → [(policy, score)]"""
    q_tokens = _tokens(question)
    if matcher is not None:
        sem = matcher.score(question)
        by_id = {p.get("id"): s for p, s in zip(matcher.policies, sem)}
    else:
        by_id = {}
    scored = [(r, by_id.get(r.get("id"), 0.0) + _lexical_boost(q_tokens, r))
              for r in results]
    scored.sort(key=lambda x: -x[1])
    return scored


_ORDINAL_WORDS = {"첫": 1, "두": 2, "세": 3, "네": 4, "다섯": 5,
                  "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10}


def _ordinal_index(question):
    """'첫 번째 정책'·'2번 정책'·'마지막 정책' 같은 순서 지칭 → 추천 목록 인덱스"""
    q = question.replace(" ", "")
    m = re.search(r"(첫|두|세|네|다섯|여섯|일곱|여덟|아홉|열)번째", q)
    if m:
        return _ORDINAL_WORDS[m.group(1)] - 1
    m = re.search(r"(\d{1,2})번(?:째)?(?:정책|거|것|추천)", q)
    if m and int(m.group(1)) >= 1:
        return int(m.group(1)) - 1
    if re.search(r"(맨위|제일위|첫)(정책|거|것|추천)", q):
        return 0
    if "마지막" in q:
        return -1
    return None


def find_policy(question, results, matcher, last_policy_id=None, intents=None):
    """질문이 가리키는 정책 1건 (없으면 None)"""
    qn = _norm(question)
    # ① 정책명 직접 매칭 (긴 이름 우선)
    named = [r for r in results
             if len(_norm(r["name"])) >= 4 and _norm(r["name"]) in qn]
    if named:
        return max(named, key=lambda r: len(_norm(r["name"])))
    # ①-2 순서 지칭 ("첫 번째 정책 신청 방법") — 추천 목록 순위로 해석
    idx = _ordinal_index(question)
    if idx is not None and -len(results) <= idx < len(results):
        return results[idx]

    def last_policy():
        if last_policy_id and intents and (set(intents) & FOLLOWUP_INTENTS):
            for r in results:
                if r.get("id") == last_policy_id:
                    return r
        return None

    # ② 내용 토큰이 없는 후속 질문("서류는 뭐가 필요해?")은 직전 정책을 우선
    if not _tokens(question):
        return last_policy()
    # ③ 하이브리드 검색 — 확신 높을 때만 특정 정책으로 단정
    ranked = hybrid_rank(question, results, matcher)
    if ranked and ranked[0][1] >= 0.60:
        return ranked[0][0]
    # ④ 검색이 애매하면 직전 대화의 정책을 이어받음
    return last_policy()


# ──────────────────────────────────────────────
# 3) 답변 템플릿 (구조화 필드만 사용)
# ──────────────────────────────────────────────
FOOTER = ("\n\n---\n:gray[규칙 기반 답변 — 등록된 정책 데이터만 사용해요. "
          "최종 확인은 각 기관 공식 공고문을 따라주세요.]")


def _deadline_line(p):
    d = p.get("days_left")
    if d is None:
        return "**상시 접수** 정책이라 준비되는 대로 신청할 수 있어요."
    return (f"**{p.get('apply_end', '')}** 마감 (D-{d})"
            + (" — 서두르는 게 좋아요! ⏰" if d <= 14 else ""))


def _apply_answer(p):
    lines = [f"**「{p['name']}」 신청 안내** ({p.get('org', '')})",
             f"- 신청 기간: {_deadline_line(p)}",
             f"- 접수 상태: {p.get('status_label', '확인 필요')}"]
    if p.get("url"):
        lines.append(f"- 신청/상세 페이지: {p['url']}")
        lines.append("- 위 링크에서 공고문을 확인하고 온라인으로 접수하는 방식이 일반적이에요.")
    else:
        lines.append("- 신청 링크가 등록돼 있지 않아요. 주관기관 홈페이지에서 공고문을 확인해 주세요.")
    return "\n".join(lines)


def _docs_answer(p):
    checks = p.get("checklist") or []
    lines = [f"**「{p['name']}」 신청 전 준비하면 좋은 것들**"]
    lines += [f"- {c}" for c in checks[:6]]
    lines.append("- 정확한 제출 서류 목록은 공고문에 명시돼요"
                 + (f": {p['url']}" if p.get("url") else "."))
    return "\n".join(lines)


def _deadline_answer(p):
    return f"**「{p['name']}」 마감 정보**\n- {_deadline_line(p)}"


def _amount_answer(p):
    label = p.get("amount_label") or "공고문에서 확인 필요"
    lines = [f"**「{p['name']}」 지원 규모**", f"- {label}"]
    kw = " ".join(p.get("keywords", [])) + p.get("name", "")
    if any(k in kw for k in ("대출", "융자")):
        lines.append("- 이 정책은 **대출**이라 갚아야 하는 돈이에요. 금리·상환 조건을 꼭 확인하세요.")
    if any(k in kw for k in ("저축", "자산형성", "통장")):
        lines.append("- 본인 저축과 매칭되는 **자산형성** 방식이라 만기까지 유지해야 전액을 받아요.")
    return "\n".join(lines)


def _eligible_answer(p, user):
    lines = [f"**「{p['name']}」 자격 판정 결과** (규칙 기반)"]
    lines += [f"- ✅ {m}" for m in (p.get("matched") or [])[:5]]
    notes = p.get("notes") or []
    lines += [f"- ⚠️ {n}" for n in notes]
    if not notes:
        lines.append("- 입력하신 정보 기준으로는 자격 요건을 충족해요. "
                     "다만 최종 판정은 기관 심사에서 확정돼요.")
    return "\n".join(lines)


def _duplicate_answer(p):
    name = f"「{p['name']}」" if p else "정책 간"
    return (f"**{name} 중복 수급 여부**\n"
            "- 중복 수급 가능 여부는 공공데이터에 구조화돼 있지 않아서, "
            "이 서비스가 단정해서 답해드릴 수 없어요.\n"
            "- 일반적으로 **같은 목적의 현금성 지원**(예: 월세지원 2개)은 중복이 제한되는 "
            "경우가 많고, 목적이 다른 지원(주거+교육)은 병행 가능한 경우가 많아요.\n"
            "- 정확한 판단은 각 정책 공고문의 '중복 지원 제한' 항목 또는 주관기관 문의로 "
            "확인해 주세요." + (f"\n- 문의처: {p['url']}" if p and p.get("url") else ""))


def _general_answer(question, results, matcher, user):
    ranked = [(r, s) for r, s in hybrid_rank(question, results, matcher)[:3] if s >= 0.40]
    if not ranked:
        return ("질문과 관련된 정책을 추천 목록에서 찾지 못했어요. 🥲\n"
                "- 정책 이름을 함께 적어주시거나 (예: \"청년월세 신청 방법\")\n"
                "- \"첫 번째 정책\"처럼 추천 순서로 물어봐도 돼요\n"
                "- \"월세\", \"장학금\", \"자격증\" 같은 키워드로 물어봐 주세요.")
    lines = [f"질문과 관련해 {user.name}님이 신청을 검토할 수 있는 정책이에요:"]
    for i, (r, s) in enumerate(ranked, 1):
        d = r.get("days_left")
        dl = "상시" if d is None else f"D-{d}"
        amt = r.get("amount_label") or "금액 공고문 참조"
        lines.append(f"{i}. **{r['name']}** — 적합도 {r.get('fit', '?')}% · {amt} · {dl}")
    lines.append("\n특정 정책의 *신청 방법 / 서류 / 마감 / 금액 / 자격*이 궁금하면 "
                 "정책 이름과 함께 물어봐 주세요!")
    return "\n".join(lines)


# ──────────────────────────────────────────────
# 메인 엔트리
# ──────────────────────────────────────────────
def answer(question, results, matcher, user, last_policy_id=None):
    """질문 → (마크다운 답변, 이번에 다룬 정책 id) — 구조화 필드 기반, 환각 없음"""
    if not results:
        return ("아직 추천 결과가 없어요. 먼저 정보를 입력하고 분석을 실행해 주세요."
                + FOOTER), None

    intents = detect_intents(question)

    if "duplicate" in intents:
        pol = find_policy(question, results, matcher, last_policy_id, intents)
        return _duplicate_answer(pol) + FOOTER, (pol or {}).get("id") or last_policy_id

    if is_browse(question):               # "장학금 뭐 있어?" → 목록형 답변
        return _general_answer(question, results, matcher, user) + FOOTER, None

    pol = find_policy(question, results, matcher, last_policy_id, intents)
    if pol is None:
        return _general_answer(question, results, matcher, user) + FOOTER, None

    handlers = {"apply": _apply_answer, "docs": _docs_answer,
                "deadline": _deadline_answer, "amount": _amount_answer}
    sections = []
    for intent in intents:
        if intent in handlers:
            sections.append(handlers[intent](pol))
        elif intent == "eligible":
            sections.append(_eligible_answer(pol, user))
    if not sections:                      # 정책은 특정됐지만 의도가 일반적
        sections.append(_apply_answer(pol))
        sections.append(_deadline_answer(pol))
    return "\n\n".join(sections) + FOOTER, pol.get("id")


# ──────────────────────────────────────────────
# 단독 테스트
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    from recommender import UserProfile, load_policies, recommend, InterestMatcher

    policies, as_of = load_policies()
    user = UserProfile(name="김청년", age=25, region="서울", status="대학생",
                       housing="무주택", income_pct=100, interests=["주거·독립"])
    matcher = InterestMatcher(policies, use_embeddings=True)
    results = recommend(user, policies, as_of, matcher=matcher)

    tests = [
        "청년월세 신청 방법 알려줘",
        "서류는 뭐가 필요해?",          # ← 직전 정책(월세) 이어받아야 함
        "월세 지원이랑 장학금 같이 받을 수 있어?",
        "장학금 뭐 있어?",              # ← 목록형
        "국가장학금 얼마나 받아?",
        "아무말대잔치",
    ]
    last_id = None
    for q in tests:
        print("=" * 60)
        print("Q:", q, f"(맥락: {last_id})")
        text, last_id = answer(q, results, matcher, user, last_id)
        print(text.replace(FOOTER, "").strip())
        print()
