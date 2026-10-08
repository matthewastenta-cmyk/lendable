"""Check the Clerk developer account: is the AuthKey valid, what's the unit balance. Prints status only (never the key)."""
import json, os, urllib.parse, urllib.request
key = os.environ.get("CLERK_AUTH_KEY", "").strip()
print("key present:", bool(key), "length:", len(key))
base = "https://www2.miamidadeclerk.gov/Developers/api/"
def get(path, params):
    q = urllib.parse.urlencode({**params, "authKey": key})
    req = urllib.request.Request(base + path + "?" + q, headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"})
    try:
        body = urllib.request.urlopen(req, timeout=60).read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        body = "HTTP %s %s" % (e.code, e.read().decode("utf-8", "replace")[:300])
    return body.replace(key, "***") if key else body
# A folio lookup: with no prepaid units this should return a status message rather than charge anything.
r = get("OfficialRecords", {"parameter1": "0232340080010", "parameter2": "FN"})
try:
    j = json.loads(r); print({k: j.get(k) for k in ("Status", "StatusDesc", "UnitsBalance")})
except Exception:
    print(r[:400])
