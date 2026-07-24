# -*- coding: utf-8 -*-
"""
인증키 로더 — 같은 폴더의 .env 파일을 단일 진실 소스로 사용

⚠️ .env 값이 세션 환경변수보다 우선한다. (setx 실수로 잘못된 키가 시스템에
남아 있어도 .env가 맞으면 정상 동작 — 실제로 ONTONG_API_KEY에 다른 키가
setx돼 수집이 통째로 깨진 사고가 있었다.)

.env 형식:
    ONTONG_API_KEY=...
    ODCLOUD_API_KEY=...
키는 코드·깃에 절대 하드코딩하지 않는다(.env는 .gitignore로 제외).
단독 실행(python keys.py) 시 키 설정 현황을 마스킹해서 출력한다.
"""
import os

ENV_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
KEY_NAMES = ["ONTONG_API_KEY", "ODCLOUD_API_KEY", "SCHOLARSHIP_UDDI"]


def load(path=ENV_PATH):
    """.env 값을 환경변수에 주입한다. .env에 있는 키는 기존 환경변수를 덮어쓴다."""
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ[k.strip()] = v.strip().strip('"').strip("'")
    return True


def get_key(name):
    load()
    return os.environ.get(name)


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    found = load()
    print(f".env 파일: {'있음' if found else '없음'} ({ENV_PATH})")
    for name in KEY_NAMES:
        v = os.environ.get(name)
        masked = f"{v[:4]}…{v[-4:]} (길이 {len(v)})" if v else "미설정"
        print(f"  {name}: {masked}")
