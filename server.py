"""
HR Probability App — Backend API
Fetches from MLB Stats API + Baseball Savant.
Deploy to Railway or run locally.
"""

from flask import Flask, jsonify, request
from flask_cors import CORS
import requests, time, os, json

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
    key_set = bool(os.environ.get("ANTHROPIC_API_KEY",""))
    return jsonify({"status":"ok","season":SEASON,"anthropic_key_set": key_set})


@app.route("/clear-cache")
def clear_cache():
    CACHE.clear()
    return jsonify({"status":"cache cleared"})


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

NHL_SEASON_2526 = 20252026   # 2025-26 season
NHL_SEASON_2627 = 20262027   # 2026-27 season
NHL_SEASON_2425 = 20242025   # 2024-25 fallback

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
        return NHL_SEASON_2627
    except Exception:
        return NHL_SEASON_2526


def search_nhl_player(name):
    """Search NHL Stats API for a player by name."""
    ck = f"nhl_search:{name.lower()}"
    cached = cget(ck)
    if cached: return cached
    try:
        parts = name.strip().split()
        # For the last name, try both as-typed and title-cased
        # This handles names like MacKinnon, O'Reilly, etc.
        raw_last   = parts[-1] if parts else name
        raw_first  = parts[0]  if len(parts) > 1 else ""
        # Generate name variants to try
        last_variants  = list(dict.fromkeys([raw_last, raw_last.title(), raw_last.capitalize()]))
        first_variants = list(dict.fromkeys([raw_first, raw_first.title()])) if raw_first else [""]

        results = []
        skater_url = "https://api.nhle.com/stats/rest/en/skater/summary"
        goalie_url = "https://api.nhle.com/stats/rest/en/goalie/summary"

        def try_search(exp):
            found = []
            try:
                d = nhl_get(skater_url, {"limit":8,"start":0,"sort":"points","dir":"desc","cayenneExp":exp})
                for p in (d.get("data") or [])[:8]:
                    pid = p.get("playerId")
                    if not pid: continue
                    found.append({"id":int(pid),"name":p.get("skaterFullName","").strip(),"position":p.get("positionCode",""),"team":p.get("teamAbbrevs","")})
            except Exception: pass
            if not found:
                try:
                    d = nhl_get(goalie_url, {"limit":8,"start":0,"sort":"wins","dir":"desc","cayenneExp":exp})
                    for p in (d.get("data") or [])[:8]:
                        pid = p.get("playerId")
                        if not pid: continue
                        found.append({"id":int(pid),"name":p.get("goalieFullName","").strip(),"position":"G","team":p.get("teamAbbrevs","")})
                except Exception: pass
            return found

        for season_id in [20252026, 20242025]:
            if results: break
            for last in last_variants:
                if results: break
                exps = []
                for fv in first_variants:
                    if fv:
                        exps.append(f'lastName="{last}" and firstName="{fv}" and seasonId={season_id} and gameTypeId=2')
                exps.append(f'lastName="{last}" and seasonId={season_id} and gameTypeId=2')
                for exp in exps:
                    results = try_search(exp)
                    if results: break

        if not results:
            raise ValueError(f"No NHL player found for '{name}'. Enter last name only (e.g. McDavid, Hellebuyck).")

        cset(ck, results)
        return results
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"NHL player search failed: {e}")


def get_skater_stats(pid, season=None):
    """Pull skater stats from NHL Stats API."""
    if season is None:
        season = NHL_SEASON_2526
    ck = f"nhl_skater:{pid}:{season}"
    cached = cget(ck)
    if cached: return cached

    for sid in [season, NHL_SEASON_2526, NHL_SEASON_2425]:
        try:
            data = nhl_get("https://api.nhle.com/stats/rest/en/skater/summary", {
                "limit": 1, "start": 0,
                "cayenneExp": f"playerId={pid} and seasonId={sid} and gameTypeId=2"
            })
            rows = data.get("data", [])
            if not rows:
                continue
            s = rows[0]
            gp       = int(s.get("gamesPlayed", 0))
            goals    = int(s.get("goals", 0))
            assists  = int(s.get("assists", 0))
            pts      = int(s.get("points", 0))
            shots    = int(s.get("shots", 0))
            ppg      = int(s.get("ppGoals", 0))
            ppp      = int(s.get("ppPoints", 0))
            toi_pg   = s.get("timeOnIcePerGame", "0:00")
            plus_m   = int(s.get("plusMinus", 0))
            gpg      = round(goals/gp, 4)        if gp > 0 else 0
            spg      = round(shots/gp, 2)        if gp > 0 else 0
            sh_pct   = round(goals/shots*100, 1) if shots > 0 else 0
            ppgpg    = round(ppg/gp, 3)          if gp > 0 else 0
            result = {
                "GP": gp, "G": goals, "A": assists, "PTS": pts,
                "S": shots, "S_pct": sh_pct, "PPG": ppg, "PPP": ppp,
                "GPG": gpg, "SPG": spg, "PPGPG": ppgpg,
                "TOI": toi_pg, "plusMinus": plus_m,
                "small_sample": gp < 10,
                "season_used": sid,
            }
            cset(ck, result)
            return result
        except Exception:
            continue
    raise ValueError(f"No NHL skater stats found for player {pid}")


def get_goalie_stats(pid, season=None):
    """Pull goalie stats from NHL Stats API."""
    if season is None:
        season = NHL_SEASON_2526
    ck = f"nhl_goalie:{pid}:{season}"
    cached = cget(ck)
    if cached: return cached

    for sid in [season, NHL_SEASON_2526, NHL_SEASON_2425]:
        try:
            data = nhl_get("https://api.nhle.com/stats/rest/en/goalie/summary", {
                "limit": 1, "start": 0,
                "cayenneExp": f"playerId={pid} and seasonId={sid} and gameTypeId=2"
            })
            rows = data.get("data", [])
            if not rows:
                continue
            s    = rows[0]
            gp   = int(s.get("gamesPlayed", 0))
            wins = int(s.get("wins", 0))
            gaa  = round(float(s.get("goalsAgainstAverage", 0) or 0), 2)
            sv   = round(float(s.get("savePct", 0) or 0), 3)
            sa   = int(s.get("shotsAgainst", 0))
            ga   = int(s.get("goalsAgainst", 0))
            so   = int(s.get("shutouts", 0))
            sapg = round(sa/gp, 1) if gp > 0 else 0
            result = {
                "GP": gp, "W": wins, "GAA": gaa, "SV_PCT": sv,
                "SA": sa, "GA": ga, "SO": so, "SAPG": sapg,
                "small_sample": gp < 5,
            }
            cset(ck, result)
            return result
        except Exception:
            continue
    raise ValueError(f"No NHL goalie stats found for player {pid}")


def get_team_defense(team_abbr, season=None):
    """Pull team defense stats using NHL Stats API with Claude AI fallback."""
    ck = f"nhl_team_def:{team_abbr}"
    cached = cget(ck)
    if cached: return cached

    # Try NHL Stats API standings first
    try:
        data = nhl_get(f"{NHL}/standings/now")
        standings = data.get("standings", [])
        team = next((t for t in standings
                     if t.get("teamAbbrev",{}).get("default","") == team_abbr), None)
        if team:
            gp   = int(team.get("gamesPlayed", 1))
            ga   = int(team.get("goalAgainst", 0))
            gf   = int(team.get("goalFor", 0))
            if gp > 0 and ga > 0:
                gapg = round(ga/gp, 2)
                result = {"GP": gp, "GA": ga, "GF": gf, "GAPG": gapg, "live": True}
                cset(ck, result)
                return result
    except Exception:
        pass

    # Fallback: use Claude AI with team-specific context
    try:
        nhl_teams_full = {
            "ANA":"Anaheim Ducks","UTA":"Utah Hockey Club","BOS":"Boston Bruins",
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
        team_name = nhl_teams_full.get(team_abbr, team_abbr)
        d = claude_stats(
            f'Return the actual 2024-25 NHL season goals against stats for the {team_name} ({team_abbr}). '
            f'These must be real stats unique to this team, not league averages. '
            f'Context: elite defenses (FLA, CAR, DAL) allow ~2.5-2.7 goals/game, '
            f'average teams allow ~2.8-3.1 goals/game, poor defenses (SJS, ANA, CHI) allow ~3.3-3.8 goals/game. '
            f'JSON keys: GP(int 82), GA(int total goals against), '
            f'GAPG(float goals against per game for {team_name} specifically), '
            f'GF(int total goals for), live(bool false). '
            f'Return only real 2024-25 stats for {team_name}.'
        )
        cset(ck, d)
        return d
    except Exception:
        # Last resort: position-based estimate
        return {"GAPG": 3.0, "GA": 246, "GF": 246, "GP": 82, "live": False}


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
        # ESPN search API
        data = nfl_get("https://site.api.espn.com/apis/search/v2",
                       {"query": name, "sport": "football",
                        "league": "nfl", "limit": 10})
        raw = [h for h in data.get("results", []) if h.get("type") == "athlete"]

        if not raw:
            raise ValueError(f"No NFL player found for '{name}'. Check spelling (First Last).")

        results = []
        NON_SKILL = {"QB","K","P","LS","CB","S","LB","DE","DT","OT","OG","C","NT","DL","OL","DB","ILB","OLB","SS","FS"}

        for r in raw[:6]:
            pid = r.get("id","")
            pname = r.get("displayName","") or r.get("name","")
            pos, team = "", ""
            try:
                ath  = nfl_get(f"{NFL_BASE}/athletes/{pid}")
                a    = ath.get("athlete", {})
                pos  = a.get("position",{}).get("abbreviation","") if isinstance(a.get("position"),dict) else ""
                team = a.get("team",{}).get("abbreviation","")     if isinstance(a.get("team"),dict)     else ""
                pname= a.get("fullName","") or pname
            except Exception:
                pass
            # Skip known non-skill positions
            if pos.upper() in NON_SKILL:
                continue
            results.append({"id": pid, "name": pname, "position": pos, "team": team})

        # If filtering removed everything, return top 3 unfiltered
        if not results:
            for r in raw[:3]:
                results.append({"id": r.get("id",""),
                                 "name": r.get("displayName","") or r.get("name",""),
                                 "position": "", "team": ""})

        cset(ck, results)
        return results
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"NFL player search failed: {e}")



# ═══════════════════════════════════════════════════════════════
# NFL ROUTES — Claude AI powered (ESPN blocks server requests)
# ═══════════════════════════════════════════════════════════════


NFL_LG = {
    "RB_TDPG": 0.45, "WR_TDPG": 0.22, "TE_TDPG": 0.18,
    "DEF_TDPG": 0.15, "DEF_PTS": 22.5,
}

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


def claude_stats(prompt):
    """Call Claude API for player stats. Returns parsed JSON dict."""
    api_key = os.environ.get("ANTHROPIC_API_KEY","")
    if not api_key:
        raise ValueError("ANTHROPIC_API_KEY not set in environment variables")
    r = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01",
                 "content-type": "application/json"},
        json={"model": "claude-haiku-4-5-20251001", "max_tokens": 600,
              "system": "Return ONLY valid JSON, no markdown, no explanation.",
              "messages": [{"role": "user", "content": prompt}]},
        timeout=15
    )
    data = r.json()
    if "error" in data:
        err = data.get("error", {})
        raise ValueError(f"Anthropic API error: {err.get('type','')} — {err.get('message','')}")
    if "content" in data and isinstance(data["content"], list):
        txt = data["content"][0].get("text","")
    elif "content" in data and isinstance(data["content"], str):
        txt = data["content"]
    else:
        raise ValueError(f"Unexpected API response: {data}")
    txt = txt.replace("```json","").replace("```","").strip()
    return json.loads(txt)


@app.route("/nfl/search")
def nfl_search():
    name = request.args.get("name","").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    ck = f"nfl_search:{name.lower()}"
    cached = cget(ck)
    if cached: return jsonify({"results": cached})
    try:
        d = claude_stats(
            f'NFL player search for "{name}". Return JSON: {{"results": ['
            f'{{"id": "espn_id_string", "name": "Full Name", "position": "WR/RB/TE", "team": "ABBR"}}]}}. '
            f'Return up to 3 matching active or recently active NFL skill position players (RB/WR/TE). '
            f'Use realistic ESPN player IDs. If only one match exists return just that one.'
        )
        results = d.get("results", [])
        cset(ck, results)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nfl/player/<player_id>")
def nfl_player(player_id):
    name = request.args.get("name", player_id)
    ck = f"nfl_player_ai:{name.lower()}"
    cached = cget(ck)
    if cached: return jsonify(cached)
    try:
        d = claude_stats(
            f'Return the actual 2025 NFL regular season stats for "{name}". '
            f'These must be real stats for this specific player. '
            f'JSON keys: GP(int), pos(str WR/RB/TE), TD(int total touchdowns), '
            f'rec_TD(int receiving TDs), rush_TD(int rushing TDs), '
            f'TDPG(float TDs per game), TGT(int total targets), TGT_PG(float targets per game), '
            f'REC(int receptions), REC_YDS(float receiving yards), REC_YPG(float rec yards per game), '
            f'RUSH_ATT(int rush attempts), RUSH_YDS(float rush yards), RUSH_YPG(float rush yards per game), '
            f'ATT_PG(float rush attempts per game), '
            f'RZ_LOOKS(int red zone targets+carries), RZ_PG(float red zone looks per game), '
            f'small_sample(bool false), season_used(int 2024).'
        )
        cset(ck, d)
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nfl/defense/<team>")
def nfl_defense(team):
    team = team.upper()
    ck = f"nfl_def_ai:{team}"
    cached = cget(ck)
    if cached: return jsonify(cached)
    try:
        team_name = NFL_TEAMS_MAP.get(team, team)
        d = claude_stats(
            f'Return the actual 2025 NFL regular season defensive stats specifically for the {team_name} ({team}). '
            f'These must be real stats unique to this team, not league averages. '
            f'For example: a strong defense like SF or BAL allows ~17-20 pts/g, '
            f'a weak defense like CAR or NE allows ~27-30 pts/g, average teams ~22-24 pts/g. '
            f'JSON keys: GP(int, 17), TD_allowed(int, total TDs allowed on season), '
            f'TDPG(float, TDs allowed per game), '
            f'PTS_pg(float, points allowed per game specific to {team_name}), '
            f'YDS_pg(float, yards allowed per game specific to {team_name}), '
            f'live(bool, false). '
            f'Return only real 2024 stats for {team_name}, not generic values.'
        )
        cset(ck, d)
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nfl/teams")
def nfl_teams_list():
    return jsonify(NFL_TEAMS_MAP)


# ═══════════════════════════════════════════════════════════════
# NBA ROUTES — Claude AI powered
# ═══════════════════════════════════════════════════════════════

NBA_LG = {
    "PPG": 111.5, "PACE": 99.2, "DEF_RTG": 113.8,
    "FGA_PG": 88.0, "FTA_PG": 22.0, "TS_PCT": 0.582,
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


@app.route("/nba/search")
def nba_search():
    name = request.args.get("name","").strip()
    if not name:
        return jsonify({"error": "name required"}), 400
    ck = f"nba_search:{name.lower()}"
    cached = cget(ck)
    if cached: return jsonify({"results": cached})
    try:
        d = claude_stats(
            f'NBA player search for "{name}". Return JSON: {{"results": ['
            f'{{"id": "espn_id_string", "name": "Full Name", "position": "G/F/C/PG/SG/SF/PF", "team": "ABBR"}}]}}. '
            f'Return up to 3 matching active NBA players. Use realistic ESPN player IDs.'
        )
        results = d.get("results", [])
        cset(ck, results)
        return jsonify({"results": results})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nba/player/<player_id>")
def nba_player(player_id):
    name = request.args.get("name", player_id)
    ck = f"nba_player_ai:{name.lower()}"
    cached = cget(ck)
    if cached: return jsonify(cached)
    try:
        d = claude_stats(
            f'Return the actual 2025-26 NBA season stats for "{name}". '
            f'These must be real stats specific to this player. '
            f'JSON keys: GP(int), pos(str), PPG(float 1dp), APG(float), RPG(float), MPG(float), '
            f'FGA(float per game), FGM(float), FG_PCT(float 0-1), '
            f'FG3A(float), FG3M(float), FG3_PCT(float 0-1), '
            f'FTA(float), FTM(float), FT_PCT(float 0-1), '
            f'TS_PCT(float 0-1), USG_EST(float percentage like 28.5), '
            f'small_sample(bool), season_used(int 2026).'
        )
        cset(ck, d)
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nba/defense/<team>")
def nba_defense(team):
    team = team.upper()
    ck = f"nba_def_ai:{team}"
    cached = cget(ck)
    if cached: return jsonify(cached)
    try:
        team_name = NBA_TEAMS_MAP.get(team, team)
        d = claude_stats(
            f'Return the actual 2025-26 NBA season defensive stats for the {team_name} ({team}). '
            f'These must be real stats unique to this specific team, not league averages. '
            f'Context: elite defenses (OKC, BOS, CLE) allow ~105-108 pts/g, '
            f'average teams allow ~112-115 pts/g, poor defenses allow ~118-122 pts/g. '
            f'Fast-paced teams (ATL, SAC) have pace 100+, slow teams (NYK, MEM) have pace 96-98. '
            f'JSON keys: GP(int), PAPG(float points allowed per game for {team_name} specifically), '
            f'PACE(float possessions per game for {team_name}), '
            f'DEF_RTG(float defensive rating for {team_name}), live(bool false). '
            f'Return only real 2025-26 stats for {team_name}, not generic values.'
        )
        cset(ck, d)
        return jsonify(d)
    except Exception as e:
        return jsonify({"error": str(e)}), 404


@app.route("/nba/teams")
def nba_teams():
    return jsonify(NBA_TEAMS_MAP)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"\n⚾  HR Backend running on port {port}\n")
    app.run(host="0.0.0.0", port=port, debug=False)
