import json
import re
import subprocess
import sys
from datetime import datetime, timezone

SCHEDULE_URL = "https://stats.baseball.cz/en/events/extraliga-2026/schedule-and-results"

TEAM_CODES = {
    "HRO": "Hroši",
    "KOT": "Kotlářka",
    "DRA": "Draci",
    "HLU": "Hluboká",
    "NUC": "Nuclears",
    "EAG": "Eagles",
    "ARR": "Arrows",
    "SAB": "SaBaT",
}


def install_playwright():
    subprocess.run([sys.executable, "-m", "pip", "install", "playwright", "-q"], check=True)
    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium", "--with-deps"], check=True)


def fetch_html_playwright(url):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30000)
        try:
            page.wait_for_selector("text=Visitor", timeout=10000)
        except Exception:
            print("  ⚠️  'Visitor' selector timeout")
        html = page.content()
        browser.close()
    return html


def html_to_lines(html):
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<br\s*/?>', '\n', html)
    html = re.sub(r'</(?:div|p|li|tr|td|th|h[1-6]|section|article)>', '\n', html)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
    lines = []
    for line in html.splitlines():
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if line:
            lines.append(line)
    return lines


def parse_datetime(raw):
    """'20/06/2026 13:00 (UTC +2) - Final' → datum, tijdstip, is_final"""
    m = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', raw)
    if not m:
        return None, None, False
    dt = datetime.strptime(m.group(1) + ' ' + m.group(2), "%d/%m/%Y %H:%M")
    is_final = bool(re.search(r'\bfinal\b', raw, re.IGNORECASE))
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), is_final


def format_dag(datum_str):
    """'2026-06-20' → 'zaterdag 20 juni'"""
    dagen = ["maandag","dinsdag","woensdag","donderdag","vrijdag","zaterdag","zondag"]
    maanden = ["","januari","februari","maart","april","mei","juni",
               "juli","augustus","september","oktober","november","december"]
    dt = datetime.strptime(datum_str, "%Y-%m-%d")
    return f"{dagen[dt.weekday()]} {dt.day} {maanden[dt.month]}"


def parse_games(html):
    lines = html_to_lines(html)
    print(f"Totaal regels na stripping: {len(lines)}")

    # Debug: toon alle score-regels met context
    print("\nScore-regels gevonden:")
    for i, l in enumerate(lines):
        if re.match(r'^\d+\s*:\s*\d+$', l):
            context = lines[max(0, i-4):i+5]
            print(f"  r{i}: {[repr(x) for x in context]}")

    uitslagen, programma = [], []
    game_id = 1
    i = 0

    while i < len(lines):
        score_m = re.match(r'^(\d+)\s*:\s*(\d+)$', lines[i])
        if score_m:
            score_uit   = int(score_m.group(1))
            score_thuis = int(score_m.group(2))

            # Zoek uit_code achteruit (3-letter hoofdletter code)
            uit_code = None
            for j in range(i - 1, max(i - 6, -1), -1):
                if re.match(r'^[A-Z]{3}$', lines[j]):
                    uit_code = lines[j]
                    break

            # Zoek thuis_code en datum vooruit
            thuis_code = datum_str = tijdstip_str = None
            is_final = False
            for j in range(i + 1, min(i + 10, len(lines))):
                if re.match(r'^[A-Z]{3}$', lines[j]) and thuis_code is None:
                    thuis_code = lines[j]
                if re.search(r'\d{2}/\d{2}/\d{4}', lines[j]):
                    datum_str, tijdstip_str, is_final = parse_datetime(lines[j])
                    break

            if uit_code and thuis_code and datum_str:
                w = {
                    "id":           game_id,
                    "datum":        datum_str,
                    "tijdstip":     tijdstip_str,
                    "dag":          format_dag(datum_str),
                    "thuis":        TEAM_CODES.get(thuis_code, thuis_code),
                    "thuis_code":   thuis_code,
                    "uit":          TEAM_CODES.get(uit_code, uit_code),
                    "uit_code":     uit_code,
                    "score_thuis":  score_thuis if is_final else None,
                    "score_uit":    score_uit   if is_final else None,
                    "thuis_innings": [],
                    "uit_innings":   [],
                    "innings":      None,
                    "gamestatus":   "F" if is_final else "",
                    "locatie":      None,
                    "stadion":      None,
                    "gespeeld":     is_final,
                }
                game_id += 1
                (uitslagen if is_final else programma).append(w)
            else:
                print(f"  ⚠️  Score op r{i} niet volledig: uit={uit_code} thuis={thuis_code} datum={datum_str}")
        i += 1

    return uitslagen, programma


def main():
    print("Playwright installeren...")
    install_playwright()

    print(f"\nOphalen van {SCHEDULE_URL} via Playwright...")
    html = fetch_html_playwright(SCHEDULE_URL)
    print(f"Ontvangen: {len(html)} bytes")

    uitslagen, programma = parse_games(html)

    uitslagen.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))
    programma.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print(f"\nGespeelde wedstrijden ({len(uitslagen)}):")
    for u in uitslagen:
        print(f"  {u['datum']} {u['tijdstip']}  {u['uit_code']} {u['score_uit']} - {u['score_thuis']} {u['thuis_code']}")

    print(f"\nProgramma ({len(programma)}):")
    for p in programma:
        print(f"  {p['datum']} {p['tijdstip']}  {p['uit_code']} @ {p['thuis_code']}")

    output = {
        "bijgewerkt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bron":       SCHEDULE_URL,
        "uitslagen":  uitslagen,
        "programma":  programma,
    }

    with open("schedule_extraliga.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ schedule_extraliga.json opgeslagen")
    print(f"   Uitslagen  : {len(uitslagen)}")
    print(f"   Programma  : {len(programma)}")


if __name__ == "__main__":
    main()
