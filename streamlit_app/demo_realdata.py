# -*- coding: utf-8 -*-
"""
실데이터 파이프라인: 4종 수집 결과 병합 → data/policies_real.json + 콘솔 추천 데모

  1) collect_ontongyouth.py / collect_gov24.py / collect_bokjiro.py /
     collect_scholarship.py 를 먼저 실행해 data/*.json 을 만든 뒤
  2) python demo_realdata.py       # 병합 + 중복 제거 + 추천 데모
     python demo_realdata.py --collect   # 키가 있으면 수집까지 한 번에

policies_real.json 이 존재하면 recommender/app이 자동으로 이를 사용하고
기준일도 오늘 날짜로 자동 전환된다.
"""
import argparse
import json
import os
import re
import sys
from datetime import date

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
OUT_PATH = os.path.join(DATA_DIR, "policies_real.json")

SOURCES = [
    ("온통청년", "ontongyouth.json"),
    ("정부24", "gov24.json"),
    ("복지로", "bokjiro.json"),
    ("장학재단", "scholarship.json"),
]


def norm_name(name):
    """중복 판정용 정책명 정규화 (공백·괄호·특수문자 제거)"""
    s = re.sub(r"\([^)]*\)", "", str(name))
    return re.sub(r"[^가-힣A-Za-z0-9]", "", s).lower()


def merge_sources():
    merged, seen = [], {}
    for label, fname in SOURCES:
        path = os.path.join(DATA_DIR, fname)
        if not os.path.exists(path):
            print(f"  - {label}: 파일 없음({fname}) → 건너뜀")
            continue
        with open(path, encoding="utf-8") as f:
            items = json.load(f)
        added = dup = 0
        if label == "온통청년" and len(items) == 0:
            print("  ⚠️ 핵심 데이터(온통청년)가 비어 있습니다! 일일 호출 한도 소진 시 "
                  "빈 파일일 수 있으니 collect_ontongyouth.py를 다시 실행하세요.")
        for p in items:
            key = norm_name(p.get("name"))
            if not key:
                continue
            if key in seen:
                # 중복이면 정보가 더 풍부한 쪽(금액·자격 필드 채워진 쪽)을 유지
                old = seen[key]
                if (p.get("amount_max") and not old.get("amount_max")):
                    merged[merged.index(old)] = p
                    seen[key] = p
                dup += 1
                continue
            seen[key] = p
            merged.append(p)
            added += 1
        print(f"  - {label}: {len(items)}건 중 {added}건 추가 (중복 {dup}건)")
    return merged


def run_collectors():
    import subprocess
    for script in ("collect_ontongyouth.py", "collect_gov24.py",
                   "collect_bokjiro.py", "collect_scholarship.py"):
        print(f"\n▶ {script} 실행")
        subprocess.run([sys.executable, "-X", "utf8",
                        os.path.join(BASE_DIR, script)], check=False)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="실데이터 병합 + 추천 데모")
    ap.add_argument("--collect", action="store_true", help="수집기 4종을 먼저 실행")
    args = ap.parse_args()

    if args.collect:
        run_collectors()

    print("\n[1/2] 4종 데이터 병합")
    merged = merge_sources()
    if not merged:
        print("병합할 데이터가 없습니다. 수집기를 먼저 실행하세요. "
              "(키가 없으면 각 수집기의 --demo로 매핑 검증만 가능)")
        sys.exit(1)

    from datetime import datetime
    payload = {"as_of": date.today().strftime("%Y.%m.%d"),
               "collected_at": datetime.now().strftime("%Y.%m.%d %H:%M"),
               "policies": merged}
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"  → {len(merged)}건 저장: {OUT_PATH} (기준일 {payload['as_of']})")

    print("\n[2/2] 실데이터 추천 데모")
    from recommender import (UserProfile, recommend, load_policies,
                             estimate_total_support, format_amount, generate_one_liner)
    policies, as_of = load_policies(OUT_PATH)
    user = UserProfile(name="임주형", age=25, region="서울", status="대학생",
                       housing="무주택", income_pct=100,
                       interests=["주거·독립", "학비·장학금"])
    results = recommend(user, policies, as_of)
    total, counted = estimate_total_support(results)
    print(f"  자격 충족 {len(results)}건 / 추정 총 지원 규모 약 {format_amount(total)} "
          f"({counted}건 기준 추정치)")
    for i, r in enumerate(results[:5], 1):
        d = r["days_left"]
        print(f"  [{i}] {r['name']} — {r['fit']}% ({r['org']}, "
              f"{'상시' if d is None else f'D-{d}'})")
    print("\n💬", generate_one_liner(results, user))


if __name__ == "__main__":
    main()
