"""Gera os recortes do CSV do Oracle's Elixir em dados/csvs/ (entrada do load.py)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import pandas as pd

from caminhos import CSVS, csv_oracles_elixir

ARQUIVO = csv_oracles_elixir()
SAIDA = CSVS
SAIDA.mkdir(parents=True, exist_ok=True)

TIMES = ["Gen.G", "Bilibili Gaming"]
WORLDS = "WLDs"

COLUNAS = [
    "gameid", "datacompleteness", "league", "split", "playoffs", "date", "game",
    "patch", "side", "position", "playername", "teamname", "champion",
    "ban1", "ban2", "ban3", "ban4", "ban5",
    "pick1", "pick2", "pick3", "pick4", "pick5",
    "firstPick", "result", "gamelength", "golddiffat15", "firstblood", "firstdragon",
]

df = pd.read_csv(ARQUIVO, dtype={"patch": str}, low_memory=False)
print(f"{len(df)} linhas, {df['gameid'].nunique()} jogos")

print(sorted(n for n in df["teamname"].dropna().unique() if "Gen" in n or "Bilibili" in n))
print(sorted(df["league"].dropna().unique()))

faltando = [c for c in COLUNAS if c not in df.columns]
if faltando:
    print("Colunas não encontradas:", faltando)
df = df[[c for c in COLUNAS if c in df.columns]]

# Jogos completos da GEN e da BLG (inclui as linhas do adversário)
jogos = df.loc[df["teamname"].isin(TIMES), "gameid"].unique()
gen_blg = df[df["gameid"].isin(jogos)]

worlds_gen_blg = gen_blg[gen_blg["league"] == WORLDS]
worlds_todos = df[df["league"] == WORLDS]

gen_blg.to_csv(SAIDA / "gen_blg.csv", index=False)
worlds_gen_blg.to_csv(SAIDA / "worlds_gen_blg.csv", index=False)
worlds_todos.to_csv(SAIDA / "worlds_todos.csv", index=False)

# Picks de todos os jogos de 2026: base das sinergias e counters
todos_picks = df[df["position"].isin(["top", "jng", "mid", "bot", "sup"])][
    ["gameid", "date", "league", "side", "teamname", "position", "champion", "result",
     "playername"]].copy()
# Ordem do pick dentro do time (1..5), tirada das colunas pick1..pick5 das linhas de time
linhas_time = df[df["position"] == "team"]
ordem = {}
for r in linhas_time.itertuples():
    for n in range(1, 6):
        ordem[(r.gameid, r.side, getattr(r, f"pick{n}"))] = n
todos_picks["team_order"] = [ordem.get((g, s, c)) for g, s, c in
                             zip(todos_picks["gameid"], todos_picks["side"], todos_picks["champion"])]
todos_picks.to_csv(SAIDA / "todos_picks.csv", index=False)

# Bans de todos os jogos de 2026, um por linha (formato longo)
bans = []
for r in linhas_time.itertuples():
    for n in range(1, 6):
        campeao = getattr(r, f"ban{n}")
        if isinstance(campeao, str) and campeao:
            bans.append({"gameid": r.gameid, "date": r.date, "league": r.league, "side": r.side,
                         "teamname": r.teamname, "team_order": n, "champion": campeao})
todos_bans = pd.DataFrame(bans)
todos_bans.to_csv(SAIDA / "todos_bans.csv", index=False)
print(f"todos_bans: {todos_bans['gameid'].nunique()} jogos, {len(todos_bans)} bans")
print(f"todos_picks: {todos_picks['gameid'].nunique()} jogos, {len(todos_picks)} linhas")

for nome, d in [("gen_blg", gen_blg), ("worlds_gen_blg", worlds_gen_blg), ("worlds_todos", worlds_todos)]:
    print(f"{nome}: {d['gameid'].nunique()} jogos, {len(d)} linhas")

# Conferência: jogos da GEN e da BLG no Worlds, em ordem de data
times_worlds = worlds_gen_blg[worlds_gen_blg["position"] == "team"]

print(times_worlds[times_worlds["teamname"].isin(TIMES)].groupby("teamname")["gameid"].nunique())

print(times_worlds[times_worlds["teamname"].isin(TIMES)]
      [["date", "game", "teamname", "side", "firstPick", "result"]]
      .sort_values("date").to_string())

# Dados completos x parciais por liga (a LPL costuma vir parcial)
times_todos = gen_blg[(gen_blg["position"] == "team") & gen_blg["teamname"].isin(TIMES)]
print(times_todos.groupby(["teamname", "league", "datacompleteness"])["gameid"].nunique())
