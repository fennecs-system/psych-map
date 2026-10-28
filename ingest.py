#!/usr/bin/env python3
"""Ingest loop: watches ingest/inbox/*.json (written by search agents),
normalises, keyword-filters, dedupes, geocodes (Nominatim, cached) and
writes public/data.json, which the map polls."""
import json, re, time, hashlib, urllib.parse, urllib.request, pathlib, random, sys

ROOT = pathlib.Path(__file__).resolve().parent
INBOX = ROOT / "ingest" / "inbox"
REJECT = ROOT / "ingest" / "rejected"
CACHE = ROOT / "ingest" / "geocache.json"
OUT = ROOT / "docs" / "data.json"
MELB = (-37.8136, 144.9631)

KEYWORDS = {
    "trans": r"\btrans(gender|\b|-|\*)|gender[- ]diverse|non[- ]?binary|gender affirm",
    "lgbt": r"lgbt|queer|rainbow|gay|lesbian|bisexual",
    "dissociation": r"dissociat|\bdid\b|osdd",
    "trauma": r"trauma|ptsd",
    "schema": r"\bschema",
    "plural": r"\bplural|multiplicity|system members|\bsystems?\b.*(alter|headmate)",
    "kink": r"kink|bdsm|fetish|\bleather",
    "sex": r"\bsex",
    "emdr": r"\bemdr\b|\bedmr\b|eye movement desensiti",
}
KW_RE = {k: re.compile(v, re.I) for k, v in KEYWORDS.items()}
TRANS_ID_RE = re.compile(r"\b(trans|transgender|non-?binary|nonbinary|enby|genderqueer|gender[- ]?fluid|agender|two[- ]spirit(ed)?)\b", re.I)

geocache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
last_geo = 0.0


def geocode(q):
    global last_geo
    if not q:
        return None
    if q in geocache:
        return geocache[q]
    wait = 1.1 - (time.time() - last_geo)
    if wait > 0:
        time.sleep(wait)
    last_geo = time.time()
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode(
        {"q": q, "format": "json", "limit": 1, "countrycodes": "au"})
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "psych-map-local/1.0"})
        res = json.loads(urllib.request.urlopen(req, timeout=15).read())
        hit = [float(res[0]["lat"]), float(res[0]["lon"])] if res else None
    except Exception as e:
        print("geocode error", q, e, file=sys.stderr)
        return None
    geocache[q] = hit
    CACHE.write_text(json.dumps(geocache))
    return hit


def in_melbourne(ll):
    return ll and -38.6 < ll[0] < -37.3 and 144.3 < ll[1] < 145.9


def norm_name(n):
    n = re.sub(r"\b(dr|mr|ms|mx|mrs|prof)\.?\s+", "", n.lower())
    return re.sub(r"[^a-z]", "", n)


def clean_url(u):
    if not u:
        return ""
    u = u.strip()
    if u and not u.startswith("http"):
        u = "https://" + u
    return u


def locate(r):
    sub_ll = None
    if r.get("suburb"):
        sub_ll = geocode(f"{r['suburb']} {r.get('postcode') or ''} VIC Australia".replace("  ", " "))
        if not in_melbourne(sub_ll):
            sub_ll = None
    if r.get("address"):
        addr = r["address"]
        if r.get("suburb") and r["suburb"].lower() not in addr.lower():
            addr = f"{addr}, {r['suburb']}"
        ll = geocode(f"{addr}, VIC, Australia")
        # trust the street hit only if it lands near the stated suburb (~3km)
        if in_melbourne(ll) and (not sub_ll or abs(ll[0] - sub_ll[0]) + abs(ll[1] - sub_ll[1]) < 0.04):
            return ll, "address"
    if sub_ll:
        return sub_ll, "suburb"
    try:
        ll = [float(r["lat"]), float(r["lng"])]
        if in_melbourne(ll):
            return ll, "agent"
    except Exception:
        pass
    if r.get("telehealth_only") or not (r.get("address") or r.get("suburb")):
        return list(MELB), "approx"
    return None, None


NICK = {"liz": "elizabeth", "beth": "elizabeth", "lizzie": "elizabeth", "kate": "katherine", "katie": "katherine",
        "catherine": "katherine", "kathryn": "katherine", "jen": "jennifer", "jenny": "jennifer", "alex": "alexandra",
        "alexander": "alexandra", "sam": "samantha", "samuel": "samantha", "chris": "christopher", "christine": "christopher",
        "nick": "nicholas", "matt": "matthew", "mike": "michael", "rob": "robert", "bob": "robert", "dan": "daniel",
        "dave": "david", "tom": "thomas", "ben": "benjamin", "jo": "joanne", "steph": "stephanie", "nic": "nicola",
        "nicki": "nicola", "nikki": "nicola", "andy": "andrew", "tony": "anthony", "pip": "philippa", "mel": "melissa",
        "bec": "rebecca", "becky": "rebecca", "bek": "rebecca", "jess": "jessica", "jodie": "jodie", "will": "william"}
CREDS = r"\b(dr|mr|ms|mx|mrs|miss|prof|professor|assoc|a/prof|phd|maps|faps|mpsych|dpsych|bsc|ba|ma|msc|clin|psych)\b\.?"
GENERIC_EMAIL = re.compile(r"^(info|admin|reception|hello|contact|enquiries|enquiry|office|bookings?|referrals?|team|mail|intake|clinic)@", re.I)
SELF_ID_RE = re.compile(
    r"\b(i am|i'm|as an?|identif(?:y|ies) as|is an?|being an?|myself as|themselves as|they are an?)\s+(?:[\w,]+\s+){0,3}?"
    r"(trans(?:gender)?|non-?binary|nonbinary|enby|genderqueer|gender ?fluid|agender|two[- ]spirit(?:ed)?)"
    r"(?![- ]?(affirm|inclusive|friendly|aware|clients?|communit|youth|young|people|folks?|individuals?|and |, |or |issues|health|experience|identit|populations?))", re.I)
PRON_TOKENS = {"she", "her", "hers", "he", "him", "his", "they", "them", "theirs", "their"}


def pron_tags(pron):
    pl = pron.lower()
    tags = []
    if re.search(r"\bshe\b|\bher\b", pl): tags.append("she/her")
    if re.search(r"\bhe\b|\bhim\b", pl): tags.append("he/him")
    if re.search(r"\bthey\b|\bthem\b", pl): tags.append("they/them")
    toks = set(re.findall(r"[a-z]+", pl)) - {"pronouns", "and", "or", "use"}
    if toks - PRON_TOKENS: tags.append("other")
    return tags


def name_tokens(n):
    n = re.sub(r"\(.*?\)", " ", n)
    n = re.split(r",|\s[-–—|]\s", n)[0]
    n = re.sub(CREDS, " ", n.lower())
    toks = [NICK.get(t, t) for t in re.findall(r"[a-z][a-z'’-]*", n)]
    return [t.replace("'", "").replace("’", "") for t in toks]


def merge(a, b):
    for k, v in b.items():
        if k in ("sources", "identity_all"):
            continue
        if v and not a.get(k):
            a[k] = v
        elif k == "description" and v and len(v) > len(a.get(k, "")):
            a[k] = v
        elif k == "name" and len(v) > len(a[k]) and "(" not in v:
            a[k] = v
    a["sources"] = sorted(set(a.get("sources", [])) | set(b.get("sources", [])))
    a["identity_all"] = a.get("identity_all", "") + " " + b.get("identity_all", "")
    a["added"] = min(a["added"], b["added"])
    return a


def build():
    recs = []
    for f in sorted(INBOX.glob("*.json"), key=lambda p: p.stat().st_mtime):
        try:
            raw = json.loads(f.read_text())
        except Exception:
            continue
        for r in raw if isinstance(raw, list) else [raw]:
            if not isinstance(r, dict) or not r.get("name"):
                continue
            text = " ".join(str(r.get(k, "")) for k in ("description", "specialties", "practice", "keywords"))
            kws = [k for k, rx in KW_RE.items() if rx.search(text)]
            if not kws:
                continue
            recs.append({
                "name": re.sub(r"\s+", " ", str(r["name"])).strip(),
                "pronouns": str(r.get("pronouns") or "").strip(),
                "title": r.get("title") or "",
                "practice": r.get("practice") or "",
                "address": r.get("address") or "",
                "suburb": r.get("suburb") or "",
                "postcode": str(r.get("postcode") or ""),
                "phone": r.get("phone") or "",
                "email": (r.get("email") or "").strip().lower(),
                "website": clean_url(r.get("website")),
                "booking_url": clean_url(r.get("booking_url")),
                "description": str(r.get("description") or "")[:1500],
                "specialties": str(r.get("specialties") or ""),
                "telehealth": bool(r.get("telehealth") or r.get("telehealth_only")),
                "telehealth_only": bool(r.get("telehealth_only")),
                "lat": r.get("lat"), "lng": r.get("lng"),
                "keywords": kws,
                "identity_all": str(r.get("identity") or ""),
                "sources": [s for s in [r.get("source_url")] if s],
                "agent": f.name.split("-")[0],
                "added": int(f.stat().st_mtime),
            })
    # union-find dedup: same first+last name, same personal email, or same initial+surname at same suburb/practice
    parent = list(range(len(recs)))
    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    def union(i, j):
        parent[find(i)] = find(j)
    seen = {}
    for i, r in enumerate(recs):
        t = name_tokens(r["name"])
        if not t:
            continue
        keys = [("n", t[0], t[-1])]
        if len(t) > 1:
            for loc in (r["suburb"].lower(), r["practice"].lower()[:20]):
                if loc:
                    keys.append(("i", t[0][0], t[-1], loc))
        # only merge on email when it looks personal (local part contains one of their name tokens)
        local = r["email"].split("@")[0]
        if r["email"] and not GENERIC_EMAIL.match(r["email"]) and any(len(x) >= 3 and x in local for x in t + name_tokens(r["name"].replace("(", " ").replace(")", " "))):
            keys.append(("e", r["email"]))
        for k in keys:
            if k in seen:
                union(i, seen[k])
            else:
                seen[k] = i
    people = {}
    for i, r in enumerate(recs):
        root = find(i)
        people[root] = merge(people[root], r) if root in people else r
    for p in people.values():
        p["trans_nb"] = bool(TRANS_ID_RE.search(p["identity_all"]) or SELF_ID_RE.search(p["description"]))
        p["identity"] = re.sub(r"\s+", " ", p.pop("identity_all")).strip()
        p["pron_tags"] = pron_tags(p["pronouns"])
        p["keywords"] = sorted(set(p["keywords"]) | {k for k, rx in KW_RE.items() if rx.search(p["description"] + " " + p["specialties"])})
        p["_key"] = "".join(name_tokens(p["name"])) or norm_name(p["name"])
    out = []
    for p in people.values():
        key = p.pop("_key")
        ll, prec = locate(p)
        if not ll:
            REJECT.mkdir(exist_ok=True)
            continue
        # jitter so co-located practitioners don't stack exactly
        h = int(hashlib.md5(key.encode()).hexdigest(), 16)
        j = 0.0006 if prec == "address" else 0.004 if prec == "suburb" else 0.02
        p["lat"] = ll[0] + ((h % 1000) / 1000 - 0.5) * j
        p["lng"] = ll[1] + (((h // 1000) % 1000) / 1000 - 0.5) * j
        p["precision"] = prec
        p["id"] = key
        out.append(p)
    out.sort(key=lambda p: p["added"])
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps({"updated": int(time.time()), "count": len(out),
                               "inbox_files": len(list(INBOX.glob('*.json'))), "people": out}))
    tmp.replace(OUT)
    return len(out)


if __name__ == "__main__":
    last_sig = None
    while True:
        sig = tuple((f.name, f.stat().st_mtime) for f in INBOX.glob("*.json"))
        if sig != last_sig:
            n = build()
            print(time.strftime("%H:%M:%S"), f"{len(sig)} files -> {n} practitioners", flush=True)
            last_sig = sig
        if "--once" in sys.argv:
            break
        time.sleep(2)
