import json
import re
import urllib.request
from datetime import datetime, timezone

HOME_URL = "https://stats.baseball.cz/en/events/extraliga-2026/home"

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


def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def html_to_lines(html):
    """Strip alle HTML-tags en geef een lijst van niet-lege regels terug."""
    # Verwijder script/style blokken volledig
    html = re.sub(r'<(script|style)[^>]*>.*?</\1>', ' ', html, flags=re.DOTALL)
    # Zet block-tags om naar newlines
    html = re.sub(r'<br\s*/?>', '\n', html)
    html = re.sub(r'</(?:div|p|li|tr|td|th|h[1-6]|section|article)>', '\n', html)
    # Verwijder resterende tags
    html = re.sub(r'<[^>]+>', ' ', html)
    # Decode HTML-entities
    html = html.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>').replace('&nbsp;', ' ')
    # Normaliseer whitespace per regel
    lines = []
    for line in html.splitlines():
        line = re.sub(r'[ \t]+', ' ', line).strip()
        if line:
            lines.append(line)
    return lines


def parse_datetime(raw):
    """'20/06/2026 13:00 (UTC +2) - Final' → ('2026-06-20', '13:00', True)"""
    m = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', raw)
    if not m:
        return None, None, False
    dt = datetime.strptime(m.group(1) + ' ' + m.group(2), "%d/%m/%Y %H:%M")
    is_final = bool(re.search(r'\bfinal\b', raw, re.IGNORECASE))
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M"), is_final


def parse_games(html):
    # Knip de "Up Next"-sectie uit
    m = re.search(
        r'Up Next Extraliga \d{4}(.*?)(?:Schedule\s*(?:&amp;|&)\s*Results|Tournament Leaders)',
        html, re.DOTALL | re.IGNORECASE
    )
    if not m:
        print("⚠️  'Up Next'-sectie niet gevonden in HTML")
        # Debug: toon de eerste 2000 chars
        lines = html_to_lines(html)
        print("  Eerste 30 regels HTML:")
        for l in lines[:30]:
            print(f"    {repr(l)}")
        return [], []

    section = m.group(1)
    lines = html_to_lines(section)

    print(f"Up Next sectie: {len(lines)} regels")
    for i, l in enumerate(lines[:60]):
        print(f"  {i:3}: {repr(l)}")

    uitslagen = []
    programma = []
    i = 0

    while i < len(lines):
        # Score-regel: "3 : 13" of "0 : 0"
        score_m = re.match(r'^(\d+)\s*:\s*(\d+)$', lines[i])
        if score_m:
            score_uit   = int(score_m.group(1))
            score_thuis = int(score_m.group(2))

            # Zoek uit_code: de 3-letter code vlak VOOR de score
            # (meestal 1-2 regels terug, na "Visitor" en een img)
            uit_code = None
            for j in range(i - 1, max(i - 5, -1), -1):
                if re.match(r'^[A-Z]{3}$', lines[j]):
                    uit_code = lines[j]
                    break

            # Zoek thuis_code en datum ACHTER de score
            thuis_code = None
            datum_str = tijdstip_str = None
            is_final = False

            for j in range(i + 1, min(i + 10, len(lines))):
                if re.match(r'^[A-Z]{3}$', lines[j]) and thuis_code is None:
                    thuis_code = lines[j]
                if re.search(r'\d{2}/\d{2}/\d{4}', lines[j]):
                    datum_str, tijdstip_str, is_final = parse_datetime(lines[j])
                    break

            if uit_code and thuis_code and datum_str:
                wedstrijd = {
                    "datum":       datum_str,
                    "tijdstip":    tijdstip_str,
                    "thuis":       TEAM_CODES.get(thuis_code, thuis_code),
                    "thuis_code":  thuis_code,
                    "uit":         TEAM_CODES.get(uit_code, uit_code),
                    "uit_code":    uit_code,
                    "score_thuis": score_thuis if is_final else None,
                    "score_uit":   score_uit   if is_final else None,
                    "gamestatus":  "F" if is_final else "",
                    "gespeeld":    is_final,
                    "locatie":     None,
                }
                if is_final:
                    uitslagen.append(wedstrijd)
                else:
                    programma.append(wedstrijd)
            else:
                print(f"  ⚠️  Score gevonden op regel {i} maar parsing mislukt: "
                      f"uit={uit_code} thuis={thuis_code} datum={datum_str}")

        i += 1

    return uitslagen, programma


def main():
    print(f"Ophalen van {HOME_URL}...")
    html = fetch_html(HOME_URL)
    print(f"Ontvangen: {len(html)} bytes")

    uitslagen, programma = parse_games(html)

    print(f"\nGespeelde wedstrijden ({len(uitslagen)}):")
    for u in uitslagen:
        print(f"  {u['datum']} {u['tijdstip']}  {u['uit_code']} {u['score_uit']} - {u['score_thuis']} {u['thuis_code']}")

    print(f"\nProgramma ({len(programma)}):")
    for p in programma:
        print(f"  {p['datum']} {p['tijdstip']}  {p['uit_code']} @ {p['thuis_code']}")

    uitslagen.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))
    programma.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))

    output = {
        "bijgewerkt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bron":       HOME_URL,
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
