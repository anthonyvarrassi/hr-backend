"""
HR Probability App — Backend API
Fetches from MLB Stats API + Baseball Savant.
Deploy to Railway or run locally.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests, time, os

app = Flask(__name__)
CORS(app)

MLB   = "https://statsapi.mlb.com/api/v1"
UA    = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}
CACHE = {}
TTL   = 1800  # 30 min

PARK = {
    "ARI":1.00,"ATL":1.04,"BAL":1.07,"BOS":1.06,"CHC":1.02,"CWS":0.98,
    "CIN":1.13,"CLE":0.99,"COL":1.18,"DET":0.98,"HOU":1.01,"KCR":0.99,
    "LAA":1.00,"LAD":1.00,"MIA":0.94,"MIL":1.05,"MIN":0.97,"NYM":1.00,
    "NYY":1.10,"OAK":0.97,"PHI":1.08,"PIT":0.96,"SDP":0.95,"SFG":0.96,
    "SEA":0.95,"STL":0.99,"TBR":0.99,"TEX":1.03,"TOR":0.99,"WSN":0.98,
}

TEAM_IDS = {
    109:"ARI",144:"ATL",110:"BAL",111:"BOS",112:"CHC",145:"CWS",
    113:"CIN",114:"CLE",115:"COL",116:"DET",117:"HOU",118:"KCR",
    108:"LAA",119:"LAD",146:"MIA",158:"MIL",142:"MIN",121:"NYM",
    147:"NYY",133:"OAK",143:"PHI",134:"PIT",135:"SDP",137:"SFG",
    136:"SEA",138:"STL",139:"TBR",140:"TEX",141:"TOR",120:"WSN",
}

LG = {
    "ISO":0.152,"FB":0.36,"HRFB":0.121,"Barrel":0.077,"HH":0.368,
    "SP_HR9":1.33,"SP_HRFB":0.121,"SP_GB":0.432,
}

SEASON = 2026


def cget(k):
    if k in CACHE:
        v, ts = CACHE[k]
        if time.time() - ts < TTL:
            return v
    return None

def cset(k, v):
    CACHE[k] = (v, time.time())

def mlb(path, params=None):
    for i in range(3):
        try:
            r = requests.get(MLB + path, params=params, headers=UA, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == 2: raise
            time.sleep(0.5)

def savant_batter(pid, season):
    try:
        import csv
        from io import StringIO
        url = (f"https://baseballsavant.mlb.com/leaderboard/expected_statistics"
               f"?type=batter&year={season}&position=&team=&min=10&csv=true")
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        for row in csv.DictReader(StringIO(r.text)):
            if str(row.get("player_id","")).strip() == str(pid):
                b = float(row.get("barrel_batted_rate", 0))
                h = float(row.get("hard_hit_percent", 0))
                if b > 0:
                    return round(b/100,4), round(h/100,4)
    except Exception:
        pass
    return None, None

def savant_pitcher(pid, season):
    try:
        import csv
        from io import StringIO
        url = (f"https://baseballsavant.mlb.com/leaderboard/expected_statistics"
               f"?type=pitcher&year={season}&position=&team=&min=5&csv=true")
        r = requests.get(url, headers=UA, timeout=12)
        r.raise_for_status()
        for row in csv.DictReader(StringIO(r.text)):
            if str(row.get("player_id","")).strip() == str(pid):
                b = float(row.get("barrel_batted_rate", 0))
                if b > 0:
                    return round(b/100,4)
    except Exception:
        pass
    return None


@app.route("/health")
def health():
    return jsonify({"status":"ok","season":SEASON})


@app.route("/search")
def search():
    name = request.args.get("name","").strip()
    if not name:
        return jsonify({"error":"name required"}), 400
    k = f"search:{name.lower()}"
    cached = cget(k)
    if cached: return jsonify({"results":cached})
    try:
        data = mlb("/people/search", {"names":name,"sportId":1})
        people = data.get("people",[])
        if not people:
            data = mlb("/people/search", {"names":name.split()[-1],"sportId":1})
            people = data.get("people",[])
        active = [p for p in people if p.get("active",False)] or people
        results = [{"id":p["id"],"name":p["fullName"],
                    "position":p.get("primaryPosition",{}).get("abbreviation","?"),
                    "team":p.get("currentTeam",{}).get("name","")} for p in active[:8]]
        cset(k, results)
        return jsonify({"results":results})
    except Exception as e:
        return jsonify({"error":str(e)}), 404


@app.route("/batter/<int:pid>")
def batter(pid):
    k = f"bat:{pid}:{SEASON}"
    cached = cget(k)
    if cached: return jsonify(cached)
    season = SEASON
    for yr in [season, season-1]:
        try:
            data = mlb(f"/people/{pid}/stats",
                       {"stats":"season","group":"hitting","season":yr,"gameType":"R"})
            splits = [s for sg in data.get("stats",[]) for s in sg.get("splits",[])]
            if splits:
                season = yr
                break
        except Exception:
            continue
    if not splits:
        return jsonify({"error":"No batting stats found"}), 404

    s    = splits[0]["stat"]
    pa   = int(s.get("plateAppearances",0))
    hr   = int(s.get("homeRuns",0))
    ab   = int(s.get("atBats",1))
    hits = int(s.get("hits",0))
    d    = int(s.get("doubles",0))
    t    = int(s.get("triples",0))
    bb_s = int(s.get("baseOnBalls",0))
    sb   = int(s.get("stolenBases",0))
    avg  = round(float(s.get("avg","0") or 0), 3)
    obp  = round(float(s.get("obp","0") or 0), 3)
    slg_v= round(float(s.get("slg","0") or 0), 3)
    ops  = round(float(s.get("ops","0") or 0), 3)
    k_s  = int(s.get("strikeOuts",0))

    calc_avg = hits/ab if ab>0 else 0.248
    calc_slg = (hits-d-t-hr+2*d+3*t+4*hr)/ab if ab>0 else 0.400
    iso  = max(0.0, round((slg_v or calc_slg) - (avg or calc_avg), 3))

    barrel_pct = round(min(0.25,max(0.02, iso*0.38)), 4)
    hh_pct     = round(min(0.60,max(0.25, 0.30+iso*0.55)), 4)
    fb_pct     = round(min(0.55,max(0.20, 0.33+(iso-0.152)*0.20)), 4)
    hrfb_pct   = round(min(0.40, hr/max(1,pa*fb_pct)), 4)

    sv_bar, sv_hh = savant_batter(pid, season)
    if sv_bar: barrel_pct, hh_pct = sv_bar, sv_hh

    result = {
        "PA":pa,"HR":hr,"AVG":avg or round(calc_avg,3),
        "OBP":obp,"SLG":slg_v or round(calc_slg,3),"OPS":ops,
        "ISO":iso,"BB":bb_s,"K":k_s,"SB":sb,
        "FB_pct":fb_pct,"HR_FB_pct":hrfb_pct,
        "Barrel_pct":barrel_pct,"HardHit_pct":hh_pct,
        "small_sample":pa<50,"season_used":season,
        "savant_data": sv_bar is not None,
    }
    cset(k, result)
    return jsonify(result)


@app.route("/pitcher/<int:pid>")
def pitcher(pid):
    k = f"pit:{pid}:{SEASON}"
    cached = cget(k)
    if cached: return jsonify(cached)
    splits = []
    season = SEASON
    for yr in [season, season-1]:
        try:
            data = mlb(f"/people/{pid}/stats",
                       {"stats":"season","group":"pitching","season":yr,"gameType":"R"})
            splits = [s for sg in data.get("stats",[]) for s in sg.get("splits",[])]
            if splits:
                season = yr
                break
        except Exception:
            continue
    if not splits:
        return jsonify({"error":"No pitching stats found"}), 404

    s     = splits[0]["stat"]
    ip    = float(s.get("inningsPitched",1))
    hr    = int(s.get("homeRuns",0))
    bb    = int(s.get("baseOnBalls",0))
    ks    = int(s.get("strikeOuts",0))
    er    = int(s.get("earnedRuns",0))
    era   = round(float(s.get("era","0") or 0), 2)
    whip  = round(float(s.get("whip","0") or 0), 2)
    go_ao = float(s.get("groundOutsToAirouts",1.0) or 1.0)

    gb_pct     = round(go_ao/(1+go_ao), 4)
    hrfb_pct   = round(min(0.35, hr/max(1,ip*(1-gb_pct)*3)), 4)
    fip        = max(1.5,min(7.5,round((13*hr+3*bb-2*ks)/ip+3.10,2) if ip>0 else 4.00))
    barrel_pct = round(min(0.20, hrfb_pct*0.65), 4)

    pinfo = mlb(f"/people/{pid}")
    hand  = pinfo.get("people",[{}])[0].get("pitchHand",{}).get("code","R")

    sv_bar = savant_pitcher(pid, season)
    if sv_bar: barrel_pct = sv_bar

    result = {
        "IP":ip,"HR":hr,"BB":bb,"K":ks,"ERA":era,"WHIP":whip,
        "HR_FB_pct":hrfb_pct,"GB_pct":gb_pct,"FIP":fip,
        "Hand":hand,"Barrel_pct":barrel_pct,
        "small_sample":ip<20,"season_used":season,
        "savant_data": sv_bar is not None,
    }
    cset(k, result)
    return jsonify(result)


@app.route("/bullpen/<team>")
def bullpen(team):
    team = team.upper()
    k = f"bp:{team}:{SEASON}"
    cached = cget(k)
    if cached: return jsonify(cached)

    team_id = next((tid for tid,abbr in TEAM_IDS.items() if abbr==team), None)
    result  = None
    if team_id:
        try:
            data = mlb(f"/teams/{team_id}/stats",
                       {"stats":"season","group":"pitching","season":SEASON,"gameType":"R"})
            splits = [s for sg in data.get("stats",[]) for s in sg.get("splits",[])]
            if splits:
                s     = splits[0]["stat"]
                ip    = float(s.get("inningsPitched",1))
                hr    = int(s.get("homeRuns",0))
                go_ao = float(s.get("groundOutsToAirouts",1.0) or 1.0)
                hr9   = round(hr/ip*9,2)
                gb    = round(go_ao/(1+go_ao),4)
                hrfb  = round(min(0.30,hr/max(1,ip*(1-gb)*3)),4)
                result = {"HR9":hr9,"HR_FB":hrfb,"GB_pct":gb,"live":True}
        except Exception:
            pass

    if not result:
        p = PARK.get(team,1.00)
        result = {
            "HR9":  round(LG["SP_HR9"]*p,2),
            "HR_FB":round(LG["SP_HRFB"]*p,4),
            "GB_pct":round(LG["SP_GB"]/p,4),
            "live": False,
        }
    cset(k, result)
    return jsonify(result)


@app.route("/park/<team>")
def park_factor(team):
    t = team.upper()
    return jsonify({"team":t,"park_factor":PARK.get(t,1.00)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n⚾  HR Backend running on port {port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
