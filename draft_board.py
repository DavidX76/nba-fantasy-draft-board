"""
Fantasy basketball draft board
------------------------------
Reads two CSV files that sit in the same folder as this script:
  1. data-gV9DK.csv                                  (projected stats per player)
  2. FantasyPros_2026_Overall_NBA_ADP_Rankings.csv   (ADP = average draft position)

and writes two files back to that same folder:
  - rankings.csv   every player, every stat, ADP, and value gap
  - RESULTS.md     steals/busts tables and the full ranking (README.md is yours to write by hand)

Run it with:  python draft_board.py
Needs:        pip install pandas
"""

import re
import unicodedata
from pathlib import Path

import pandas as pd

# Everything is read from / written to the folder this script lives in.
HERE = Path(__file__).parent
PROJECTIONS_FILE = HERE / "data-gV9DK.csv"
ADP_FILE = HERE / "FantasyPros_2026_Overall_NBA_ADP_Rankings.csv"


# ---------------------------------------------------------------------------
# Step 1: make player names comparable between the two files
# ---------------------------------------------------------------------------
# The files spell some names differently ("Jr." vs "Jr", accents, "Alex" vs
# "Alexandre"). We reduce each name to a simple lowercase "key" so they match.
ALIASES = {  # real spelling differences that cleaning alone can't fix
    "alexandre sarr": "alex sarr",
    "nicolas claxton": "nic claxton",
    "cam johnson": "cameron johnson",
}


def name_key(name):
    name = unicodedata.normalize("NFKD", str(name)).encode("ascii", "ignore").decode()
    name = name.lower().replace(".", "").replace("'", "").replace("-", " ")
    name = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", name)  # drop suffixes
    name = re.sub(r"\s+", " ", name).strip()
    return ALIASES.get(name, name)


# ---------------------------------------------------------------------------
# Step 2: load the data
# ---------------------------------------------------------------------------
proj = pd.read_csv(PROJECTIONS_FILE, encoding="utf-8-sig")  # utf-8-sig strips a hidden BOM
proj.columns = [c.strip() for c in proj.columns]

adp = pd.read_csv(ADP_FILE, encoding="utf-8-sig").dropna(subset=["Player"])  # file ends with blank rows
# Positions come with injury tags like "C,PF OUT"; remove the tags.
adp["Positions"] = adp["Positions"].str.replace(
    r"\s+(DTD|OUT|INJ|FA|RET|NWT|G-League)\b", "", regex=True
).str.strip()


# ---------------------------------------------------------------------------
# Step 3: score each player
# ---------------------------------------------------------------------------
# Every stat is worth 1 point and turnovers cost 1 point. The file has no
# FGM/FGA/FTM/FTA columns, so the shooting terms of the full formula are
# NOT included. This is a partial version of the requested scoring.
proj["per_game"] = (
    proj.PTS + proj.REB + proj.AST + proj.STL + proj.BLK + proj["3PT"] - proj.TO
).round(2)

# Season value = points per game x projected games played (so injury risk counts).
proj["season"] = (proj.per_game * proj.GP).round(0).astype(int)


# ---------------------------------------------------------------------------
# Step 4: attach ADP
# ---------------------------------------------------------------------------
proj["key"] = proj.PLAYER.map(name_key)
adp["key"] = adp.Player.map(name_key)

m = proj.merge(adp[["key", "Team", "Positions", "ESPN", "Yahoo"]], on="key", how="left")

# Prefer ESPN's ADP. If ESPN has no value, fall back to Yahoo and mark it.
m["adp"] = m.ESPN.fillna(m.Yahoo)
m["adp_src"] = ""
m.loc[m.ESPN.notna(), "adp_src"] = "ESPN"
m.loc[m.ESPN.isna() & m.Yahoo.notna(), "adp_src"] = "Yahoo*"

# Final ranking order = highest projected season score first.
m = m.sort_values("season", ascending=False).reset_index(drop=True)
m["proj_rank"] = m.index + 1


# ---------------------------------------------------------------------------
# Step 5: find steals and busts
# ---------------------------------------------------------------------------
# Only players that have an ADP can be compared. Within that group we rank
# everyone twice (by projected season score, and by ADP) and subtract.
#   gap = ADP rank - projected rank
#   positive -> projected better than where he's drafted  (steal)
#   negative -> projected worse than where he's drafted   (bust)
pool = m[m.adp.notna()].copy()
pool["proj_rank_pool"] = pool.season.rank(ascending=False, method="first").astype(int)
pool["adp_rank_pool"] = pool.adp.rank(method="first").astype(int)
pool["gap"] = pool.adp_rank_pool - pool.proj_rank_pool
m = m.merge(pool[["PLAYER", "proj_rank_pool", "adp_rank_pool", "gap"]], on="PLAYER", how="left")

out = m[[
    "proj_rank", "PLAYER", "Team", "Positions", "GP", "PTS", "REB", "AST", "STL", "BLK",
    "3PT", "TO", "per_game", "season", "adp", "adp_src", "adp_rank_pool", "proj_rank_pool", "gap",
]]
out.columns = [
    "Rank", "Player", "Team", "Pos", "GP", "PTS", "REB", "AST", "STL", "BLK",
    "3PM", "TO", "Score/G", "Season Score", "ADP", "ADP Source", "ADP Rank", "Proj Rank", "Value Gap",
]
out.to_csv(HERE / "rankings.csv", index=False)


# ---------------------------------------------------------------------------
# Step 6: write the README that GitHub displays
# ---------------------------------------------------------------------------
def md_table(df, columns, headers):
    """Turn a dataframe into a markdown table. `columns` are functions: row -> text."""
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for _, row in df.iterrows():
        lines.append("| " + " | ".join(str(f(row)) for f in columns) + " |")
    return "\n".join(lines)


def adp_text(r):
    if pd.isna(r["ADP"]):
        return "—"
    return f"{r['ADP']:.0f}{'*' if r['ADP Source'] == 'Yahoo*' else ''}"


def gap_text(r):
    return "—" if pd.isna(r["Value Gap"]) else f"{r['Value Gap']:+.0f}"


full_table = md_table(
    out,
    [lambda r: r["Rank"], lambda r: r["Player"], lambda r: r["Team"] if pd.notna(r["Team"]) else "—",
     lambda r: r["GP"], lambda r: f"{r['Score/G']:.1f}", lambda r: f"{r['Season Score']:.0f}",
     adp_text, gap_text],
    ["#", "Player", "Team", "GP", "Score/G", "Season", "ADP", "Gap"],
)

gap_cols = [lambda r: r["Player"], lambda r: r["GP"], lambda r: f"{r['Season Score']:.0f}", adp_text,
            lambda r: f"{r['ADP Rank']:.0f}", lambda r: f"{r['Proj Rank']:.0f}", gap_text]
gap_heads = ["Player", "GP", "Season", "ADP", "ADP rank", "Proj rank", "Gap"]

comparable = out.dropna(subset=["Value Gap"])
steals = md_table(comparable.sort_values("Value Gap", ascending=False).head(15), gap_cols, gap_heads)
busts = md_table(comparable.sort_values("Value Gap").head(15), gap_cols, gap_heads)
no_adp = int(out["ADP"].isna().sum())

readme = f"""# 2026 Fantasy Basketball Draft Board

Ranks players by projected season value and compares that to ESPN average draft position (ADP) to find steals and busts.

## How scores are calculated

**This is a partial version of the requested scoring.** The projections file has no FGM, FGA, FTM or FTA columns, so the shooting-efficiency terms could not be included.

`Score/G = PTS + REB + AST + STL + BLK + 3PM − TO` (each worth 1 point, per game)

`Season = Score/G × projected games played`, which is the ranking order. Injury-prone players drop because they miss games.

Because FGA and FTA (−1 each) are left out, **high-volume, low-efficiency scorers are overrated here and efficient scorers are underrated.** Treat this as an approximation until the shooting columns are available.

## ADP and the Gap column

- **ADP** is ESPN ADP from the FantasyPros file. A `*` means ESPN had no value, so Yahoo ADP was used instead.
- **Gap** is ADP rank minus projected rank, with both ranked within the same pool of players that have an ADP. **Positive = steal** (projected better than drafted), **negative = bust**.
- {no_adp} players in the projections have no ADP in the FantasyPros file, so they are ranked below but excluded from steals/busts.
- Players with very low GP (e.g. Mark Williams at 5, Jimmy Butler at 18) show up as busts because of expected missed games, not per-game production. Check the GP column.

## Draft steals (projected much better than ADP)

{steals}

## Draft busts (projected much worse than ADP)

{busts}

## Full ranking

{full_table}

---
Data: `rankings.csv` has every column, including the individual stat projections.
Code: `draft_board.py` regenerates this file and `rankings.csv` from the two input CSVs.
Note: this file is auto-generated, so edits made here are lost the next time the script runs.
"""
# Written to RESULTS.md (not README.md) so a hand-written README is never overwritten.
(HERE / "RESULTS.md").write_text(readme, encoding="utf-8")

print(f"Done: {len(out)} players ranked, {no_adp} without ADP. Wrote rankings.csv and RESULTS.md")
