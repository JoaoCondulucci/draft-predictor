"""tendencias.py — tendências de draft de um torneio (padrão: Worlds), direto do draft.db.

    python main.py tendencias            # gera resultados/tend_*.csv
    python main.py tendencias --liga MSI

Tabelas:
  presenca     pick/ban de cada campeão (% dos jogos), winrate e em que fase é banido
  duplas       campeões do mesmo time que aparecem juntos mais do que o acaso (lift)
  rotas        que rota cada time pega no 1º, 2º... pick
  first_pick   quando o time fica com o first pick e quanto vence com e sem ele
  fearless     campeões que os times "gastam" no jogo 1 x guardam para depois
  bans_time    o que cada time mais bane, separado por fase
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import argparse
import itertools
import sqlite3
from collections import Counter

import pandas as pd

from caminhos import BANCO, RESULTADOS

SAIDA = RESULTADOS


def carregar(con, ligas):
    marcas = ",".join("?" * len(ligas))
    jogos = pd.read_sql_query(f"SELECT * FROM games WHERE league IN ({marcas})", con, params=ligas)
    ids = tuple(jogos["game_id"])
    marcas_ids = ",".join("?" * len(ids))
    acoes = pd.read_sql_query(
        f"SELECT * FROM draft_actions WHERE game_id IN ({marcas_ids})", con, params=ids)
    jogadores = pd.read_sql_query(
        f"SELECT * FROM player_games WHERE game_id IN ({marcas_ids})", con, params=ids)
    return jogos, acoes, jogadores


def presenca(jogos, acoes, jogadores):
    n = len(jogos)
    picks = acoes[acoes.action_type == "pick"].groupby("champion").size()
    bans = acoes[acoes.action_type == "ban"].groupby("champion").size()
    bans1 = acoes[acoes.phase == "ban1"].groupby("champion").size()
    bans2 = acoes[acoes.phase == "ban2"].groupby("champion").size()
    vitorias = jogadores.groupby("champion")["win"].sum()
    rota = jogadores.groupby("champion")["role"].agg(lambda s: s.value_counts().index[0])
    t = pd.DataFrame({"picks": picks, "bans": bans, "bans_1a_fase": bans1, "bans_2a_fase": bans2,
                      "vitorias": vitorias, "rota_principal": rota}).fillna(0)
    for c in ["picks", "bans", "bans_1a_fase", "bans_2a_fase", "vitorias"]:
        t[c] = t[c].astype(int)
    t["presenca"] = (t["picks"] + t["bans"]) / n
    t["winrate"] = (t["vitorias"] / t["picks"]).where(t["picks"] > 0)
    t["rota_principal"] = t["rota_principal"].replace(0, "")
    t.index.name = "campeao"
    return t.sort_values("presenca", ascending=False).reset_index()


def duplas(jogadores, minimo=4):
    times = jogadores.groupby(["game_id", "team"])
    n_time, n_par = Counter(), Counter()
    rotas = {}
    for _, g in times:
        campeoes = sorted(set(g["champion"]))
        n_time.update(campeoes)
        for a, b in itertools.combinations(campeoes, 2):
            n_par[(a, b)] += 1
        rotas.update(dict(zip(g["champion"], g["role"])))
    N = times.ngroups
    linhas = []
    for (a, b), k in n_par.items():
        if k >= minimo:
            esperado = n_time[a] * n_time[b] / N
            linhas.append({"campeao_a": a, "rota_a": rotas.get(a), "campeao_b": b,
                           "rota_b": rotas.get(b), "jogos_juntos": k,
                           "lift": k / esperado if esperado else None})
    return pd.DataFrame(linhas).sort_values(["lift", "jogos_juntos"], ascending=False)


def rotas_por_time(acoes, jogadores):
    picks = acoes[acoes.action_type == "pick"].merge(
        jogadores[["game_id", "team", "champion", "role"]], on=["game_id", "team", "champion"])
    t = (picks.groupby(["team", "team_order", "role"]).size().unstack("role", fill_value=0))
    t = t.reindex(columns=["top", "jng", "mid", "bot", "sup"], fill_value=0)
    t = t.div(t.sum(axis=1), axis=0).reset_index()
    return t.rename(columns={"team": "time", "team_order": "pick_do_time"})


def first_pick(jogos):
    linhas = []
    for time in sorted(set(jogos.blue_team) | set(jogos.red_team)):
        j = jogos[(jogos.blue_team == time) | (jogos.red_team == time)]
        com_fp = j[j.first_pick_team == time]
        sem_fp = j[j.first_pick_team != time]
        azul = j[j.blue_team == time]
        linhas.append({
            "time": time, "jogos": len(j),
            "pct_com_first_pick": len(com_fp) / len(j),
            "pct_lado_azul": len(azul) / len(j),
            "pct_azul_e_first_pick": len(azul[azul.first_pick_team == time]) / len(j),
            "winrate_com_fp": (com_fp.winner == time).mean() if len(com_fp) else None,
            "winrate_sem_fp": (sem_fp.winner == time).mean() if len(sem_fp) else None,
        })
    return pd.DataFrame(linhas).sort_values("jogos", ascending=False)


def fearless(jogos, acoes):
    """Em que jogo da série cada campeão costuma ser escolhido (só séries de 2+ jogos)."""
    multi = jogos.groupby("series_id").filter(lambda s: len(s) >= 2)
    picks = acoes[acoes.action_type == "pick"].merge(
        multi[["game_id", "game_number"]], on="game_id")
    t = picks.groupby("champion")["game_number"].agg(["count", "mean"])
    t["pct_no_jogo_1"] = picks[picks.game_number == 1].groupby("champion").size() / t["count"]
    t = t[t["count"] >= 4].fillna(0).sort_values("mean")
    return t.reset_index().rename(columns={"champion": "campeao", "count": "picks_em_series",
                                           "mean": "jogo_medio_da_serie"})


def bans_por_time(acoes):
    b = acoes[acoes.action_type == "ban"].dropna(subset=["champion"])
    t = b.groupby(["team", "phase", "champion"]).size().reset_index(name="vezes")
    t = t.sort_values(["team", "phase", "vezes"], ascending=[True, True, False])
    return t.groupby(["team", "phase"]).head(8).rename(columns={"team": "time", "phase": "fase",
                                                                "champion": "campeao"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", nargs="+", default=["WLDs"])
    args = ap.parse_args()
    SAIDA.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(BANCO)
    jogos, acoes, jogadores = carregar(con, args.liga)
    tabelas = {
        "presenca": presenca(jogos, acoes, jogadores),
        "duplas": duplas(jogadores),
        "rotas": rotas_por_time(acoes, jogadores),
        "first_pick": first_pick(jogos),
        "fearless": fearless(jogos, acoes),
        "bans_time": bans_por_time(acoes),
    }
    for nome, t in tabelas.items():
        t.to_csv(SAIDA / f"tend_{nome}.csv", index=False)
        print(f"tend_{nome}.csv: {len(t)} linhas")
    return tabelas


if __name__ == "__main__":
    main()
