import json
import re
import urllib.request
from datetime import datetime, timezone

HOME_URL = "https://stats.baseball.cz/en/events/extraliga-2026/home"

# 3-letter codes naar teamnamen (zoals ze in de HTML staan)
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

LOGO_URLS = {
    "HRO": "https://static.wbsc.org/upload/271efdd4-78f7-782b-19e9-ca7fd00cfee2.png",
    "KOT": "https://static.wbsc.org/upload/a7dffba8-f8b9-2a89-1883-b07093f1e5b4.png",
    "DRA": "https://static.wbsc.org/upload/6bea51c2-3d49-1230-97fe-bf3fd52ef27a.jpg",
    "HLU": "https://static.wbsc.org/upload/06ebf3e7-4094-4d7d-7bad-cd88e4ec3330.png",
    "NUC": "https://static.wbsc.org/upload/1ad273ca-49c9-52b7-3330-5aae326481f9.png",
    "EAG": "https://static.wbsc.org/upload/d41ed6a3-9cb2-6629-99f3-c02c2861b626.png",
    "ARR": "https://static.wbsc.org/upload/65fd09a8-3d13-c9be-e020-8c154128996e.png",
    "SAB": "https://static.wbsc.org/upload/e0cdbe49-5118-1882-4882-f10fd522553d.png",
}


def fetch_html(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def strip_tags(html):
    return re.sub(r'<[^>]+>', '', html).strip()


def parse_datetime(raw):
    """Parse '20/06/2026 13:00 (UTC +2)' → datum + tijdstip strings."""
    m = re.search(r'(\d{2}/\d{2}/\d{4})\s+(\d{2}:\d{2})', raw)
    if not m:
        return None, None
    dt = datetime.strptime(m.group(1) + ' ' + m.group(2), "%d/%m/%Y %H:%M")
    return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")


def parse_games(html):
    """
    Parst de 'Up Next' sectie van de homepage.
    Elke wedstrijd staat als een blok met:
      - Visitor code + score
      - Home code + score
      - Datum/tijd + status ('Final' of leeg)
    """
    # Knip de "Up Next" sectie uit
    upnext_match = re.search(
        r'Up Next Extraliga 2026(.*?)(?:Schedule &amp; Results|Tournament Leaders)',
        html, re.DOTALL
    )
    if not upnext_match:
        print("⚠️  'Up Next' sectie niet gevonden")
        return [], []

    section = upnext_match.group(1)

    # Elke wedstrijd begint bij Visitor en eindigt bij de datum-regel
    # Patroon: blokken gescheiden door datum-regels
    # We zoeken op de 3-letter codes + scores
    game_blocks = re.split(
        r'(?=\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})',
        section
    )

    uitslagen = []
    programma = []

    # Herstart: parse per wedstrijd via een andere aanpak
    # Zoek op het patroon: code score : score code + datum
    wedstrijd_pattern = re.compile(
        r'([A-Z]{3})\s*\n\s*(\d+)\s*:\s*(\d+)\s*\n\s*([A-Z]{3})'
        r'.*?'
        r'(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2}.*?)(?=\n\n|\Z)',
        re.DOTALL
    )

    # Betere aanpak: extract alle wedstrijdblokken via datum als anker
    # Format in de HTML: "Visitor\n\nCODE\n\nSCORE : SCORE\n\nHome\n\nCODE\n\nDATE - STATUS"
    # Na strip_tags ziet het er zo uit

    # Strip HTML maar bewaar structuur
    text = re.sub(r'<br\s*/?>', '\n', section)
    text = re.sub(r'</(?:div|p|li|tr|td|th|h[1-6])>', '\n', text)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    lines = [l.strip() for l in text.splitlines() if l.strip()]

    # Zoek patronen: CODE \n score : score \n CODE \n datum
    i = 0
    while i < len(lines):
        # Zoek een regel met "X : Y" (score)
        score_match = re.match(r'^(\d+)\s*:\s*(\d+)$', lines[i])
        if score_match:
            score_uit = int(score_match.group(1))
            score_thuis = int(score_match.group(2))

            # Zoek de 3-letter codes voor en na de score
            uit_code = None
            thuis_code = None
            datum_str = None
            tijdstip_str = None
            is_final = False

            # Zoek achteruit voor uit_code
            for j in range(i - 1, max(i - 6, -1), -1):
                if re.match(r'^[A-Z]{3}$', lines[j]):
                    uit_code = lines[j]
                    break

            # Zoek vooruit voor thuis_code en datum
            for j in range(i + 1, min(i + 8, len(lines))):
                if re.match(r'^[A-Z]{3}$', lines[j]) and thuis_code is None:
                    thuis_code = lines[j]
                if re.search(r'\d{2}/\d{2}/\d{4}', lines[j]):
                    datum_str, tijdstip_str = parse_datetime(lines[j])
                    is_final = 'final' in lines[j].lower()
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
                    "score_uit":   score_uit if is_final else None,
                    "gamestatus":  "F" if is_final else "",
                    "gespeeld":    is_final,
                    "locatie":     None,
                }

                if is_final:
                    uitslagen.append(wedstrijd)
                else:
                    programma.append(wedstrijd)

        i += 1

    return uitslagen, programma


def main():
    print(f"Ophalen van {HOME_URL}...")
    html = fetch_html(HOME_URL)
    print(f"Ontvangen: {len(html)} bytes")

    uitslagen, programma = parse_games(html)

    print(f"\nGespeelde wedstrijden:")
    for u in uitslagen:
        print(f"  {u['datum']} {u['uit_code']} {u['score_uit']}-{u['score_thuis']} {u['thuis_code']}")

    print(f"\nProgramma:")
    for p in programma:
        print(f"  {p['datum']} {p['tijdstip']} {p['uit_code']} @ {p['thuis_code']}")

    # Sorteer
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
