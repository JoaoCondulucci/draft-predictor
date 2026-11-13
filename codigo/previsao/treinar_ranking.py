"""Treina o ranking aprendido (LightGBM) de picks e bans com os jogos do Worlds.

    python main.py ranking

1. Para cada ação de cada jogo, todos os campeões disponíveis viram candidatos com features
   calculadas só com jogos ANTERIORES ao dia do jogo (sem vazamento).
2. Teste para frente: em cada bloco de datas, treina só com os blocos anteriores e compara
   com o modelo de contagem nas mesmas ações. É o número honesto para divulgar.
3. Ajusta a temperatura do softmax para o % mostrado ficar perto da taxa real de acerto.
4. Treina os modelos finais com todos os jogos e salva em dados/modelos/.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import json
import sqlite3
import time

import lightgbm as lgb
import numpy as np
import pandas as pd

from caminhos import BANCO
from previsao.features import Estatisticas, features_ban, features_pick
from previsao.modelo import Modelo, estado_para_previsao
from previsao.ranking import MODELOS

LIGAS = ("WLDs",)
NAO_FEATURES = {"campeao", "acao", "game_id", "data", "tipo", "alvo"}
PARAMS = dict(objective="lambdarank", metric="ndcg", ndcg_eval_at=[1, 3, 5], learning_rate=0.05,
              num_leaves=15, min_data_in_leaf=40, feature_fraction=0.8, bagging_fraction=0.8,
              bagging_freq=1, lambda_l2=1.0, verbose=-1, seed=7)
RODADAS = 300
CORTES = (0.4, 0.55, 0.7, 0.85)   # blocos do teste para frente (fração acumulada das ações)


def montar_base():
    con = sqlite3.connect(BANCO)
    est_todas = Estatisticas(con)
    marcas = ",".join("?" * len(LIGAS))
    jogos = con.execute(f"""SELECT game_id, date_utc, blue_team, red_team FROM games
                            WHERE league IN ({marcas}) ORDER BY date_utc""", LIGAS).fetchall()
    modelos, linhas, n_acao = {}, [], 0
    for game_id, data, azul, verm in jogos:
        ate = data[:10] + " 00:00:00"
        if ate not in modelos:
            print(f"  modelo até {ate[:10]}...")
            modelos[ate] = Modelo(ate=ate)
        m, est = modelos[ate], est_todas.ate(ate)
        time_por_lado = {"blue": azul, "red": verm}
        lado_por_time = {azul: "blue", verm: "red"}
        fearless = [c for (c,) in con.execute(
            "SELECT champion FROM v_fearless_locked WHERE game_id = ?", (game_id,))]
        feitos = []
        for time_, tipo, ordem, real in con.execute("""SELECT team, action_type, team_order, champion
                                                       FROM draft_actions WHERE game_id = ? ORDER BY step""",
                                                    (game_id,)):
            lado = lado_por_time[time_]
            if real:
                e = estado_para_previsao(feitos, (lado, tipo, ordem), time_por_lado, fearless)
                candidatos = m.campeoes - set(e["indisponiveis"])
                if real in candidatos:
                    f = features_pick if tipo == "pick" else features_ban
                    for linha in f(m, est, e["time"], e["adversario"], ordem, e["picks_time"],
                                   e["picks_adv"], candidatos, {"ordem": ordem}):
                        linha.update(acao=n_acao, game_id=game_id, data=data[:10], tipo=tipo,
                                     alvo=int(linha["campeao"] == real))
                        linhas.append(linha)
                    n_acao += 1
            feitos.append((lado, tipo, real))
    con.close()
    return pd.DataFrame(linhas)


def treinar(df, feats):
    df = df.sort_values("acao")
    grupos = df.groupby("acao", sort=True).size().values
    return lgb.train(PARAMS, lgb.Dataset(df[feats], df["alvo"], group=grupos), num_boost_round=RODADAS)


def taxas(df, col):
    r = df.groupby("acao")[col].rank(ascending=False, method="first")
    acertou = r[df.alvo == 1]
    return [(acertou <= k).mean() for k in (1, 3, 5)]


def melhor_temperatura(df, col):
    """Temperatura do softmax que minimiza o erro (log-loss) na probabilidade do campeão real."""
    melhor, menor = 1.0, float("inf")
    for t in np.geomspace(0.1, 10, 80):
        s = df[col] / t
        log_soma = s.groupby(df.acao).transform(lambda v: np.log(np.exp(v - v.max()).sum()) + v.max())
        perda = -(s - log_soma)[df.alvo == 1].mean()
        if perda < menor:
            melhor, menor = t, perda
    return float(melhor)


def main():
    t0 = time.time()
    print("Montando a base (features sem vazamento)...")
    base = montar_base()
    MODELOS.mkdir(parents=True, exist_ok=True)
    meta = {"features": {}, "temperatura": {}, "teste_para_frente": {}}
    acumulado = base[base.alvo == 1].groupby("data").size().cumsum() / (base.alvo == 1).sum()
    cortes = [acumulado[acumulado >= q].index[0] for q in CORTES] + ["9999"]
    for tipo in ("pick", "ban"):
        df = base[base.tipo == tipo].reset_index(drop=True)
        feats = [c for c in df.columns if c not in NAO_FEATURES and df[c].notna().any()]
        df[feats] = df[feats].fillna(0)
        df["p"] = np.nan
        for ini, fim in zip(cortes[:-1], cortes[1:]):
            tr, te = df[df.data < ini], df[(df.data >= ini) & (df.data < fim)]
            df.loc[te.index, "p"] = treinar(tr, feats).predict(te[feats])
        teste = df[df.p.notna()].copy()
        teste["atual"] = -teste.rank_modelo
        antes, depois = taxas(teste, "atual"), taxas(teste, "p")
        meta["temperatura"][tipo] = melhor_temperatura(teste, "p")
        meta["features"][tipo] = feats
        meta["teste_para_frente"][tipo] = {"acoes": int(teste.acao.nunique()),
                                           "modelo_contagem": antes, "ranking": depois}
        print(f"\n{tipo.upper()} — teste para frente em {teste.acao.nunique()} ações (fim do Worlds)")
        print(f"  modelo de contagem  top1/3/5: {antes[0]:.1%}  {antes[1]:.1%}  {antes[2]:.1%}")
        print(f"  ranking aprendido   top1/3/5: {depois[0]:.1%}  {depois[1]:.1%}  {depois[2]:.1%}")
        treinar(df, feats).save_model(str(MODELOS / f"ranking_{tipo}.txt"))
    (MODELOS / "ranking.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nModelos salvos em {MODELOS} ({time.time() - t0:.0f} s)")


if __name__ == "__main__":
    main()
