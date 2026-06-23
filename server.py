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
    games = int(s.get("gamesPitched",0))

    gb_pct     = round(go_ao/(1+go_ao), 4)
    hrfb_pct   = round(min(0.35, hr/max(1,ip*(1-gb_pct)*3)), 4)
    fip        = max(1.5,min(7.5,round((13*hr+3*bb-2*ks)/ip+3.10,2) if ip>0 else 4.00))
    barrel_pct = round(min(0.20, hrfb_pct*0.65), 4)

    pinfo = mlb(f"/people/{pid}")
    hand  = pinfo.get("people",[{}])[0].get("pitchHand",{}).get("code","R")

    sv_bar = savant_pitcher(pid, season)
    if sv_bar: barrel_pct = sv_bar

    result = {
        "G":games,"IP":ip,"HR":hr,"BB":bb,"K":ks,"ERA":era,"WHIP":whip,
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


# ═══════════════════════════════════════════════════════════════
# NHL ROUTES
# ═══════════════════════════════════════════════════════════════

NHL      = "https://api-web.nhle.com/v1"
NHL_STATS= "https://api.nhle.com/stats/rest/en"

NHL_SEASON_2026 = 20252026   # 2025-26 NHL season code
NHL_SEASON_2027 = 20262027   # 2026-27 NHL season code

NHL_TEAMS = {
    "ANA":"Anaheim Ducks","ARI":"Utah Hockey Club","BOS":"Boston Bruins",
    "BUF":"Buffalo Sabres","CGY":"Calgary Flames","CAR":"Carolina Hurricanes",
    "CHI":"Chicago Blackhawks","COL":"Colorado Avalanche","CBJ":"Columbus Blue Jackets",
    "DAL":"Dallas Stars","DET":"Detroit Red Wings","EDM":"Edmonton Oilers",
    "FLA":"Florida Panthers","LAK":"Los Angeles Kings","MIN":"Minnesota Wild",
    "MTL":"Montreal Canadiens","NSH":"Nashville Predators","NJD":"New Jersey Devils",
    "NYI":"New York Islanders","NYR":"New York Rangers","OTT":"Ottawa Senators",
    "PHI":"Philadelphia Flyers","PIT":"Pittsburgh Penguins","SEA":"Seattle Kraken",
    "SJS":"San Jose Sharks","STL":"St. Louis Blues","TBL":"Tampa Bay Lightning",
    "TOR":"Toronto Maple Leafs","VAN":"Vancouver Canucks","VGK":"Vegas Golden Knights",
    "WSH":"Washington Capitals","WPG":"Winnipeg Jets",
}


def nhl_get(url, params=None):
    for i in range(3):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == 2: raise
            time.sleep(0.5)


def get_nhl_season():
    """Return current/most recent NHL season code."""
    try:
        data = nhl_get(f"{NHL}/standings/now")
        # If standings exist for 2026-27 use that, otherwise 2025-26
        return NHL_SEASON_2027
    except Exception:
        return NHL_SEASON_2026


def search_nhl_player(name):
    """Search NHL API for a player."""
    ck = f"nhl_search:{name.lower()}"
    cached = cget(ck)
    if cached: return cached
    try:
        data = nhl_get(f"https://search.d3.nhle.com/api/v1/search",
                       {"q": name, "type": "player", "limit": 8, "culture": "en-us"})
        players = data if isinstance(data, list) else data.get("players", [])
        results = []
        for p in players[:8]:
            pid = p.get("playerId") or p.get("id")
            if not pid: continue
            results.append({
                "id":       pid,
                "name":     p.get("name","") or f"{p.get('firstName','')} {p.get('lastName','')}".strip(),
                "position": p.get("positionCode",""),
                "team":     p.get("teamAbbrev","") or p.get("lastTeamAbbrev",""),
            })
        cset(ck, results)
        return results
    except Exception as e:
        raise ValueError(f"NHL player search failed: {e}")


def get_skater_stats(pid, season=None):
    """Pull skater stats from NHL API."""
    if season is None:
        season = get_nhl_season()
    ck = f"nhl_skater:{pid}:{season}"
    cached = cget(ck)
    if cached: return cached

    try:
        data = nhl_get(f"{NHL}/player/{pid}/landing")
        seasons = data.get("seasonTotals", [])
        # Find matching season
        reg = [s for s in seasons if s.get("season") == season and s.get("gameTypeId") == 2]
        if not reg and season == NHL_SEASON_2027:
            # Fall back to 2025-26
            reg = [s for s in seasons if s.get("season") == NHL_SEASON_2026 and s.get("gameTypeId") == 2]
            if reg: season = NHL_SEASON_2026
        if not reg:
            # Try most recent season
            reg_all = [s for s in seasons if s.get("gameTypeId") == 2]
            if reg_all:
                reg = [sorted(reg_all, key=lambda x: x.get("season",0), reverse=True)[0]]
                season = reg[0].get("season", season)

        if not reg:
            raise ValueError(f"No NHL stats found for player {pid}")

        s = reg[0]
        gp     = int(s.get("gamesPlayed", 0))
        goals  = int(s.get("goals", 0))
        assists= int(s.get("assists", 0))
        shots  = int(s.get("shots", 0))
        ppg    = int(s.get("powerPlayGoals", 0))
        ppp    = int(s.get("powerPlayPoints", 0))
        toi    = s.get("avgTimeOnIcePerGame", "0:00")
        plus_m = int(s.get("plusMinus", 0))

        gpg    = round(goals/gp, 4)         if gp > 0 else 0
        spg    = round(shots/gp, 2)         if gp > 0 else 0
        sh_pct = round(goals/shots*100, 1)  if shots > 0 else 0
        ppgpg  = round(ppg/gp, 3)           if gp > 0 else 0
        pts    = goals + assists

        result = {
            "GP": gp, "G": goals, "A": assists, "PTS": pts,
            "S": shots, "S_pct": sh_pct, "PPG": ppg, "PPP": ppp,
            "GPG": gpg, "SPG": spg, "PPGPG": ppgpg,
            "TOI": toi, "plusMinus": plus_m,
            "small_sample": gp < 10,
            "season_used": season,
        }
        cset(ck, result)
        return result
    except Exception as e:
        raise ValueError(str(e))


def get_goalie_stats(pid, season=None):
    """Pull goalie stats from NHL API."""
    if season is None:
        season = get_nhl_season()
    ck = f"nhl_goalie:{pid}:{season}"
    cached = cget(ck)
    if cached: return cached

    try:
        data = nhl_get(f"{NHL}/player/{pid}/landing")
        seasons = data.get("seasonTotals", [])
        reg = [s for s in seasons if s.get("season") == season and s.get("gameTypeId") == 2]
        if not reg and season == NHL_SEASON_2027:
            reg = [s for s in seasons if s.get("season") == NHL_SEASON_2026 and s.get("gameTypeId") == 2]
        if not reg:
            reg_all = [s for s in seasons if s.get("gameTypeId") == 2]
            if reg_all:
                reg = [sorted(reg_all, key=lambda x: x.get("season",0), reverse=True)[0]]

        if not reg:
            raise ValueError("No goalie stats found")

        s = reg[0]
        gp    = int(s.get("gamesPlayed", 0))
        gaa   = round(float(s.get("goalsAgainstAverage", 0) or 0), 2)
        sv_pct= round(float(s.get("savePct", 0) or 0), 3)
        wins  = int(s.get("wins", 0))
        sa    = int(s.get("shotsAgainst", 0))
        ga    = int(s.get("goalsAgainst", 0))
        so    = int(s.get("shutouts", 0))
        sapg  = round(sa/gp, 1) if gp > 0 else 0

        result = {
            "GP": gp, "W": wins, "GAA": gaa, "SV_PCT": sv_pct,
            "SA": sa, "GA": ga, "SO": so, "SAPG": sapg,
            "small_sample": gp < 5,
        }
        cset(ck, result)
        return result
    except Exception as e:
        raise ValueError(str(e))


def get_team_defense(team_abbr, season=None):
    """Pull team defense stats (goals against, shots against)."""
    if season is None:
        season = get_nhl_season()
    ck = f"nhl_team_def:{team_abbr}:{season}"
    cached = cget(ck)
    if cached: return cached

    try:
        data = nhl_get(f"{NHL}/standings/now")
        standings = data.get("standings", [])
        team = next((t for t in standings if t.get("teamAbbrev",{}).get("default","") == team_abbr), None)
        if not team:
            raise ValueError("Team not found")
        gp   = int(team.get("gamesPlayed", 1))
        ga   = int(team.get("goalAgainst", 0))
        gf   = int(team.get("goalFor", 0))
        gapg = round(ga/gp, 2) if gp > 0 else 3.0
        result = {
            "GP": gp, "GA": ga, "GF": gf,
            "GAPG": gapg, "live": True,
        }
        cset(ck, result)
        return result
    except Exception:
        return {"GAPG": 3.0, "live": False}


@app.route("/nhl/search")
def nhl_search():
    name = request.args.get("name","").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        results = search_nhl_player(name)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nhl/skater/<int:pid>")
def nhl_skater(pid):
    try:
        data = get_skater_stats(pid)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nhl/goalie/<int:pid>")
def nhl_goalie(pid):
    try:
        data = get_goalie_stats(pid)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nhl/team/<team>")
def nhl_team(team):
    try:
        data = get_team_defense(team.upper())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nhl/teams")
def nhl_teams():
    return jsonify(NHL_TEAMS)


# ═══════════════════════════════════════════════════════════════
# NFL ROUTES
# ═══════════════════════════════════════════════════════════════

NFL_BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl"
NFL_CDN  = "https://site.web.api.espn.com/apis/common/v3/sports/football/nfl"

NFL_SEASON_2025 = 2025
NFL_SEASON_2026 = 2026

NFL_TEAMS_MAP = {
    "ARI":"Arizona Cardinals","ATL":"Atlanta Falcons","BAL":"Baltimore Ravens",
    "BUF":"Buffalo Bills","CAR":"Carolina Panthers","CHI":"Chicago Bears",
    "CIN":"Cincinnati Bengals","CLE":"Cleveland Browns","DAL":"Dallas Cowboys",
    "DEN":"Denver Broncos","DET":"Detroit Lions","GB":"Green Bay Packers",
    "HOU":"Houston Texans","IND":"Indianapolis Colts","JAX":"Jacksonville Jaguars",
    "KC":"Kansas City Chiefs","LAC":"Los Angeles Chargers","LAR":"Los Angeles Rams",
    "LV":"Las Vegas Raiders","MIA":"Miami Dolphins","MIN":"Minnesota Vikings",
    "NE":"New England Patriots","NO":"New Orleans Saints","NYG":"New York Giants",
    "NYJ":"New York Jets","PHI":"Philadelphia Eagles","PIT":"Pittsburgh Steelers",
    "SEA":"Seattle Seahawks","SF":"San Francisco 49ers","TB":"Tampa Bay Buccaneers",
    "TEN":"Tennessee Titans","WSH":"Washington Commanders",
}

# League average baselines (2024 season)
NFL_LG = {
    "RB_TDPG": 0.45,   # TDs per game for feature RB
    "WR_TDPG": 0.22,   # TDs per game for WR1
    "TE_TDPG": 0.18,   # TDs per game for TE1
    "DEF_TDPG": 2.40,  # TDs allowed per game by average defense
    "DEF_RZTD": 0.52,  # Red zone TD% allowed
}


def nfl_get(url, params=None):
    for i in range(3):
        try:
            r = requests.get(url, params=params, headers=UA, timeout=12)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            if i == 2: raise
            time.sleep(0.5)


def search_nfl_player(name):
    ck = f"nfl_search:{name.lower()}"
    cached = cget(ck)
    if cached: return cached
    try:
        data = nfl_get(f"{NFL_BASE}/athletes",
                       {"search": name, "limit": 10, "active": True})
        athletes = data.get("items", []) or data.get("athletes", [])
        results = []
        for a in athletes[:8]:
            pos = a.get("position", {}).get("abbreviation", "")
            if pos not in ("RB","WR","TE","FB"): continue
            results.append({
                "id":       a.get("id",""),
                "name":     a.get("fullName","") or a.get("displayName",""),
                "position": pos,
                "team":     a.get("team",{}).get("abbreviation","") if isinstance(a.get("team"),dict) else "",
            })
        if not results:
            # fallback: try suggestions endpoint
            data2 = nfl_get("https://site.api.espn.com/apis/search/v2",
                            {"query": name, "sport": "football", "league": "nfl", "limit": 8})
            hits = data2.get("results", [])
            for h in hits:
                if h.get("type") != "athlete": continue
                d = h.get("displayName","")
                pid = h.get("id","")
                pos = h.get("subtitle","").split("·")[0].strip() if "·" in h.get("subtitle","") else ""
                results.append({"id": pid, "name": d, "position": pos, "team": ""})
        cset(ck, results)
        return results
    except Exception as e:
        raise ValueError(f"NFL player search failed: {e}")


def get_nfl_player_stats(player_id, season=None):
    """Pull NFL skill position stats from ESPN API."""
    if season is None:
        season = NFL_SEASON_2026
    ck = f"nfl_player:{player_id}:{season}"
    cached = cget(ck)
    if cached: return cached

    # Try requested season first, fall back to 2025
    for yr in ([season, NFL_SEASON_2025] if season == NFL_SEASON_2026 else [season]):
        try:
            data = nfl_get(f"{NFL_BASE}/athletes/{player_id}/statistics",
                           {"season": yr})
            splits = data.get("statistics", {})
            cats   = data.get("categories", [])
            names  = data.get("names", [])

            # Build stat dict from ESPN's category structure
            stat_dict = {}
            for cat in (splits.get("categories") or cats or []):
                cat_name = cat.get("name","").lower()
                for i, val in enumerate(cat.get("values", [])):
                    label = (cat.get("labels") or cat.get("names") or names or [])[i] if i < len((cat.get("labels") or cat.get("names") or names or [])) else f"{cat_name}_{i}"
                    stat_dict[f"{cat_name}_{label}".lower()] = val

            # Also try flat stats
            flat = data.get("athlete", {}).get("statistics", [])
            for item in flat:
                stat_dict[item.get("name","").lower()] = item.get("value", 0)

            gp = int(stat_dict.get("general_gamesplayed", stat_dict.get("gamesplayed", 0)) or 0)
            if gp == 0:
                continue

            # Extract by position
            # Receiving
            rec        = int(stat_dict.get("receiving_receptions", stat_dict.get("receptions", 0)) or 0)
            rec_tgt    = int(stat_dict.get("receiving_targets", stat_dict.get("targets", 0)) or 0)
            rec_yds    = float(stat_dict.get("receiving_receivingyards", stat_dict.get("receivingyards", 0)) or 0)
            rec_td     = int(stat_dict.get("receiving_receivingtouchdowns", stat_dict.get("receivingtouchdowns", 0)) or 0)
            rec_rz_tgt = int(stat_dict.get("receiving_receptionsinredzone", stat_dict.get("receptionsinredzone", 0)) or 0)

            # Rushing
            rush_att   = int(stat_dict.get("rushing_rushingAttempts", stat_dict.get("rushingattempts", 0)) or 0)
            rush_yds   = float(stat_dict.get("rushing_rushingyards", stat_dict.get("rushingyards", 0)) or 0)
            rush_td    = int(stat_dict.get("rushing_rushingtouchdowns", stat_dict.get("rushingtouchdowns", 0)) or 0)
            rush_rz    = int(stat_dict.get("rushing_rushingattemptsinredzone", stat_dict.get("rushingattemptsinredzone", 0)) or 0)

            total_td   = rec_td + rush_td
            tdpg       = round(total_td / gp, 3) if gp > 0 else 0
            tgt_pg     = round(rec_tgt / gp, 1) if gp > 0 else 0
            att_pg     = round(rush_att / gp, 1) if gp > 0 else 0
            rec_ypg    = round(rec_yds / gp, 1) if gp > 0 else 0
            rush_ypg   = round(rush_yds / gp, 1) if gp > 0 else 0
            rz_looks   = rec_rz_tgt + rush_rz
            rz_pg      = round(rz_looks / gp, 2) if gp > 0 else 0

            # Position from athlete data
            athlete    = data.get("athlete", {})
            pos        = athlete.get("position", {}).get("abbreviation", "WR") if isinstance(athlete.get("position"), dict) else "WR"

            result = {
                "GP": gp, "pos": pos,
                "TD": total_td, "rec_TD": rec_td, "rush_TD": rush_td,
                "TDPG": tdpg,
                "TGT": rec_tgt, "TGT_PG": tgt_pg,
                "REC": rec, "REC_YDS": rec_yds, "REC_YPG": rec_ypg,
                "RUSH_ATT": rush_att, "RUSH_YDS": rush_yds, "RUSH_YPG": rush_ypg,
                "ATT_PG": att_pg,
                "RZ_LOOKS": rz_looks, "RZ_PG": rz_pg,
                "small_sample": gp < 6,
                "season_used": yr,
            }
            cset(ck, result)
            return result
        except Exception:
            continue

    raise ValueError(f"No NFL stats found for player {player_id}")


def get_nfl_defense(team_abbr, season=None):
    """Pull team defensive stats against skill positions."""
    if season is None:
        season = NFL_SEASON_2025
    ck = f"nfl_def:{team_abbr}:{season}"
    cached = cget(ck)
    if cached: return cached

    try:
        # Get team ID first
        teams_data = nfl_get(f"{NFL_BASE}/teams")
        teams = teams_data.get("sports",[{}])[0].get("leagues",[{}])[0].get("teams",[])
        team_id = None
        for t in teams:
            tm = t.get("team",{})
            if tm.get("abbreviation","").upper() == team_abbr.upper():
                team_id = tm.get("id")
                break

        if not team_id:
            raise ValueError("Team not found")

        data = nfl_get(f"{NFL_BASE}/teams/{team_id}/statistics",
                       {"season": season})

        stat_dict = {}
        for cat in data.get("results", {}).get("stats", {}).get("categories", []):
            for stat in cat.get("stats", []):
                stat_dict[stat.get("name","").lower()] = stat.get("value", 0)

        gp       = int(stat_dict.get("gamesplayed", 17) or 17)
        pts_all  = float(stat_dict.get("pointsallowed", stat_dict.get("totalPointsAllowed", 0)) or 0)
        yds_all  = float(stat_dict.get("totalyardsallowed", stat_dict.get("yardsAllowed", 0)) or 0)
        td_all   = float(stat_dict.get("touchdownsallowed", 0) or 0)
        pass_td  = float(stat_dict.get("passingtouchdownsallowed", 0) or 0)
        rush_td  = float(stat_dict.get("rushingtouchdownsallowed", 0) or 0)

        tdpg_all = round((td_all or (pass_td + rush_td)) / gp, 3) if gp > 0 else NFL_LG["DEF_TDPG"] / 16

        result = {
            "GP": gp,
            "TD_allowed": int(td_all or (pass_td + rush_td)),
            "TDPG": tdpg_all,
            "PTS_pg": round(pts_all / gp, 1) if gp > 0 else 0,
            "YDS_pg": round(yds_all / gp, 1) if gp > 0 else 0,
            "live": True,
        }
        cset(ck, result)
        return result
    except Exception:
        return {
            "TDPG": NFL_LG["DEF_TDPG"] / 16,
            "PTS_pg": 22.5, "YDS_pg": 340.0,
            "live": False,
        }


@app.route("/nfl/search")
def nfl_search():
    name = request.args.get("name","").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    try:
        results = search_nfl_player(name)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nfl/player/<player_id>")
def nfl_player(player_id):
    try:
        data = get_nfl_player_stats(player_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nfl/defense/<team>")
def nfl_defense(team):
    try:
        data = get_nfl_defense(team.upper())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nfl/teams")
def nfl_teams_list():
    return jsonify(NFL_TEAMS_MAP)

# ═══════════════════════════════════════════════════════════════
# NBA ROUTES
# ═══════════════════════════════════════════════════════════════

NBA_BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
NBA_CDN  = "https://site.web.api.espn.com/apis/common/v3/sports/basketball/nba"

NBA_SEASON_2526 = 2025   # ESPN uses ending year for season (2025-26 = 2026)
NBA_SEASON_2627 = 2026   # 2026-27 = 2027

# League averages (2024-25)
NBA_LG = {
    "PPG":    111.5,
    "PACE":   99.2,
    "DEF_RTG": 113.8,
    "FGA_PG":  88.0,
    "FTA_PG":  22.0,
    "USG":     20.0,
    "TS_PCT":  0.582,
}

NBA_TEAMS_MAP = {
    "ATL":"Atlanta Hawks","BOS":"Boston Celtics","BKN":"Brooklyn Nets",
    "CHA":"Charlotte Hornets","CHI":"Chicago Bulls","CLE":"Cleveland Cavaliers",
    "DAL":"Dallas Mavericks","DEN":"Denver Nuggets","DET":"Detroit Pistons",
    "GSW":"Golden State Warriors","HOU":"Houston Rockets","IND":"Indiana Pacers",
    "LAC":"LA Clippers","LAL":"Los Angeles Lakers","MEM":"Memphis Grizzlies",
    "MIA":"Miami Heat","MIL":"Milwaukee Bucks","MIN":"Minnesota Timberwolves",
    "NOP":"New Orleans Pelicans","NYK":"New York Knicks","OKC":"Oklahoma City Thunder",
    "ORL":"Orlando Magic","PHI":"Philadelphia 76ers","PHX":"Phoenix Suns",
    "POR":"Portland Trail Blazers","SAC":"Sacramento Kings","SAS":"San Antonio Spurs",
    "TOR":"Toronto Raptors","UTA":"Utah Jazz","WSH":"Washington Wizards",
}


def search_nba_player(name):
    ck = f"nba_search:{name.lower()}"
    cached = cget(ck)
    if cached: return cached
    try:
        data = nfl_get(f"{NBA_BASE}/athletes",
                       {"search": name, "limit": 10, "active": True})
        athletes = data.get("items", []) or data.get("athletes", [])
        results = []
        for a in athletes[:8]:
            results.append({
                "id":       a.get("id",""),
                "name":     a.get("fullName","") or a.get("displayName",""),
                "position": a.get("position",{}).get("abbreviation","") if isinstance(a.get("position"),dict) else "",
                "team":     a.get("team",{}).get("abbreviation","") if isinstance(a.get("team"),dict) else "",
            })
        if not results:
            data2 = nfl_get("https://site.api.espn.com/apis/search/v2",
                            {"query": name, "sport": "basketball", "league": "nba", "limit": 8})
            for h in data2.get("results",[]):
                if h.get("type") != "athlete": continue
                results.append({"id":h.get("id",""),"name":h.get("displayName",""),"position":"","team":""})
        cset(ck, results)
        return results
    except Exception as e:
        raise ValueError(f"NBA player search failed: {e}")


def get_nba_player_stats(player_id, season=None):
    """Pull NBA player stats from ESPN API."""
    if season is None:
        season = NBA_SEASON_2526
    ck = f"nba_player:{player_id}:{season}"
    cached = cget(ck)
    if cached: return cached

    for yr in ([season, NBA_SEASON_2526] if season == NBA_SEASON_2627 else [season, NBA_SEASON_2526]):
        try:
            data = nfl_get(f"{NBA_BASE}/athletes/{player_id}/statistics",
                           {"season": yr})
            cats = data.get("statistics", {}).get("categories", []) or data.get("categories", [])
            stat_dict = {}
            for cat in cats:
                cat_name = cat.get("name","").lower()
                labels = cat.get("labels", cat.get("names", []))
                vals   = cat.get("values", [])
                for i, val in enumerate(vals):
                    lbl = labels[i] if i < len(labels) else f"stat_{i}"
                    stat_dict[f"{cat_name}_{lbl}".lower().replace(" ","_")] = val

            # Also try flat
            for item in data.get("athlete",{}).get("statistics",[]):
                stat_dict[item.get("name","").lower()] = item.get("value",0)

            gp  = int(stat_dict.get("general_gamesplayed", stat_dict.get("gamesplayed",0)) or 0)
            if gp == 0: continue

            ppg  = float(stat_dict.get("scoring_pts",    stat_dict.get("scoring_avgpoints",    stat_dict.get("avgpoints",0)))    or 0)
            apg  = float(stat_dict.get("general_ast",    stat_dict.get("assists",0)))    or 0
            rpg  = float(stat_dict.get("rebounds_totreb",stat_dict.get("totalrebounds",0))) or 0
            mpg  = float(stat_dict.get("general_min",    stat_dict.get("avgminutes",0)))     or 0
            fga  = float(stat_dict.get("shooting_fga",   stat_dict.get("fieldgoalsattempted",0))) or 0
            fgm  = float(stat_dict.get("shooting_fgm",   stat_dict.get("fieldgoalsmade",0)))      or 0
            fg3a = float(stat_dict.get("shooting_3pa",   stat_dict.get("threepointersattempted",0))) or 0
            fg3m = float(stat_dict.get("shooting_3pm",   stat_dict.get("threepointersmade",0)))      or 0
            fta  = float(stat_dict.get("shooting_fta",   stat_dict.get("freethrowsattempted",0))) or 0
            ftm  = float(stat_dict.get("shooting_ftm",   stat_dict.get("freethrowsmade",0)))      or 0
            fg_pct  = round(fgm/fga, 3)  if fga > 0 else 0
            ft_pct  = round(ftm/fta, 3)  if fta > 0 else 0
            fg3_pct = round(fg3m/fg3a,3) if fg3a > 0 else 0
            # True shooting %: PTS / (2 * (FGA + 0.44*FTA))
            ts_pct  = round(ppg / (2*(fga+0.44*fta)), 3) if (fga+fta) > 0 else 0
            # Usage rate estimate: (FGA + 0.44*FTA + TOV) / team_poss — approximate from FGA+FTA
            usg_est = round((fga + 0.44*fta) / max(1, mpg/48*100), 1)
            fga_pg  = round(fga, 1)
            fta_pg  = round(fta, 1)

            athlete = data.get("athlete",{})
            pos = athlete.get("position",{}).get("abbreviation","G") if isinstance(athlete.get("position"),dict) else "G"

            result = {
                "GP":gp,"pos":pos,
                "PPG":round(ppg,1),"APG":round(apg,1),"RPG":round(rpg,1),
                "MPG":round(mpg,1),
                "FGA":fga_pg,"FGM":round(fgm,1),"FG_PCT":fg_pct,
                "FG3A":round(fg3a,1),"FG3M":round(fg3m,1),"FG3_PCT":fg3_pct,
                "FTA":fta_pg,"FTM":round(ftm,1),"FT_PCT":ft_pct,
                "TS_PCT":ts_pct,"USG_EST":usg_est,
                "small_sample":gp < 10,
                "season_used":yr,
            }
            cset(ck, result)
            return result
        except Exception:
            continue

    raise ValueError(f"No NBA stats found for player {player_id}")


def get_nba_defense(team_abbr, season=None):
    """Pull NBA team defensive stats."""
    if season is None:
        season = NBA_SEASON_2526
    ck = f"nba_def:{team_abbr}:{season}"
    cached = cget(ck)
    if cached: return cached

    try:
        teams_data = nfl_get(f"{NBA_BASE}/teams")
        teams = teams_data.get("sports",[{}])[0].get("leagues",[{}])[0].get("teams",[])
        team_id = None
        for t in teams:
            tm = t.get("team",{})
            if tm.get("abbreviation","").upper() == team_abbr.upper():
                team_id = tm.get("id")
                break

        if not team_id:
            raise ValueError("Team not found")

        data = nfl_get(f"{NBA_BASE}/teams/{team_id}/statistics",
                       {"season": season})
        stat_dict = {}
        for cat in data.get("results",{}).get("stats",{}).get("categories",[]):
            for stat in cat.get("stats",[]):
                stat_dict[stat.get("name","").lower()] = stat.get("value",0)

        gp       = int(stat_dict.get("gamesplayed", 82) or 82)
        pts_all  = float(stat_dict.get("pointsallowed", stat_dict.get("opppoints", 0)) or 0)
        pace     = float(stat_dict.get("pace", NBA_LG["PACE"]) or NBA_LG["PACE"])
        def_rtg  = float(stat_dict.get("defensiverating", NBA_LG["DEF_RTG"]) or NBA_LG["DEF_RTG"])
        papg     = round(pts_all/gp, 1) if gp > 0 and pts_all > 0 else NBA_LG["PPG"]

        result = {
            "GP": gp, "PAPG": papg,
            "PACE": round(pace,1),
            "DEF_RTG": round(def_rtg,1),
            "live": True,
        }
        cset(ck, result)
        return result
    except Exception:
        return {"PAPG": NBA_LG["PPG"], "PACE": NBA_LG["PACE"],
                "DEF_RTG": NBA_LG["DEF_RTG"], "live": False}


@app.route("/nba/search")
def nba_search():
    name = request.args.get("name","").strip()
    if not name:
        return jsonify({"error":"name required"}), 400
    try:
        results = search_nba_player(name)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nba/player/<player_id>")
def nba_player(player_id):
    try:
        data = get_nba_player_stats(player_id)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nba/defense/<team>")
def nba_defense(team):
    try:
        data = get_nba_defense(team.upper())
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nba/teams")
def nba_teams():
    return jsonify(NBA_TEAMS_MAP)

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
    games = int(s.get("gamesPitched",0))

    gb_pct     = round(go_ao/(1+go_ao), 4)
    hrfb_pct   = round(min(0.35, hr/max(1,ip*(1-gb_pct)*3)), 4)
    fip        = max(1.5,min(7.5,round((13*hr+3*bb-2*ks)/ip+3.10,2) if ip>0 else 4.00))
    barrel_pct = round(min(0.20, hrfb_pct*0.65), 4)

    pinfo = mlb(f"/people/{pid}")
    hand  = pinfo.get("people",[{}])[0].get("pitchHand",{}).get("code","R")

    sv_bar = savant_pitcher(pid, season)
    if sv_bar: barrel_pct = sv_bar

    result = {
        "G":games,"IP":ip,"HR":hr,"BB":bb,"K":ks,"ERA":era,"WHIP":whip,
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
