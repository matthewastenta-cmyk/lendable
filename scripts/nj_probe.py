import json, re, urllib.request, urllib.parse
UA={'User-Agent':'Mozilla/5.0 pocketapproval'}
def get(u, data=None):
    return urllib.request.urlopen(urllib.request.Request(u, data=data, headers=UA), timeout=120).read()
FS='https://services2.arcgis.com/XVOqAjTOJ5P6ngMu/ArcGIS/rest/services/Parcels_MODIV_NJ_WM/FeatureServer/0/query?'
def q(**p):
    p.setdefault('f','json'); return json.loads(get(FS+urllib.parse.urlencode(p)))
for mun in ['HOBOKEN CITY','JERSEY CITY']:
    for w in ["MUN_NAME='%s'","MUN_NAME='%s' AND PCLQCODE LIKE 'C%%'","MUN_NAME='%s' AND PROP_CLASS='2'"]:
        try: print(mun, w, q(where=w%mun, returnCountOnly='true'))
        except Exception as e: print('ERR', e)
    try:
        r=q(where="MUN_NAME='%s' AND PCLQCODE LIKE 'C%%'"%mun, outFields='PCLBLOCK,PCLLOT,PCLQCODE,PROP_CLASS,PROP_LOC,BLDG_DESC,BLDG_CLASS,YR_CONSTR,SALE_PRICE,DEED_DATE,DWELL,ZIP5', resultRecordCount=5)
        for f in r.get('features',[]): print(f['attributes'])
    except Exception as e: print('ERR', e)
    try:
        r=q(where="MUN_NAME='%s'"%mun, outFields='PROP_CLASS,count(*)', groupByFieldsForStatistics='PROP_CLASS', outStatistics=json.dumps([{"statisticType":"count","onStatisticField":"OBJECTID","outStatisticFieldName":"n"}]))
        print('classes', [ (f['attributes']['PROP_CLASS'], f['attributes']['n']) for f in r.get('features',[])])
    except Exception as e: print('ERR', e)
# big rentals/condo master lots
try:
    r=q(where="MUN_NAME='HOBOKEN CITY' AND DWELL>20", outFields='PCLBLOCK,PCLLOT,PCLQCODE,PROP_CLASS,PROP_LOC,BLDG_DESC,YR_CONSTR,DWELL', resultRecordCount=8)
    for f in r.get('features',[]): print('big', f['attributes'])
except Exception as e: print('ERR', e)
# SR1A downloads
for u in ['https://www.nj.gov/treasury/taxation/lpt/statdata.shtml','https://www.state.nj.us/treasury/taxation/lpt/statdata.shtml','https://www.nj.gov/treasury/taxation/lpt/salesdata.shtml']:
    try:
        h=get(u).decode('latin-1'); links=sorted(set(re.findall(r'href="([^"]*(?:SR1A|sr1a|Sales|sales)[^"]*)"',h)))
        print(u, len(h), links[:40])
    except Exception as e: print(u,'ERR',e)
