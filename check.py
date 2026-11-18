#!/usr/bin/env python3
"""
Jednorazowe sprawdzenie bitomatów Shitcoins.club (uruchamiane co 5 min przez GitHub Actions).
Poprzedni stan trzyma w state.json (workflow commituje go do repo), żeby wiedzieć,
kiedy bitomat przeszedł z 0 zł na > 0 zł.

Sekrety (Settings -> Secrets and variables -> Actions):
  TELEGRAM_TOKEN     - token od @BotFather
  TELEGRAM_CHAT_IDS  - numery chat_id po przecinku, np. 123456789,987654321
"""

import json
import os
import sys
from pathlib import Path

from curl_cffi import requests as http

CITIES = ["Kraków", "Tarnów"]   # miasta do pilnowania
MIN_PLN = 1                     # próg "są środki"
ALERT_AFTER_ERRORS = 3          # po ilu nieudanych sprawdzeniach z rzędu wysłać ostrzeżenie

BASE = "https://shitcoins.club"
API = f"{BASE}/atms/getAtmsWithMoney?country=pl"
HEADERS = {
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Accept-Language": "pl-PL,pl;q=0.9",
    "Referer": f"{BASE}/pl/mapa-bitomatow",
    "X-Requested-With": "XMLHttpRequest",
}
STATE = Path(__file__).with_name("state.json")

TOKEN = os.environ.get("TELEGRAM_TOKEN", "").strip()
CHAT_IDS = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_IDS", "").split(",") if c.strip()]


def telegram(text):
    print("TELEGRAM:", text.replace("\n", " / "))
    if not TOKEN or not CHAT_IDS:
        print("  (brak sekretów TELEGRAM_TOKEN / TELEGRAM_CHAT_IDS - nie wysyłam)")
        return
    for chat in CHAT_IDS:
        try:
            r = http.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", timeout=15,
                          json={"chat_id": chat, "text": text, "disable_web_page_preview": True})
            if r.status_code != 200:
                print(f"  Telegram ({chat}) błąd: {r.text[:200]}")
        except Exception as e:
            print(f"  Telegram ({chat}) wyjątek: {e}")


def fetch():
    r = http.get(API, headers=HEADERS, timeout=30, impersonate="chrome")
    r.raise_for_status()
    wanted = {c.casefold() for c in CITIES}
    out = {}
    for a in r.json()["message"][0]:
        city = (a.get("city") or "").strip()
        if city.casefold() not in wanted or not a.get("enabled", True):
            continue
        pln = sum(float(v or 0) for v in (a.get("cassetteState") or {}).values())
        name = " ".join((a.get("shoppingCenter") or "").replace("<br>", " ").split()).rstrip(",")
        if city.casefold() not in name.casefold():
            name = f"{city}, {name}"
        out[str(a["id"])] = {"name": name, "pln": pln, "url": BASE + (a.get("urlMapping") or "")}
    return out


def main():
    first_run = not STATE.exists()
    state = json.loads(STATE.read_text()) if not first_run else {"atms": {}, "errors": 0}

    try:
        cur = fetch()
    except Exception as e:
        state["errors"] = state.get("errors", 0) + 1
        print(f"Błąd pobierania ({state['errors']} z rzędu): {e}")
        if state["errors"] == ALERT_AFTER_ERRORS:
            telegram(f"⚠️ Nie mogę pobrać danych z shitcoins.club ({state['errors']}x z rzędu): {e}")
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))
        return

    if state.get("errors", 0) >= ALERT_AFTER_ERRORS:
        telegram("✅ Znowu pobieram dane z shitcoins.club.")
    state["errors"] = 0

    for v in cur.values():
        print(f"{v['name']}: {v['pln']:.0f} zł")

    if first_run:
        telegram(f"👀 Start pilnowania bitomatów ({', '.join(CITIES)}) na GitHubie, co ~5 min:\n"
                 + "\n".join(f"• {v['name']}: {v['pln']:.0f} zł" for v in cur.values()))

    prev = state.get("atms", {})
    for atm_id, v in cur.items():
        was = prev.get(atm_id, {}).get("pln", 0)
        if v["pln"] >= MIN_PLN and was < MIN_PLN and not first_run:
            telegram(f"💰 SĄ ŚRODKI: {v['pln']:.0f} zł\n📍 {v['name']}\n{v['url']}")
        elif v["pln"] < MIN_PLN and was >= MIN_PLN:
            telegram(f"❌ {v['name']} - znowu 0 zł")
        elif first_run and v["pln"] >= MIN_PLN:
            telegram(f"💰 Już teraz są środki: {v['pln']:.0f} zł\n📍 {v['name']}\n{v['url']}")

    # zapisujemy tylko kwoty, żeby state.json zmieniał się (i był commitowany) tylko przy realnej zmianie
    state["atms"] = {k: {"name": v["name"], "pln": v["pln"]} for k, v in cur.items()}
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True))


if __name__ == "__main__":
    main()
    sys.exit(0)
