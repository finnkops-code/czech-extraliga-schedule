import json
import re
import subprocess
import sys
import datetime as dt
from datetime import timezone, timedelta
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

# JavaScript dat direct in de browser-DOM de wedstrijddata uitpikt
EXTRACT_JS = """
() => {
    const results = [];

    // Debug: log alle tekst op de pagina die op scores lijkt
    console.log('DOM ready, zoeken naar wedstrijden...');

    // Probeer verschillende selectors die WBSC-platforms gebruiken
    const selectors = [
        '.game-card', '.game', '.match', '.fixture',
        '[class*="game"]', '[class*="match"]', '[class*="fixture"]',
        'tr', 'li'
    ];

    // Zoek score-patronen: "X : Y" of "X - Y" met teamcodes
    // WBSC-structuur: Visitor / teamcode / score / Home / teamcode / datum
    const allText = document.body.innerText;
    console.log('Eerste 2000 chars:', allText.substring(0, 2000));

    // Zoek alle elementen met 3-letter teamcodes
    const walker = document.createTreeWalker(
        document.body,
        NodeFilter.SHOW_TEXT,
        null
    );

    const textNodes = [];
    let node;
    while (node = walker.nextNode()) {
        const t = node.textContent.trim();
        if (t.length > 0) textNodes.push(t);
    }

    console.log('Totaal tekstknopen:', textNodes.length);

    // Zoek score-patronen
    for (let i = 0; i < textNodes.length; i++) {
        const t = textNodes[i];
        if (/^\\d+\\s*:\\s*\\d+$/.test(t)) {
            const context = textNodes.slice(Math.max(0, i-5), i+6);
            console.log('SCORE gevonden:', JSON.stringify(context));
        }
    }

    return {
        url: window.location.href,
        title: document.title,
        textSample: allText.substring(0, 3000),
        textNodeCount: textNodes.length,
        scoreNodes: textNodes.filter(t => /^\\d+\\s*:\\s*\\d+$/.test(t)).length,
    };
}
"""

# Tweede JS: als we weten hoe de DOM eruit ziet, extraheer de wedstrijden
EXTRACT_GAMES_JS = """
() => {
    const games = [];
    const TEAM_CODES = {
        "HRO": "Hroši", "KOT": "Kotlářka", "DRA": "Draci", "HLU": "Hluboká",
        "NUC": "Nuclears", "EAG": "Eagles", "ARR": "Arrows", "SAB": "SaBaT",
    };

    // Haal alle tekstnodes op als platte array
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT, null);
    const texts = [];
    let node;
    while (node = walker.nextNode()) {
        const t = node.textContent.trim();
        if (t) texts.push(t);
    }

    // Loop door tekstnodes, zoek score-patronen
    for (let i = 0; i < texts.length; i++) {
        const scoreMatch = texts[i].match(/^(\\d+)\\s*:\\s*(\\d+)$/);
        if (!scoreMatch) continue;

        const scoreUit   = parseInt(scoreMatch[1]);
        const scoreThuis = parseInt(scoreMatch[2]);

        // Zoek uit_code achteruit
        let uitCode = null;
        for (let j = i - 1; j >= Math.max(0, i - 6); j--) {
            if (/^[A-Z]{3}$/.test(texts[j])) { uitCode = texts[j]; break; }
        }

        // Zoek thuis_code en datum vooruit
        let thuisCode = null, datumRaw = null;
        for (let j = i + 1; j < Math.min(texts.length, i + 10); j++) {
            if (/^[A-Z]{3}$/.test(texts[j]) && !thuisCode) thuisCode = texts[j];
            if (/\\d{2}\\/\\d{2}\\/\\d{4}/.test(texts[j])) { datumRaw = texts[j]; break; }
        }

        if (!uitCode || !thuisCode || !datumRaw) continue;

        // Parse datum: "20/06/2026 13:00 (UTC +2) - Final"
        const dmatch = datumRaw.match(/(\\d{2})\\/(\\d{2})\\/(\\d{4})\\s+(\\d{2}:\\d{2})/);
        if (!dmatch) continue;
        const datum    = `${dmatch[3]}-${dmatch[2]}-${dmatch[1]}`;
        const tijdstip = dmatch[4];
        const isFinal  = /final/i.test(datumRaw);

        games.push({
            datum,
            tijdstip,
            thuis:       TEAM_CODES[thuisCode] || thuisCode,
            thuis_code:  thuisCode,
            uit:         TEAM_CODES[uitCode]   || uitCode,
            uit_code:    uitCode,
            score_thuis: isFinal ? scoreThuis : null,
            score_uit:   isFinal ? scoreUit   : null,
            gamestatus:  isFinal ? "F" : "",
            gespeeld:    isFinal,
        });
    }

    return games;
}
"""


def format_dag(datum_str):
    dagen   = ["maandag","dinsdag","woensdag","donderdag","vrijdag","zaterdag","zondag"]
    maanden = ["","januari","februari","maart","april","mei","juni",
               "juli","augustus","september","oktober","november","december"]
    d = dt.datetime.strptime(datum_str, "%Y-%m-%d")
    return f"{dagen[d.weekday()]} {d.day} {maanden[d.month]}"


def main():
    print(f"Ophalen van {SCHEDULE_URL} via Playwright...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_context(
            user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36",
            locale="en-US",
            viewport={"width": 1280, "height": 800},
        ).new_page()

        # Vang console.log op voor debug
        page.on("console", lambda msg: print(f"  [browser] {msg.text}"))

        page.goto(SCHEDULE_URL, wait_until="networkidle", timeout=30000)

        # Wacht op enige wedstrijdinhoud
        try:
            page.wait_for_selector("text=Visitor", timeout=10000)
            print("  ✓ 'Visitor' gevonden in DOM")
        except Exception:
            print("  ⚠️  'Visitor' niet gevonden — pagina mogelijk leeg")

        # Stap 1: debug — wat ziet de browser?
        print("\n── Debug scan ──")
        debug = page.evaluate(EXTRACT_JS)
        print(f"  URL    : {debug['url']}")
        print(f"  Title  : {debug['title']}")
        print(f"  Nodes  : {debug['textNodeCount']}")
        print(f"  Scores : {debug['scoreNodes']}")
        print(f"  Tekst  :\n{debug['textSample'][:1500]}")

        # Stap 2: extraheer wedstrijden
        raw_games = page.evaluate(EXTRACT_GAMES_JS)
        print(f"\n── {len(raw_games)} wedstrijden gevonden ──")

        browser.close()

    uitslagen = [g for g in raw_games if g["gespeeld"]]
    programma = [g for g in raw_games if not g["gespeeld"]]

    # Voeg dag-label en id toe
    for i, g in enumerate(raw_games):
        g["id"]  = i + 1
        g["dag"] = format_dag(g["datum"])
        g["thuis_innings"] = []
        g["uit_innings"]   = []
        g["innings"]       = None
        g["locatie"]       = None
        g["stadion"]       = None

    uitslagen.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))
    programma.sort(key=lambda g: (g["datum"], g["tijdstip"] or ""))

    print(f"\nUitslagen ({len(uitslagen)}):")
    for u in uitslagen:
        print(f"  {u['datum']} {u['tijdstip']}  {u['uit_code']} {u['score_uit']} - {u['score_thuis']} {u['thuis_code']}")

    print(f"\nProgramma ({len(programma)}):")
    for p in programma:
        print(f"  {p['datum']} {p['tijdstip']}  {p['uit_code']} @ {p['thuis_code']}")

    output = {
        "bijgewerkt": dt.datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bron":       SCHEDULE_URL,
        "uitslagen":  uitslagen,
        "programma":  programma,
    }

    with open(JSON_FILE, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✅ {JSON_FILE} opgeslagen — {len(uitslagen)} uitslagen, {len(programma)} programma")


if __name__ == "__main__":
    main()
