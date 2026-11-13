"""avaliacao.py — avaliação completa da previsão em todos os jogos do Worlds.

    python main.py avaliacao                 # gera resultados/acoes.csv e as tabelas de resumo
    python main.py avaliacao --liga WLDs MSI # outras ligas

Para cada ação de cada jogo (todos os times), o modelo é montado com os jogos até o dia
anterior e anotamos em que POSIÇÃO do ranking o campeão real ficou (1 = acertou em cheio).
Guardar a posição, e não só "acertou/errou", é o que permite achar padrões nos erros.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import argparse
import sqlite3
from collections import Counter

import pandas as pd

from caminhos import BANCO, RESULTADOS
from previsao.modelo import Modelo, estado_para_previsao

SAIDA = RESULTADOS
RANKING_MAX = 60      # até que posição procuramos o campeão real


def baseline_posicao(modelo, tipo, indisponiveis, real):
    pop = sum(modelo.meta_pick.values(), Counter()) if tipo == "pick" else modelo.meta_ban
    ranking = [c for c, _ in pop.most_common() if c not in indisponiveis]
    return ranking.index(real) + 1 if real in ranking else None


def avaliar(ligas):
    con = sqlite3.connect(BANCO)
    marcas = ",".join("?" * len(ligas))
    jogos = con.execute(f"""
        SELECT game_id, date_utc, series_id, game_number, blue_team, red_team, first_pick_team, winner
        FROM games WHERE league IN ({marcas}) ORDER BY date_utc""", ligas).fetchall()
    linhas, modelos = [], {}
    for game_id, data, serie, n_jogo, azul, verm, fp, vencedor in jogos:
        ate = data[:10] + " 00:00:00"
        if ate not in modelos:
            print(f"montando modelo até {ate[:10]}...")
            modelos[ate] = Modelo(ate=ate)
        modelo = modelos[ate]
        time_por_lado = {"blue": azul, "red": verm}
        lado_por_time = {azul: "blue", verm: "red"}
        fearless = [c for (c,) in con.execute(
            "SELECT champion FROM v_fearless_locked WHERE game_id = ?", (game_id,))]
        acoes = con.execute("""SELECT step, team, action_type, phase, team_order, champion
                               FROM draft_actions WHERE game_id = ? ORDER BY step""",
                            (game_id,)).fetchall()
        feitos = []
        for step, time, tipo, fase, ordem, real in acoes:
            lado = lado_por_time[time]
            if real:
                estado = estado_para_previsao(feitos, (lado, tipo, ordem), time_por_lado, fearless)
                ranking = modelo.prever(**estado, k=RANKING_MAX)
                nomes = [c for c, _, _ in ranking]
                pos = nomes.index(real) + 1 if real in nomes else None
                linhas.append({
                    "game_id": game_id, "data": data[:10], "serie": serie, "jogo_da_serie": n_jogo,
                    "time": time, "adversario": time_por_lado["red" if lado == "blue" else "blue"],
                    "lado": lado, "tem_first_pick": time == fp, "venceu": time == vencedor,
                    "passo": step, "fase": fase, "tipo": tipo, "ordem_no_time": ordem,
                    "real": real, "posicao": pos,
                    "prob_real": ranking[pos - 1][1] if pos else 0.0,
                    "top1": nomes[0], "prob_top1": ranking[0][1], "motivo_top1": ranking[0][2],
                    "top5": ", ".join(nomes[:5]),
                    "motivo_real": ranking[pos - 1][2] if pos else "",
                    "posicao_baseline": baseline_posicao(modelo, tipo, estado["indisponiveis"], real),
                    "fearless_bloqueados": len(fearless),
                })
            feitos.append((lado, tipo, real))
    return pd.DataFrame(linhas)


def taxas(df, por):
    """top1/top3/top5 (modelo e baseline) agrupado por `por`."""
    def resumo(g):
        p, b = g["posicao"], g["posicao_baseline"]
        return pd.Series({
            "acoes": len(g),
            "top1": (p == 1).mean(), "top3": (p <= 3).mean(), "top5": (p <= 5).mean(),
            "baseline_top5": (b <= 5).mean(),
            "posicao_mediana": p.fillna(RANKING_MAX + 1).median(),
        })
    return df.groupby(por).apply(resumo, include_groups=False).reset_index()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", nargs="+", default=["WLDs"])
    args = ap.parse_args()
    SAIDA.mkdir(parents=True, exist_ok=True)

    df = avaliar(args.liga)
    df.to_csv(SAIDA / "acoes.csv", index=False)
    print(f"\n{len(df)} ações avaliadas em {df['game_id'].nunique()} jogos")

    tabelas = {
        "por_tipo": taxas(df, ["tipo"]),
        "por_fase": taxas(df, ["fase", "tipo"]),
        "por_jogo_da_serie": taxas(df, ["jogo_da_serie", "tipo"]),
        "por_ordem": taxas(df, ["tipo", "ordem_no_time"]),
        "por_first_pick": taxas(df, ["tem_first_pick", "tipo"]),
        "por_time": taxas(df, ["time", "tipo"]),
    }
    for nome, t in tabelas.items():
        t.to_csv(SAIDA / f"{nome}.csv", index=False)
    pd.set_option("display.width", 160)
    print(tabelas["por_tipo"].round(3).to_string(index=False))
    print(tabelas["por_fase"].round(3).to_string(index=False))
    print(tabelas["por_jogo_da_serie"].round(3).to_string(index=False))


if __name__ == "__main__":
    main()
