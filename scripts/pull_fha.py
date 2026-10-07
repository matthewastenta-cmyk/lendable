"""Pull HUD's FHA-approved condominium list for the counties Lendable covers.
Runs in GitHub Actions (HUD's site isn't reachable from Vercel builds reliably). Writes data/fha.json."""
import html, json, os, re, sys, time, urllib.parse, urllib.request
from datetime import date

COUNTIES = [("NY", "NEW YORK"), ("NY", "KINGS"), ("NY", "QUEENS"), ("NY", "BRONX"), ("NY", "RICHMOND"),
            ("FL", "MIAMI-DADE"), ("FL", "BROWARD"), ("FL", "PALM BEACH")]
URL = "https://entp.hud.gov/idapp/html/condo1.cfm"

def fetch(state, county, start):
    f = {"FAPPROVAL_METHOD": "NEW", "FSORTED_BY": "condo_name", "FSTATE": state, "FCOUNTY": county, "FCONDO_ID": "", "FCONDO_NAME": "",
         "FCITY": "", "FZIP": "", "FSTATUS_CODE": "X", "FSEARCH_TYPE": "P", "FBEGIN_MO": "", "FBEGIN_DY": "", "FBEGIN_YR": "",
         "FEND_MO": "", "FEND_DY": "", "FEND_YR": "", "CAME_FROM": "oth", "IN_FHAC": "true", "startAt": str(start), "maxRows": "500",
         "pageIn": "https://entp.hud.gov/idapp/html/condlook.cfm", "thisPage": "condo1.cfm"}
    req = urllib.request.Request(URL, data=urllib.parse.urlencode(f).encode(), headers={"User-Agent": "Mozilla/5.0", "Referer": "https://entp.hud.gov/idapp/html/condlook.cfm"})
    return urllib.request.urlopen(req, timeout=90).read().decode("latin-1")

def cells(tr):
    out = []
    for t in re.findall(r"<td[^>]*>(.*?)</td>", tr, flags=re.S | re.I):
        t = re.sub(r"<br\s*/?>", "|", t, flags=re.I)
        t = re.sub(r"<[^>]+>", "", t)
        out.append(re.sub(r"\s+", " ", html.unescape(t)).strip())
    return out

def mdy(s):
    m = re.search(r"(\d{2})/(\d{2})/(\d{4})", s or "")
    return f"{m.group(3)}-{m.group(1)}-{m.group(2)}" if m else ""

rows = {}
for state, county in COUNTIES:
    start, total = 1, None
    while True:
        try:
            page = fetch(state, county, start)
        except Exception as e:
            print(state, county, "failed:", e, file=sys.stderr); break
        if start == 1 and state == "FL" and county == "MIAMI-DADE":
            open("/tmp/fl_page.html", "w").write(page)
        if total is None:
            m = re.search(r"\((\d+) records were selected", page)
            total = int(m.group(1)) if m else 0
        got = 0
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, flags=re.S | re.I):
            c = cells(tr)
            if len(c) < 13 or not re.match(r"[A-Z]\d{4,}", c[1]):
                continue
            got += 1
            addr = c[2].split("|")
            street = addr[0].strip()
            m = re.search(r"^(.*),\s*([A-Z]{2})\s+(\d{5})", addr[-1].strip()) if len(addr) > 1 else None
            pid = c[1].split()[0]
            rec = {"id": pid, "name": re.sub(r"^\d+\s+(?=\D)", "", c[0]) if re.match(r"^\d+\s+[A-Z]", c[0]) and not re.match(r"^\d+(ST|ND|RD|TH)\b", c[0]) else c[0],
                   "street": street, "city": m.group(1).strip() if m else "", "state": state, "zip": m.group(3) if m else "",
                   "county": c[3], "composition": c[4][:160], "method": c[7], "status": c[9], "statusDate": mdy(c[11]), "expires": mdy(c[12])}
            # keep the most recent submission per project
            old = rows.get(pid)
            if not old or rec["statusDate"] > old["statusDate"]:
                rows[pid] = rec
        print(state, county, "start", start, "rows", got, "of", total, file=sys.stderr)
        start += 25
        if got == 0 or start > total:
            break
        time.sleep(1)

out = {"source": "HUD FHA Approved Condominiums (entp.hud.gov/idapp/html/condlook.cfm)", "pulled": date.today().isoformat(),
       "rows": sorted(rows.values(), key=lambda r: (r["state"], r["county"], r["name"]))}
os.makedirs("data", exist_ok=True)
if len(rows) < 50:
    sys.exit("too few rows; not overwriting")
json.dump(out, open("data/fha.json", "w"), separators=(",", ":"))
print(len(rows), "projects", file=sys.stderr)
