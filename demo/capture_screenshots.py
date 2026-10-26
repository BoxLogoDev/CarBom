#!/usr/bin/env python3
"""카봄 웹 데모의 앱 화면 시안 스크린샷을 캡처한다.

demo.js 의 쿼리 지정 기능(?scenario=...&step=...)으로 시나리오와 단계를
고정한 뒤, headless Chrome 으로 차량 화면 + 운전자 폰 화면을 PNG 로 저장한다.
출력은 접수양식 참고자료용 시안 폴더이며, 인자 없이 재실행하면 덮어쓴다.

실행: python3 demo/capture_screenshots.py
"""

import subprocess
import sys
from pathlib import Path

CHROME = "/opt/meta-chromium/chrome"
DEMO_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = Path.home() / "workspace" / "goals" / "pleos" / "files" / "시안"
WINDOW_SIZE = "1180,900"

SHOTS = [
    # (파일명, 시나리오, 단계 번호(1부터))
    ("카봄-시안-01-등원정상-도착확인.png", "dropoff_normal", 4),
    ("카봄-시안-02-하차깜빡-긴급알림.png", "forgotten_rising_temp", 8),
    ("카봄-시안-03-반려동물-하차완료.png", "pet_dropoff", 6),
]


def capture(filename, scenario, step):
    url = (DEMO_DIR / "index.html").as_uri() + "?scenario=%s&step=%d" % (scenario, step)
    out = OUTPUT_DIR / filename
    cmd = [
        CHROME,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--hide-scrollbars",
        "--virtual-time-budget=2000",
        "--window-size=" + WINDOW_SIZE,
        "--screenshot=" + str(out),
        url,
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for filename, scenario, step in SHOTS:
        out = capture(filename, scenario, step)
        data = out.read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            print("PNG 시그니처가 아닙니다: %s" % out, file=sys.stderr)
            return 1
        print("%s (%d bytes)" % (out, len(data)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
