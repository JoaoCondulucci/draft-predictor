"""backtest.py — mede o quanto a previsão acerta em jogos que já aconteceram.

    python main.py backtest                   # jogos da GEN e da BLG no Worlds
    python main.py backtest --liga LCK LPL    # outras ligas

Para cada jogo, o modelo é montado SÓ com jogos anteriores a ele (sem "espiar o futuro").
Em cada ação do time (pick ou ban), anotamos em que posição do ranking o campeão real ficou.
Comparamos com um baseline burro: "o campeão mais popular ainda disponível".
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import argparse
import sqlite3
from collections import Counter, defaultdict

from caminhos import BANCO
from previsao.modelo import Modelo, estado_para_previsao

TIMES = ["Gen.G", "Bilibili Gaming"]


def baseline(modelo, tipo, indisponiveis, k=5):
    """Mais popular no Worlds até ali (picks por rota somados, ou bans)."""
    if tipo == "pick":
        pop = sum(modelo.meta_pick.values(), Counter())
    else:
        pop = modelo.meta_ban
    ranking = [c for c, _ in pop.most_common() if c not in indisponiveis]
    return ranking[:k]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--liga", nargs="+", default=["WLDs"])
    ap.add_argument("--todos-os-times", action="store_true",
                    help="avalia as ações de TODOS os times (não só GEN/BLG); o modelo é montado "
                         "uma vez por dia, com os jogos até o dia anterior (mais rápido)")
    args = ap.parse_args()

    con = sqlite3.connect(BANCO)
    marcas = ",".join("?" * len(args.liga))
    if args.todos_os_times:
        jogos = con.execute(f"""SELECT game_id, date_utc, blue_team, red_team FROM games
                                WHERE league IN ({marcas}) ORDER BY date_utc""", args.liga).fetchall()
    else:
        jogos = con.execute(f"""
            SELECT game_id, date_utc, blue_team, red_team FROM games
            WHERE league IN ({marcas}) AND (blue_team IN (?, ?) OR red_team IN (?, ?))
            ORDER BY date_utc""", (*args.liga, *TIMES, *TIMES)).fetchall()
    avaliar = (lambda time: True) if args.todos_os_times else (lambda time: time in TIMES)

    resultado = defaultdict(lambda: {"n": 0, "top1": 0, "top3": 0, "top5": 0, "base5": 0})
    modelos = {}
    for game_id, data, azul, vermelho in jogos:
        ate = data[:10] + " 00:00:00" if args.todos_os_times else data
        if ate not in modelos:
            modelos[ate] = Modelo(ate=ate)
        modelo = modelos[ate]
        time_por_lado = {"blue": azul, "red": vermelho}
        lado_por_time = {azul: "blue", vermelho: "red"}
        fearless = [c for (c,) in con.execute(
            "SELECT champion FROM v_fearless_locked WHERE game_id = ?", (game_id,))]
        acoes = con.execute("""SELECT step, team, action_type, team_order, champion
                               FROM draft_actions WHERE game_id = ? ORDER BY step""",
                            (game_id,)).fetchall()
        feitos = []
        for step, time, tipo, ordem, campeao in acoes:
            lado = lado_por_time[time]
            if avaliar(time) and campeao:
                estado = estado_para_previsao(feitos, (lado, tipo, ordem), time_por_lado, fearless)
                top = [c for c, _, _ in modelo.prever(**estado, k=5)]
                base = baseline(modelo, tipo, estado["indisponiveis"])
                for chave in (f"{time} {tipo}", f"TOTAL {tipo}"):
                    r = resultado[chave]
                    r["n"] += 1
                    r["top1"] += campeao in top[:1]
                    r["top3"] += campeao in top[:3]
                    r["top5"] += campeao in top[:5]
                    r["base5"] += campeao in base
            feitos.append((lado, tipo, campeao))

    print(f"{len(jogos)} jogos ({', '.join(args.liga)})\n")
    print(f"{'':24} {'ações':>6} {'top1':>6} {'top3':>6} {'top5':>6}   {'baseline top5':>13}")
    for chave in sorted(resultado):
        r = resultado[chave]
        pct = lambda x: f"{x / r['n']:6.0%}"
        print(f"{chave:24} {r['n']:6d} {pct(r['top1'])} {pct(r['top3'])} {pct(r['top5'])}   {pct(r['base5']):>13}")


if __name__ == "__main__":
    main()
