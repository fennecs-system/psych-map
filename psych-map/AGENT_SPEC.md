# psych-map search agent spec

You feed a live map of psychologists / psychotherapists / counsellors / sexologists in greater Melbourne, VIC.

## Match criteria
Include a practitioner if their public description mentions ANY of: trans / transgender / gender diverse / non-binary,
LGBT / LGBTQIA+ / queer, dissociation / DID / OSDD, trauma / PTSD, schema therapy, plural / plurality / multiplicity / parts,
kink / BDSM, sex / sexuality / sex therapy, EMDR. Melbourne metro only (incl. telehealth-only practitioners based in Melbourne).

## Fetching — use a normal browser user agent
WebFetch gets blocked (403) by many directories. When that happens, fetch with curl and a real browser UA:

    curl -sL --compressed -m 25 \
      -A "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36" \
      -H "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8" \
      -H "Accept-Language: en-AU,en;q=0.9" \
      "<url>" > /private/tmp/claude-502/psych-fetch/<something>.html

Save pages under /private/tmp/claude-502/psych-fetch/ (mkdir -p it) and extract with grep/sed/python3 -I, rather than
dumping whole pages into your context. Be polite: ≥1s between requests to the same host, no parallel hammering.
If a site still blocks, move on — don't try to evade CAPTCHAs or logins. Don't run any downloaded code.

## Output — write AS YOU GO (every 3–8 people), the user watches pins appear live
Use the Write tool to create a NEW file each time: /Users/fennecs/psych-map/ingest/inbox/<agent-id>-<n>.json (n=1,2,3…).
Content: JSON array of objects. Use "" when unknown — NEVER invent:

    {"name": "", "pronouns": "only if published, exactly as written", "title": "", "practice": "",
     "address": "street address", "suburb": "", "postcode": "", "phone": "", "email": "", "website": "",
     "booking_url": "direct booking link (Halaxy/HotDoc/Cliniko/practice page)",
     "description": "their own words, 1-5 sentences, include the matching keywords as written",
     "specialties": "comma list", "telehealth": true/false, "telehealth_only": true/false,
     "identity": "ONLY the practitioner's own self-description of their identity, quoted (e.g. 'queer non-binary'); else empty",
     "source_url": ""}

Identity rule: do NOT infer identity from pronouns or from who they work with. Only quote what they say about themselves.

Re-adding someone already on the map is fine and useful when you have richer details (address, email, booking link,
pronouns, full bio) — the ingest merges by name. Check what's already there with:
    python3 -c "import json;print('\n'.join(p['name']+' | '+p['suburb'] for p in json.load(open('/Users/fennecs/psych-map/public/data.json'))['people']))" | grep -i <name>

Final reply: one short paragraph: count written, sources that worked, sources that stayed blocked.
