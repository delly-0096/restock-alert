# -*- coding: utf-8 -*-
"""
SMTOWN &STORE 재입고 알림 - GitHub Actions 버전
한 번 실행될 때마다 재고를 한 번 확인하고, 품절이 풀렸으면 디스코드로 알립니다.
직전 상태는 state.json 에 저장해서, 재입고된 순간에만 알림이 갑니다.
"""
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone

# ====================== 바꾸고 싶으면 여기만 ======================
PRODUCT_URL = (
    "https://smtownandstore.com/product/"
    "2025-nct-wish-1st-concert-tour-into-the-wish-our-wish-scrunchie/"
    "27705/category/53/display/1/"
)
PRODUCT_NAME = "NCT WISH 'INTO THE WISH Our WISH' SCRUNCHIE"
MEMBERS = ["RIKU", "YUSHI"]
HEARTBEAT_MINUTES = 60   # 이 간격마다 "정상 작동 중" 무음 메시지 (0이면 끔)
# =================================================================

WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
MANUAL_RUN = os.environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
STATE_FILE = "state.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/130.0 Safari/537.36")


def fetch_html():
    req = urllib.request.Request(PRODUCT_URL, headers={
        "User-Agent": UA,
        "Accept-Language": "ko-KR,ko;q=0.9",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def parse_stock(html):
    m = re.search(r"option_stock_data\s*=\s*'(.*?)';", html, re.S)
    if not m:
        return None
    raw = m.group(1).replace("\\'", "'")
    try:
        data = json.loads(json.loads('"' + raw + '"'))
    except Exception:
        try:
            data = json.loads(raw)
        except Exception:
            return None
    result = {}
    for item in data.values():
        if not isinstance(item, dict):
            continue
        name = str(item.get("option_value") or item.get("option_value_orginal") or "")
        selling = item.get("is_selling", "T") != "F"
        displayed = item.get("is_display", "T") != "F"
        use_stock = item.get("use_stock") in (True, "T", "true")
        try:
            stock = int(item.get("stock_number", 0))
        except (TypeError, ValueError):
            stock = 0
        result[name] = selling and displayed and not (use_stock and stock <= 0)
    return result


def member_status(stock):
    status = {}
    for member in MEMBERS:
        hits = [ok for name, ok in stock.items() if member.upper() in name.upper()]
        status[member] = any(hits) if hits else None
    return status


def send_discord(text, silent=False):
    payload = {"content": text}
    if silent:
        payload["flags"] = 4096   # 폰이 울리지 않는 무음 메시지
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(WEBHOOK, data=body, headers={
        "Content-Type": "application/json",
        "User-Agent": "restock-alert/1.0",
    })
    with urllib.request.urlopen(req, timeout=30) as r:
        r.read()


def load_state():
    try:
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")


def label(ok):
    return "구매가능" if ok else "옵션없음?" if ok is None else "품절"


def main():
    if not WEBHOOK.startswith("https://"):
        sys.exit("DISCORD_WEBHOOK_URL 시크릿이 등록되지 않았어요.")

    state = load_state()
    new_state = dict(state)

    error = None
    status = None
    try:
        stock = parse_stock(fetch_html())
        if stock is None:
            error = "페이지에서 재고 데이터를 찾지 못했어요 (구조가 다르거나 접속이 차단됨)"
        else:
            print("전체 옵션:", stock)
            status = member_status(stock)
    except Exception as e:
        error = f"사이트 접속 실패: {e}"

    if error:
        print("오류:", error)
        # 오류가 시작된 순간에만 한 번 알림
        if not state.get("_error") or MANUAL_RUN:
            send_discord(f"⚠️ 재입고 알림(GitHub): {error}")
        new_state["_error"] = True
    else:
        new_state["_error"] = False
        summary = "  ".join(f"{m}: {label(ok)}" for m, ok in status.items())
        print(summary)
        for member, ok in status.items():
            if ok and not state.get(member):
                send_discord(
                    f"@everyone 🚨 **{member} 재입고!** {PRODUCT_NAME}\n{PRODUCT_URL}")
                print(f"{member} 재입고 알림 전송")
            new_state[member] = bool(ok)
        if MANUAL_RUN:
            send_discord(f"✅ GitHub 재입고 알림 작동 확인\n{summary}\n{PRODUCT_URL}")
            new_state["_last_heartbeat"] = int(time.time())

    # 주기적으로 "정상 작동 중" 무음 메시지
    if HEARTBEAT_MINUTES > 0:
        now = int(time.time())
        last = int(new_state.get("_last_heartbeat") or 0)
        if now - last >= HEARTBEAT_MINUTES * 60 - 150:
            kst = datetime.now(timezone(timedelta(hours=9))).strftime("%m/%d %H:%M")
            line = f"⚠️ 오류 지속 중: {error}" if error else summary
            send_discord(f"🟢 {kst} 작동 중 | {line}", silent=True)
            new_state["_last_heartbeat"] = now

    if new_state != state:
        save_state(new_state)


if __name__ == "__main__":
    main()
