import json, pathlib, urllib.request

BASE = pathlib.Path(__file__).parent
TITLE_KEYS = ["sdet", "qa automation", "quality engineer", "test automation",
              "software development engineer in test", "automation engineer",
              "qa engineer", "quality assurance"]
TITLE_BLOCK = ["intern", "manager", "director", "head of", "principal", "staff", "lead", "junior", "associate"]
LOC_KEYS = ["bengaluru", "bangalore", "india", "remote"]
MAX_NEW = 15

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)

def wanted(title, loc):
    t, l = title.lower(), (loc or "").lower()
    return (any(k in t for k in TITLE_KEYS)
            and not any(b in t for b in TITLE_BLOCK)
            and any(k in l for k in LOC_KEYS))

def greenhouse(slug):
    data = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs")
    for j in data.get("jobs", []):
        if wanted(j["title"], j.get("location", {}).get("name")):
            yield j["absolute_url"]

def lever(slug):
    for j in get(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        if wanted(j["text"], j.get("categories", {}).get("location")):
            yield j.get("applyUrl") or j["hostedUrl"]

def main():
    links = BASE / "links.txt"
    done = BASE / "done.txt"
    seen = set()
    for f in (links, done):
        if f.exists():
            seen |= {l.strip() for l in f.read_text().splitlines()}
    new = []
    for line in (BASE / "companies.txt").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        kind, slug = line.split(":", 1)
        try:
            for url in (greenhouse if kind == "greenhouse" else lever)(slug):
                if url not in seen:
                    new.append(url); seen.add(url)
        except Exception as e:
            print("skip", line, e)
    new = new[:MAX_NEW]
    if new:
        with open(links, "a") as f:
            f.write("\n".join(new) + "\n")
    print(f"discovered {len(new)} new links")

if __name__ == "__main__":
    main()
