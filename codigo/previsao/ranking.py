"""Reordena os candidatos do Modelo com um ranking aprendido (LightGBM LambdaRank).

O modelo de contagem (modelo.py) continua calculando tudo; a nota dele é uma das features.
O LightGBM aprendeu, com os jogos do Worlds, a combinar essa nota com outros sinais
(taxas recentes de pick/ban, sinergias, counters, o que cada time costuma banir).
Treino: python main.py ranking. Sem os arquivos treinados ou sem lightgbm, nada muda.
"""
import json
import math
import sqlite3

from caminhos import BANCO, DADOS
from previsao.features import Estatisticas, features_ban, features_pick

MODELOS = DADOS / "modelos"


def carregar(modelo, banco=BANCO):
    """Liga o ranking ao modelo, se possível. Devolve True se ligou."""
    arq_meta = MODELOS / "ranking.json"
    if not arq_meta.exists():
        print("[ranking] sem modelo treinado (python main.py ranking): usando só o modelo de contagem")
        return False
    try:
        import lightgbm as lgb
    except ImportError:
        print("[ranking] lightgbm não instalado (pip install lightgbm): usando só o modelo de contagem")
        return False
    meta = json.loads(arq_meta.read_text(encoding="utf-8"))
    modelos = {tipo: lgb.Booster(model_file=str(MODELOS / f"ranking_{tipo}.txt")) for tipo in ("pick", "ban")}
    with sqlite3.connect(banco) as con:
        est = Estatisticas(con).ate(modelo.ate)
    modelo.ranking = Ranking(modelos, meta, est)
    return True


class Ranking:
    def __init__(self, modelos, meta, est):
        self.modelos, self.meta, self.est = modelos, meta, est

    def notas(self, m, tipo, time, adversario, ordem, picks_time, picks_adv, candidatos):
        """{campeão: probabilidade} pelo ranking aprendido."""
        f = features_pick if tipo == "pick" else features_ban
        linhas = f(m, self.est, time, adversario, ordem, picks_time, picks_adv, candidatos,
                   {"ordem": ordem})
        colunas = self.meta["features"][tipo]
        x = [[linha.get(c, 0.0) for c in colunas] for linha in linhas]
        brutas = self.modelos[tipo].predict(x)
        # softmax com "temperatura" ajustada no treino, para o % ficar perto da taxa real de acerto
        t = self.meta["temperatura"][tipo]
        maior = max(brutas)
        exps = [math.exp((s - maior) / t) for s in brutas]
        total = sum(exps)
        return {linha["campeao"]: e / total for linha, e in zip(linhas, exps)}
