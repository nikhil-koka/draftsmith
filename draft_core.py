import requests
import base64
import pandas as pd
import certifi
import urllib3
import numpy as np
from sklearn.model_selection import GroupShuffleSplit
from sklearn.ensemble import RandomForestClassifier
from scipy.optimize import linear_sum_assignment

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

http_insecure = urllib3.PoolManager(cert_reqs="CERT_NONE")

version  = "16.4.1"
roles    = ["top", "jng", "mid", "bot", "sup"]
ban_cols = [f"ban{i}" for i in range(1, 6)]

role_tags = {
    "Fighter":  {"top": 0.5,  "jng": 0.3,  "mid": 0.1,  "bot": 0.05, "sup": 0.05},
    "Tank":     {"top": 0.4,  "jng": 0.2,  "mid": 0.05, "bot": 0.05, "sup": 0.3},
    "Mage":     {"top": 0.05, "jng": 0.05, "mid": 0.6,  "bot": 0.05, "sup": 0.25},
    "Assassin": {"top": 0.1,  "jng": 0.35, "mid": 0.5,  "bot": 0.03, "sup": 0.02},
    "Marksman": {"top": 0.02, "jng": 0.05, "mid": 0.05, "bot": 0.85, "sup": 0.03},
    "Support":  {"top": 0.02, "jng": 0.03, "mid": 0.05, "bot": 0.05, "sup": 0.85},
}


name_table      = {}
name_data_keyed = {}
name_to_id      = {}
id_to_name      = {}
matches_df      = None
prob_df         = None
champion_list   = []
forest_mod      = None
df_model_lanes  = None
players         = None
_initialized    = False
min_games       = 10


def initialize(ranked_csv: str, pro_csv: str, status_cb=None):
    global name_table, name_data_keyed, name_to_id, id_to_name
    global matches_df, prob_df, champion_list, forest_mod, df_model_lanes
    global players, _initialized

    def log(msg):
        if status_cb:
            status_cb(msg)

    log("Fetching champion data from DataDragon...")
    url       = f"https://ddragon.leagueoflegends.com/cdn/{version}/data/en_US/champion.json"
    name_data = requests.get(url).json()["data"]
    for champ in name_data:
        name_table[champ] = name_data[champ]["name"]
    name_table["FiddleSticks"] = "Fiddlesticks"
    name_data_keyed.update({v["name"]: v for v in name_data.values()})
    name_to_id.update({c["name"]: int(c["key"]) for c in name_data_keyed.values()})
    id_to_name.update({int(c["key"]): c["name"] for c in name_data_keyed.values()})

    log("Loading ranked dataset...")
    raw = pd.read_csv(ranked_csv)
    if "Unnamed: 0" in raw.columns:
        raw = raw.drop(columns=["Unnamed: 0"])
    matches_df = raw.copy()

    required = roles + ban_cols + ["result", "gameid", "patch", "side"]
    missing  = [c for c in required if c not in matches_df.columns]
    if missing:
        raise ValueError(f"ranked_dataset.csv is missing columns: {missing}")

    prob_df = matches_df[["top","jng","mid","bot","sup"]].melt(
        var_name="position", value_name="champion")

    all_champs = pd.concat(
        [matches_df[["top","jng","mid","bot","sup"]], matches_df[ban_cols]], axis=0
    ).values.ravel()
    champion_list.clear()
    champion_list.extend(pd.Series(all_champs).dropna().unique().tolist())

    log("Preparing features...")
    matches_df = matches_df[matches_df["patch"].astype(str).str.startswith("16")].copy()
    if matches_df.empty:
        raise ValueError(
            "No rows found for patch 16.x in your ranked_dataset.csv.\n"
            "Make sure your data contains games from the current season."
        )

    matches_df["weight"] = (
        matches_df["patch"].astype(str).str.split(".").str[1].astype(int) * 10
    )
    matches_df[[f"opp_{c}" for c in ban_cols]] = (
        matches_df.groupby("gameid")[ban_cols]
        .transform(lambda x: x.iloc[::-1].values)
    )

    new_cols = {}
    for role in roles:
        for champ in champion_list:
            new_cols[f"pick_{champ}_{role}"] = (
                matches_df[roles].eq(champ).any(axis=1).astype(int)
                - matches_df[[f"opp_{r}" for r in roles]].eq(champ).any(axis=1).astype(int)
            )
    for champ in champion_list:
        new_cols[f"ban_{champ}"] = (
            matches_df[ban_cols].eq(champ).any(axis=1)
            | matches_df[[f"opp_{c}" for c in ban_cols]].eq(champ).any(axis=1)
        ).astype(int)

    new_features = pd.DataFrame(new_cols, index=matches_df.index)
    matches_df   = pd.concat([matches_df, new_features], axis=1)
    matches_df["side"] = matches_df["side"].map({"Red": 0, "Blue": 1})

    drop = (roles + ban_cols
            + [f"opp_{c}" for c in roles]
            + [f"opp_{c}" for c in ban_cols])
    df_model_lanes = matches_df.drop(columns=drop)

    x      = df_model_lanes.drop(columns=["result","gameid","date"], errors="ignore")
    y      = df_model_lanes["result"]
    groups = df_model_lanes["gameid"]

    gss = GroupShuffleSplit(test_size=0.05, n_splits=4, random_state=42)
    train_idx, _ = next(gss.split(x, y, groups))
    x_train = x.iloc[train_idx]
    y_train = y.iloc[train_idx]
    weights = x_train["weight"]
    x_train = x_train.drop(columns="weight")

    log(f"Training model on {len(x_train)} rows...")
    forest_mod = RandomForestClassifier(
        n_estimators=1200, criterion="gini", max_depth=3,
        min_samples_split=2, min_samples_leaf=1, max_features="sqrt",
        bootstrap=True, n_jobs=-1, random_state=42
    )
    forest_mod.fit(x_train, y_train, sample_weight=weights)

    log("Loading pro dataset...")
    dfPro = pd.read_csv(pro_csv)
    dfPro = dfPro[~dfPro["league"].isin(["LPL","DCup"])].reset_index(drop=True)
    cols  = ["patch","gameid","date","side","firstPick","position","champion",
             "pick1","pick2","pick3","pick4","pick5",
             "ban1","ban2","ban3","ban4","ban5","result"]
    dfPro = dfPro[[c for c in cols if c in dfPro.columns]].copy()

    lookup_pos = dfPro[dfPro["position"] != "team"].set_index(["gameid","champion"])["position"]
    team_mask  = dfPro["position"] == "team"
    for i in range(1, 6):
        col = f"pick{i}"
        if col in dfPro.columns:
            keys = list(zip(dfPro.loc[team_mask,"gameid"], dfPro.loc[team_mask, col]))
            dfPro.loc[team_mask, f"lane_{i}"] = [lookup_pos.get(k) for k in keys]

    team_rows = dfPro[dfPro["position"] == "team"].copy()
    team_rows["lane_pick_map"] = team_rows.apply(
        lambda row: {row[f"lane_{i}"]: i for i in range(1,6)
                     if f"lane_{i}" in row.index and pd.notna(row.get(f"lane_{i}"))}, axis=1
    )
    pick_lookup = team_rows.set_index(["gameid","side"])["lane_pick_map"]

    pl = dfPro[dfPro["position"] != "team"].copy()

    def gpn(row):
        try:
            return pick_lookup[(row["gameid"], row["side"])].get(row["position"], 99)
        except KeyError:
            return 99

    def gepn(row):
        try:
            es = "Red" if row["side"] == "Blue" else "Blue"
            return pick_lookup[(row["gameid"], es)].get(row["position"], 99)
        except KeyError:
            return 99

    pl["pick_number"]       = pl.apply(gpn, axis=1)
    pl["enemy_pick_number"] = pl.apply(gepn, axis=1)
    pl["is_blind"]          = pl["pick_number"] < pl["enemy_pick_number"]
    players = pl

    _initialized = True
    log("✓ Ready!")


# LCU 

def read_lockfile(path: str):
    with open(path, "r") as f:
        parts = f.read().split(":")
    return parts[2], parts[3]


def fetch_session(port, password):
    auth    = base64.b64encode(f"riot:{password}".encode()).decode()
    url     = f"https://127.0.0.1:{port}/lol-champ-select/v1/session"
    headers = {"Authorization": f"Basic {auth}"}
    resp    = http_insecure.request("GET", url, headers=headers)
    return resp.json()


def fetch_patch(port, password):
    url  = f"https://127.0.0.1:{port}/lol-patch/v1/game-version"
    resp = requests.get(url, auth=("riot", password), verify=False)
    return float(".".join(resp.json().split(".")[:2]))


# role inference

def _build_prob_lookup():
    rc = (prob_df.groupby(["champion","position"]).size()
          .unstack(fill_value=0).reindex(columns=roles, fill_value=0))
    rp = rc.div(rc.sum(axis=1), axis=0)
    return rc, rp.to_dict(orient="index")


def _get_tag_prior(tags):
    matching = [role_tags[t] for t in tags if t in role_tags]
    if not matching:
        return {r: 1/len(roles) for r in roles}
    blended = {r: np.mean([m[r] for m in matching]) for r in roles}
    total   = sum(blended.values())
    return {r: v/total for r, v in blended.items()}


def _blend_probs(champ, tags, role_counts, prob_lookup):
    prior  = _get_tag_prior(tags)
    if champ not in role_counts.index:
        return prior
    n      = role_counts.loc[champ].sum()
    weight = min(n / min_games, 1)
    dp     = prob_lookup.get(champ, {r: 0 for r in roles})
    blended = {r: weight * dp.get(r,0) + (1-weight)*prior[r] for r in roles}
    total   = sum(blended.values())
    return {r: v/total for r, v in blended.items()}


def assign_enemy_roles(picks_dict, your_team_id, role_counts, prob_lookup):
    norm = {"bottom":"bot","utility":"sup","middle":"mid","jungle":"jng"}
    for d in picks_dict.values():
        d["lane"] = norm.get(d["lane"], d["lane"])

    enemy_unknown = [(pid, d) for pid, d in picks_dict.items()
                     if d["team"] != your_team_id and d["lane"] == ""]
    if not enemy_unknown:
        return picks_dict

    enemy_taken = {d["lane"] for d in picks_dict.values()
                   if d["team"] != your_team_id and d["lane"] != ""}
    remaining   = [r for r in roles if r not in enemy_taken]

    prob_matrix = []
    for _, d in enemy_unknown:
        probs = _blend_probs(d["champ"], d["tags"], role_counts, prob_lookup)
        prob_matrix.append([probs[r] for r in remaining])

    prob_matrix          = np.array(prob_matrix)
    row_ind, col_ind     = linear_sum_assignment(1 - prob_matrix)
    for r, c in zip(row_ind, col_ind):
        picks_dict[enemy_unknown[r][0]]["lane"] = remaining[c]
    return picks_dict


# parse LCU session

def parse_session(data, port, password):

    norm       = {"bottom":"bot","utility":"sup","middle":"mid","jungle":"jng"}
    my_team_id = data["myTeam"][0]["team"]
    my_side    = "Blue" if my_team_id == 100 else "Red"
    opp_side   = "Red"  if my_side == "Blue" else "Blue"


    player_lookup = {}
    for team_key in ["myTeam","theirTeam"]:
        for player in data[team_key]:
            cid = player.get("championId", 0)
            if cid and cid != 0:
                lane = norm.get(player.get("assignedPosition",""),
                                player.get("assignedPosition",""))
                player_lookup[cid] = {"lane": lane, "team": player["team"]}

    draft_picks = {}
    bans_by_side = {"Blue": [], "Red": []}

    for action_group in data.get("actions", []):
        for action in action_group:
            atype     = action.get("type","")
            cid       = action.get("championId", 0)
            completed = action.get("completed", False)
            cell_id   = action.get("actorCellId", 0)

            if atype == "ban" and completed and cid and cid > 0:
                name     = id_to_name.get(cid)
                ban_side = "Blue" if cell_id < 5 else "Red"
                if name:
                    bans_by_side[ban_side].append(name)

            elif atype == "pick" and cid and cid > 0:
                info = player_lookup.get(cid)
                if not info:
                    continue
                champ_name = id_to_name.get(cid)
                if not champ_name:
                    continue
                draft_picks[f"pick_{cid}"] = {
                    "champ": champ_name,
                    "lane":  info["lane"],
                    "team":  info["team"],
                    "tags":  name_data_keyed.get(champ_name, {}).get("tags", [])
                }

    role_counts, prob_lookup = _build_prob_lookup()
    draft_picks = assign_enemy_roles(draft_picks, my_team_id, role_counts, prob_lookup)

    patch = fetch_patch(port, password)

    draft = {
        "team1": {
            "patch": patch, "side": my_side,  "firstPick": 1,
            "Picks": {r: None for r in roles},
            "Bans":  (bans_by_side[my_side]  + [None]*5)[:5]
        },
        "team2": {
            "patch": patch, "side": opp_side, "firstPick": 0,
            "Picks": {r: None for r in roles},
            "Bans":  (bans_by_side[opp_side] + [None]*5)[:5]
        }
    }

    for pick_data in draft_picks.values():
        lane     = pick_data["lane"]
        team_key = "team1" if pick_data["team"] == my_team_id else "team2"
        if lane in roles:
            draft[team_key]["Picks"][lane] = pick_data["champ"]

    return draft


# model

def _scale(x):
    return (x - 0.48) / (0.52 - 0.48) * 100


def convert(team1, team2):
    def make_row(t, opp):
        row = {"patch": t["patch"], "side": t["side"], "firstPick": t["firstPick"]}
        for role, champ in t["Picks"].items():
            if champ:
                row[f"pick_{champ}_{role}"] = 1
        for role, champ in opp["Picks"].items():
            if champ:
                row[f"pick_{champ}_{role}"] = -1
        for champ in (t["Bans"] + opp["Bans"]):
            if champ:
                row[f"ban_{champ}"] = 1
        return row

    df1      = pd.DataFrame([make_row(team1, team2)])
    df2      = pd.DataFrame([make_row(team2, team1)])
    df_input = pd.concat([df1, df2], ignore_index=True)
    base_cols = df_model_lanes.columns.drop(
        ["gameid","result","weight","date"], errors="ignore")
    df_input  = df_input.reindex(columns=base_cols, fill_value=0)
    df_input["side"] = df_input["side"].map({"Red": 0, "Blue": 1})
    return df_input


def evaluate_draft(draft):
    preds = forest_mod.predict_proba(convert(draft["team1"], draft["team2"]))[:, 1]
    return _scale(preds[0]), _scale(preds[1])

def get_recommendations(draft, top_n=10):
    bans        = [b for b in draft["team1"]["Bans"] + draft["team2"]["Bans"] if b]
    empty_roles = [r for r in roles if draft["team1"]["Picks"][r] is None]
    if not empty_roles:
        return pd.DataFrame(columns=["Champion","Role","Strength"])

    games_buffer  = (len(matches_df) ** 0.5) / 2
    diff_role_dict = {"sup": "bot", "bot": "sup"}


    winrates = {}
    for role in empty_roles:
        winrates[f"{role}_winrates"] = {}
        opp_pick = draft["team2"]["Picks"][role]

        if role in ["bot", "sup"]:
            partner_role  = diff_role_dict[role]
            partner_pick  = draft["team1"]["Picks"][partner_role]

            duo_opp       = opp_pick
            duo_partner   = partner_pick

            for champ in set(matches_df[role].unique()) - set(bans):
                if duo_opp and duo_partner:

                    counter_win   = len(matches_df[(matches_df[role] == champ) &
                                                    (matches_df[f"opp_{role}"] == duo_opp) &
                                                    (matches_df["result"] == 1)])
                    counter_total = len(matches_df[(matches_df[role] == champ) &
                                                    (matches_df[f"opp_{role}"] == duo_opp)])
                    synergy_win   = len(matches_df[(matches_df[role] == champ) &
                                                    (matches_df[partner_role] == duo_partner) &
                                                    (matches_df["result"] == 1)])
                    synergy_total = len(matches_df[(matches_df[role] == champ) &
                                                    (matches_df[partner_role] == duo_partner)])
                    counter_wr = (counter_win + games_buffer) / (counter_total + games_buffer * 2)
                    synergy_wr = (synergy_win + games_buffer) / (synergy_total + games_buffer * 2)
                    winrates[f"{role}_winrates"][champ] = (counter_wr + synergy_wr) / 2

                elif duo_opp or duo_partner:

                    has_synergy  = bool(duo_partner)
                    filled       = partner_role if has_synergy else f"opp_{role}"
                    filled_champ = duo_partner  if has_synergy else duo_opp
                    win_num   = len(matches_df[(matches_df[role] == champ) &
                                               (matches_df[filled] == filled_champ) &
                                               (matches_df["result"] == 1)])
                    total_games = len(matches_df[(matches_df[role] == champ) &
                                                  (matches_df[filled] == filled_champ)])
                    winrates[f"{role}_winrates"][champ] = (
                        (win_num + games_buffer) / (total_games + games_buffer * 2))

                else:

                    total = players[(players["position"] == role) &
                                    (players["is_blind"] == True)]["champion"].value_counts()
                    if champ in total:
                        winrates[f"{role}_winrates"][champ] = total[champ]

        elif opp_pick is None:

            total = (players[(players["position"] == role) &
                              (players["is_blind"] == True)]["champion"].value_counts())
            for champ in set(players[(players["position"] == role) &
                                      (players["is_blind"] == True)]["champion"].unique()) - set(bans):
                winrates[f"{role}_winrates"][champ] = total.get(champ, 0)

        else:

            for champ in set(matches_df[role].unique()) - set(bans):
                total_games = len(matches_df[(matches_df[role] == champ) &
                                              (matches_df[f"opp_{role}"] == opp_pick)])
                if total_games > 0:
                    win_num = len(matches_df[(matches_df[role] == champ) &
                                              (matches_df[f"opp_{role}"] == opp_pick) &
                                              (matches_df["result"] == 1)])
                    winrates[f"{role}_winrates"][champ] = (
                        (win_num + games_buffer) / (total_games + games_buffer * 2))


    results = []
    for role in empty_roles:
        role_wr   = winrates.get(f"{role}_winrates", {})
        candidates = sorted(role_wr, key=role_wr.get, reverse=True)[:top_n]

        for champ in candidates:
            dc = {
                "team1": {**draft["team1"],
                           "Picks": {**draft["team1"]["Picks"], role: champ}},
                "team2": draft["team2"]
            }
            X    = convert(dc["team1"], dc["team2"])
            X    = X.drop(columns=[c for c in X.columns if "None" in str(c)], errors="ignore")
            pred = forest_mod.predict_proba(X)[:, 1]
            results.append({
                "Champion": champ,
                "Role":     role,
                "Strength": round((pred[0] - pred[1]) * 100, 2)
            })

    return pd.DataFrame(results).sort_values("Strength", ascending=False)

