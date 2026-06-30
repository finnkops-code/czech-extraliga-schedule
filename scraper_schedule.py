"""
Czech Extraliga Schedule Scraper
Haalt data op via de Inertia.js JSON-payload die in de HTML is embedded,
of valt terug op Playwright DOM-extractie.
"""

import json
import re
import datetime as dt
from datetime import timezone
from playwright.sync_api import sync_playwright

SCHEDULE_URL = "https://stats.baseball.cz/en/events/extraliga-2026/schedule-and-results"
JSON_FILE    = "schedule_extraliga.json"

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


def format_dag(datum_str):
    dagen   = ["maandag","dinsdag","woensdag","donderdag","vrijdag","zaterdag","zondag"]
    maanden = ["","januari","februari","maart","april","mei","juni",
               "juli","augustus","september","oktober","november","december"]
    d = dt.datetime.strptime(datum_str, "%Y-%m-%d")
    return f"{dagen[d.weekday()]} {d.day} {maanden[d.month]}"


def parse_datum(raw):
    """'20/06/2026 13:00 (UTC +2) - Final' → (datum, tijdstip, is_final)"""
    m = re.search(r'(\d{2})/(\d{2})/(\d{4})\s+(\d{2}:\d{2})', raw)
    if not m:
        return None, None, False
    datum    = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    tijdstip = m.group(4)
    is_final = bool(re.search(r'\bfinal\b', raw, re.IGNORECASE))
    return datum, tijdstip, is_final


def extract_from_inertia(html):
    """Probeer de Inertia.js data-page payload te parsen."""
    m = re.search(r'data-page="([^"]+)"', html)
    if not m:
        return None
    try:
        payload = json.loads(m.group(1).replace('&quot;', '"').replace('&#039;', "'"))
        print(f"  Inertia payload gevonden, keys: {list(payload.get('props', {}).keys())}")
        return payload
    except Exception as e:
        print(f"  Inertia parse fout: {e}")
        return None


def extract_games_from_dom(page):
    """Extraheer wedstrijden via JS tree-walker in de browser DOM."""
    return page.evaluate("""
    () => {
        const games = [];
        const CODES = {
            "HRO":"Hroši","KOT":"Kotlářka","DRA":"Draci","HLU":"Hluboká",
            "NUC":"Nuclears","EAG":"Eagles","ARR":"Arrows","SAB":"SaBaT"
        };

        // Verzamel alle tekst-nodes
        const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
        const texts = [];
        let n;
        while (n = walker.nextNode()) {
            const t = n.textContent.trim();
            if (t) texts.push(t);
        }

        // Zoek score-patronen X : Y
        for (let i = 0; i < texts.length; i++) {
            const sm = texts[i].match(/^(\\d+)\\s*:\\s*(\\d+)$/);
            if (!sm) continue;

            const scoreUit   = parseInt(sm[1]);
            const scoreThuis = parseInt(sm[2]);

            // Zoek uit-code achteruit
            let uitCode = null;
            for (let j = i-1; j >= Math.max(0,i-6); j--) {
                if (/^[A-Z]{3}$/.test(texts[j])) { uitCode = texts[j]; break; }
            }

            // Zoek thuis-code en datum vooruit
            let thuisCode = null, datumRaw = null;
            for (let j = i+1; j < Math.min(texts.length, i+10); j++) {
                if (/^[A-Z]{3}$/.test(texts[j]) && !thuisCode) thuisCode = texts[j];
                if (/\\d{2}\\/\\d{2}\\/\\d{4}/.test(texts[j])) { datumRaw = texts[j]; break; }
            }

            if (!uitCode || !thuisCode || !datumRaw) continue;

            const dm = datumRaw.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})\\s+(\\d{2}:\\d{2})/);
            if (!dm) continue;

            const datum    = `${dm[3]}-${dm[2]}-${dm[1]}`;
            const tijdstip = dm[4];
            const isFinal  = /final/i.test(datumRaw);

            games.push({ datum, tijdstip, uitCode, thuisCode,
                         scoreUit, scoreThuis, isFinal });
        }
        return games;
    }
    """)


def main():
    print(f"Ophalen van {SCHEDULE_URL}...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        # Vang alle XHR/fetch responses op — misschien zit data in een API-call
        api_data = {}
        def handle_response(response):
            url = response.url
            if "json" in response.headers.get("content-type", "") and "wbsc" in url:
                try:
                    data = response.json()
                    api_data[url] = data
                    print(f"  API response: {url} ({type(data).__name__}, {len(str(data))} chars)")
                except Exception:
                    pass

        page.on("response", handle_response)

        page.goto(SCHEDULE_URL, wait_until="networkidle", timeout=30000)
        page.wait_for_timeout(2000)

        # Probeer eerst Inertia payload
        html = page.content()
        print(f"HTML: {len(html)} bytes")

        inertia = extract_from_inertia(html)
        if inertia:
            print(f"  Props: {json.dumps(list(inertia.get('props',{}).keys()))}")

        # Log alle gevangen API calls
        if api_data:
            print(f"\nGevangen API calls ({len(api_data)}):")
            for url, data in api_data.items():
                print(f"  {url}: {str(data)[:200]}")

        # Wacht op Visitor-tekst
        try:
            page.wait_for_selector("text=Visitor", timeout=8000)
            print("  ✓ 'Visitor' in DOM")
        except Exception:
            print("  ⚠️  'Visitor' niet gevonden")

        # Toon wat de pagina toont
        body_text = page.inner_text("body")
        print(f"\nPagina tekst (eerste 2000 chars):\n{body_text[:2000]}")

        # Extraheer wedstrijden via DOM
        raw_games = extract_games_from_dom(page)
        print(f"\n{len(raw_games)} wedstrijden in DOM gevonden")

        browser.close()

    # Verwerk resultaten
    uitslagen, programma = [], []
    for i, g in enumerate(raw_games):
        wedstrijd = {
            "id":           i + 1,
            "datum":        g["datum"],
            "tijdstip":     g["tijdstip"],
            "dag":          format_dag(g["datum"]),
            "thuis":        TEAM_CODES.get(g["thuisCode"], g["thuisCode"]),
            "thuis_code":   g["thuisCode"],
            "uit":          TEAM_CODES.get(g["uitCode"], g["uitCode"]),
            "uit_code":     g["uitCode"],
            "score_thuis":  g["scoreThuis"] if g["isFinal"] else None,
            "score_uit":    g["scoreUit"]   if g["isFinal"] else None,
            "thuis_innings": [],
            "uit_innings":   [],
            "innings":       None,
            "gamestatus":   "F" if g["isFinal"] else "",
            "locatie":      None,
            "stadion":      None,
            "gespeeld":     g["isFinal"],
        }
        if g["isFinal"]:
            uitslagen.append(wedstrijd)
        else:
            programma.append(wedstrijd)

    uitslagen.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))
    programma.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))

    print(f"\nUitslagen ({len(uitslagen)}):")
    for u in uitslagen:
        print(f"  {u['datum']} {u['tijdstip']}  {u['uit_code']} {u['score_uit']} - {u['score_thuis']} {u['thuis_code']}")
    print(f"\nProgramma ({len(programma)}):")
    for pp in programma:
        print(f"  {pp['datum']} {pp['tijdstip']}  {pp['uit_code']} @ {pp['thuis_code']}")

    output = {
        "bijgewerkt": dt.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bron":       SCHEDULE_URL,
        "uitslagen":  uitslagen,
        "programma":  programma,
    }

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {JSON_FILE}: {len(uitslagen)} uitslagen, {len(programma)} programma")


if __name__ == "__main__":
    main()
