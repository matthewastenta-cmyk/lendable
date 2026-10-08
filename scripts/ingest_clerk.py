"""Daily: pull new files from the Clerk's Official Records bulk folder (through the Fixie static-IP proxy),
keep mortgages on condo units, and accumulate them in data/miami_mortgages.json.
Needs secrets CLERK_AUTH_KEY, CLERK_PROXY_URL and the folder name in CLERK_FOLDER (repo variable or secret).
Borrower names are never stored; only lender, date, amount, folio and book/page."""
import csv, io, json, os, re, sys, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET

KEY = os.environ["CLERK_AUTH_KEY"].strip()
PROXY = os.environ["CLERK_PROXY_URL"].strip()
FOLDER = os.environ.get("CLERK_FOLDER", "").strip()
API = "https://www2.miamidadeclerk.gov/Developers/api/FTPapi"
opener = urllib.request.build_opener(urllib.request.ProxyHandler({"http": PROXY, "https": PROXY}))
def get(params, accept="application/xml"):
    q = urllib.parse.urlencode({**params, "AuthKey": KEY})
    try:
        return opener.open(urllib.request.Request(API + "?" + q, headers={"Accept": accept, "User-Agent": "Mozilla/5.0"}), timeout=300).read()
    except urllib.error.HTTPError as e:
        return ("HTTP %s " % e.code).encode() + e.read()

if not FOLDER:
    # Folder name not configured: try the likely names and report what the Clerk says.
    for cand in ["Records", "RECORDS", "OfficialRecords", "Official Records", "OR", "Recording"]:
        r = get({"folderListName": cand}).decode("utf-8", "replace").replace(KEY, "***")
        print("try", repr(cand), "->", re.sub(r"\s+", " ", r)[:300])
        if re.search(r"\.(zip|txt|csv|dat|xml)", r, re.I):
            FOLDER = cand; print("USING", cand); break
    if not FOLDER:
        sys.exit(0)

state_path = "data/miami_mortgages.json"
state = json.load(open(state_path)) if os.path.exists(state_path) else {"files": [], "mortgages": []}

listing = get({"folderListName": FOLDER}).decode("utf-8", "replace")
print("listing head:", re.sub(r"\s+", " ", listing.replace(KEY, "***"))[:500])
names = re.findall(r"[\w.\-]+\.(?:zip|txt|csv|dat|xml)", listing, re.I)
names = sorted(set(names))
print("files in folder:", len(names), names[:5])
new = [n for n in names if n not in state["files"]]
print("new files:", len(new))

MORT = re.compile(r"^(MOR|MTG|MORT|MORTGAGE)$", re.I)
def rows_from(blob, name):
    if blob[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(blob))
        for inner in z.namelist():
            yield from rows_from(z.read(inner), inner)
        return
    text = blob.decode("latin-1")
    if text.lstrip().startswith("<"):
        root = ET.fromstring(text)
        for el in root.iter():
            kids = list(el)
            if kids and all(len(k) == 0 for k in kids):
                yield {k.tag.split("}")[-1].upper(): (k.text or "").strip() for k in kids}
        return
    first = text.splitlines()[0] if text else ""
    delim = "|" if first.count("|") > first.count(",") else ("\t" if "\t" in first else ",")
    for r in csv.DictReader(io.StringIO(text), delimiter=delim):
        yield {(k or "").strip().upper(): (v or "").strip() for k, v in r.items()}

added = 0
for n in new:
    blob = get({"fileName": n, "folderName": FOLDER}, accept="application/octet-stream")
    cols = None; kept = 0
    for r in rows_from(blob, n):
        cols = cols or list(r.keys())
        if not MORT.match(r.get("DOC_TYPE", "")):
            continue
        folio = re.sub(r"\D", "", r.get("FOLIO_NUMBER", "") or r.get("FOLIO", ""))
        if not folio:
            continue
        lender = r.get("SECOND_PARTY", "") if r.get("PARTY_CODE", "") in ("", "D", "R") else r.get("FIRST_PARTY", "")
        state["mortgages"].append({"folio": folio.zfill(13), "lender": lender, "date": (r.get("REC_DATE", "") or "")[:10],
                                   "amt": r.get("CONSIDERATION_1", "") or r.get("CONSIDERATION", ""), "book": r.get("REC_BOOK", ""), "page": r.get("REC_PAGE", ""),
                                   "condo": r.get("SUBDIV_NAME", "")})
        kept += 1
    print(n, "columns:", (cols or [])[:25], "mortgages kept:", kept)
    state["files"].append(n); added += kept

# de-duplicate (one mortgage can have several party rows)
seen, out = set(), []
for m in state["mortgages"]:
    k = (m["folio"], m["book"], m["page"], m["lender"])
    if k not in seen:
        seen.add(k); out.append(m)
state["mortgages"] = out
os.makedirs("data", exist_ok=True)
json.dump(state, open(state_path, "w"), separators=(",", ":"))
print("added", added, "total mortgages", len(out))
