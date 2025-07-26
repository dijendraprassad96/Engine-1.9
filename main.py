import os
import re
import sys
import requests
from bs4 import BeautifulSoup

# —— CONFIG —— #
CACHE_DIR = "/storage/emulated/0/2030/AI/14 Python/Engine 1.8/cache"
os.makedirs(CACHE_DIR, exist_ok=True)

WIKI_BASE = "https://en.wikipedia.org/wiki/"
API_URL   = "https://en.wikipedia.org/w/api.php"

# —— UTILITIES —— #

def fetch_page(title: str) -> str:
    """Fetch & cache a Wikipedia page HTML."""
    fn = title.replace(" ", "_") + ".html"
    path = os.path.join(CACHE_DIR, fn)
    if os.path.exists(path):
        return open(path, encoding="utf-8").read()
    url = WIKI_BASE + fn
    resp = requests.get(url, headers={"User-Agent":"MedBot/1.0"})
    resp.raise_for_status()
    html = resp.text
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return html

def clean_text(txt: str) -> str:
    """Strip citations and parenthetical notes."""
    txt = re.sub(r"\[.*?\]|\(.*?see.*?\)", "", txt, flags=re.IGNORECASE)
    return txt.strip(" .\n\t;")

def extract_symptoms_from_infobox(html: str) -> list[str]:
    """Return a list of symptoms from the page’s infobox (if present)."""
    soup = BeautifulSoup(html, "html.parser")
    box = soup.find("table", {"class":"infobox"})
    if not box:
        return []
    th = box.find(lambda t: t.name=="th" and "Symptoms" in t.text)
    if not th:
        return []
    td = th.find_next_sibling("td")
    if not td:
        return []
    items = []
    # 1) list items
    for li in td.find_all("li"):
        t = clean_text(li.get_text())
        if 3 <= len(t) <= 60:
            items.append(t.lower())
    # 2) fallback split
    if len(items) < 4:
        raw = td.get_text(separator=";")
        for part in re.split(r"[;,]", raw):
            t = clean_text(part)
            if (
                3 <= len(t) <= 60
                and not re.match(r"^(some cases|recurring|latent)", t, re.IGNORECASE)
            ):
                items.append(t.lower())
    # dedupe
    return list(dict.fromkeys(items))

def search_candidate_diseases(symptom: str, limit: int = 100) -> list[dict]:
    """
    1) Search up to `limit` pages whose **text** mentions the symptom.
    2) For each page, fetch & parse its infobox–symptoms (if any).
    3) Always include the page as a candidate, even if the infobox itself omits the symptom.
    """
    params = {
        "action": "query",
        "list":   "search",
        "srsearch": symptom,
        "format": "json",
        "srnamespace": 0,
        "srlimit": limit
    }
    resp = requests.get(API_URL, params=params, headers={"User-Agent":"MedBot/1.0"})
    resp.raise_for_status()
    results = resp.json().get("query", {}).get("search", [])
    titles = [r["title"] for r in results]

    pool = []
    for title in titles:
        try:
            html = fetch_page(title)
            syms = extract_symptoms_from_infobox(html)
            # always include—even if syms==[]
            pool.append({"name": title, "symptoms": syms})
        except Exception:
            continue
    return pool

# —— LIVE TRAIN + ASK LOOP —— #

def main():
    print("🩺 Live AI MedBot (train+ask — full dynamic pool)")
    print("Enter symptoms; you’ll get a numbered checklist to pick from.")
    print("Type 'done' when you want the final diagnosis.\n")

    selected = []
    remaining = []

    while True:
        # build the checklist of *new* symptoms
        next_syms = sorted({
            s for d in remaining for s in d["symptoms"]
            if s not in selected
        })

        # TERMINATION CONDITIONS
        # 1) Exactly one disease left & no more new symptoms → DONE
        if len(remaining) == 1 and not next_syms and selected:
            print(f"\n✅ Final Diagnosis: {remaining[0]['name']}")
            return

        # 2) >1 diseases but no distinguishing symptoms → LIST THEM
        if remaining and not next_syms and selected:
            print("\n❌ Unable to narrow further. Possible matches:")
            for d in remaining:
                print(f"  ➤ {d['name']}")
            return

        # show symptom checklist if we have at least one selected
        if selected and next_syms:
            print("📝 Symptom Checklist:")
            for i, s in enumerate(next_syms, 1):
                print(f"  {i}. {s}")
            print("-" * 40)

        # prompt
        prompt = "First symptom: " if not selected else "Enter new symptoms (text, numbers) or 'done': "
        user_in = input(prompt).strip().lower()
        if user_in == "done":
            break

        # handle comma/space-separated tokens
        tokens = user_in.replace(",", " ").split()
        for tok in tokens:
            # number → symptom
            if tok.isdigit() and selected and next_syms:
                idx = int(tok) - 1
                if 0 <= idx < len(next_syms):
                    sym = next_syms[idx]
                else:
                    print(f"⚠️ Invalid number: {tok}")
                    continue
            else:
                sym = tok

            # FIRST symptom: build the live pool
            if not selected:
                selected.append(sym)
                remaining = search_candidate_diseases(sym)
                if not remaining:
                    print(f"❌ No pages found mentioning: {sym}")
                    sys.exit(1)
                print(f"✔️ Added symptom: {sym} → {len(remaining)} candidates loaded")
                continue

            # SUBSEQUENT: filter down
            if sym in selected:
                print(f"⚠️ Already added: {sym}")
            else:
                selected.append(sym)
                # only keep diseases whose infobox DID list this symptom
                # (if infobox is empty, we conservatively keep it)
                new_rem = []
                for d in remaining:
                    if not d["symptoms"] or sym in d["symptoms"]:
                        new_rem.append(d)
                remaining = new_rem
                print(f"✔️ Added symptom: {sym} → {len(remaining)} candidates remain")
                if not remaining:
                    print(f"❌ No diseases match all: {', '.join(selected)}")
                    sys.exit(1)

        print()  # blank line

    # user typed 'done' manually
    if len(remaining) == 1:
        print(f"\n✅ Final Diagnosis: {remaining[0]['name']}")
    else:
        print("\n❌ Final shortlist:")
        for d in remaining:
            print(f"  ➤ {d['name']}")

if __name__ == "__main__":
    main()



