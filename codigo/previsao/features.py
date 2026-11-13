"""Features por candidato para o modelo de ranking (aprendido) de picks e bans.

Para cada ação do draft, todo campeão disponível é um candidato com um vetor de features.
Tudo é calculado com o Modelo montado só com jogos ANTES do dia do jogo (sem vazamento).
"""
import math
from collections import Counter, defaultdict

import pandas as pd

from previsao.modelo import Modelo, _normalizar
from regras import ROTAS

JANELA_RECENTE = 30   # dias para as taxas "recentes"


def _log(x):
    return math.log(max(x, 1e-6))


class Estatisticas:
    """Contagens extras (recência, conforto do time) a partir de todos_picks/todos_bans."""

    def __init__(self, con):
        self.picks = pd.read_sql_query(
            "SELECT game_id, date_utc, team, role, champion, player FROM todos_picks", con)
        self.bans = pd.read_sql_query(
            "SELECT game_id, date_utc, team, team_order, champion FROM todos_bans", con)
        for t in (self.picks, self.bans):
            t["data"] = pd.to_datetime(t["date_utc"].str[:19])
        self._cache = {}

    def ate(self, ate=None):
        """Estatísticas com jogos antes de `ate` (None = todos os jogos do banco)."""
        if ate in self._cache:
            return self._cache[ate]
        fim = pd.Timestamp(ate) if ate else max(self.picks.data.max(), self.bans.data.max()) + pd.Timedelta(days=1)
        ini = fim - pd.Timedelta(days=JANELA_RECENTE)
        p = self.picks[self.picks.data < fim]
        b = self.bans[self.bans.data < fim]
        pr, br = p[p.data >= ini], b[b.data >= ini]
        n_rec = max(pr.game_id.nunique(), 1)
        e = {
            "pick_rec": (pr.groupby("champion").size() / n_rec).to_dict(),
            "ban_rec": (br.groupby("champion").size() / n_rec).to_dict(),
            "time_picks": p.groupby(["team", "champion"]).size().to_dict(),
            "time_jogos": p.groupby("team").game_id.nunique().to_dict(),
            "jog_rec": pr.groupby(["player", "champion"]).size().to_dict(),
            "time_bans": b.groupby(["team", "champion"]).size().to_dict(),
        }
        self._cache[ate] = e
        return e


def rotulo_rota(m, c):
    d = _normalizar(m.rota_do_campeao.get(c, Counter()))
    if not d:
        return None, 0.0, 0.0
    r = max(d, key=d.get)
    entropia = -sum(v * math.log(v) for v in d.values() if v > 0)
    return r, d[r], entropia


def features_pick(m, est, time, adversario, ordem, picks_time, picks_adv, candidatos, extra):
    scores, _ = m._pick(time, adversario, ordem, picks_time, picks_adv, candidatos)
    scores = _normalizar(scores)
    ocupadas, livres = m.rotas_ocupadas(time, picks_time)
    rota_adv, livres_adv = m.rotas_ocupadas(adversario, picks_adv)
    adv_na_rota = {r: c for c, r in rota_adv.items()}
    p_rota = m.p_proxima_rota(time, ordem, set(ocupadas.values()), livres)
    pjr = {r: m.p_campeao_jogador(m.elenco.get((time, r)), r, candidatos) for r in livres}
    meta_total = _normalizar(sum((m.meta_pick[r] for r in livres), Counter()))
    ordenado = sorted(scores, key=lambda c: -scores[c])
    rank = {c: i + 1 for i, c in enumerate(ordenado)}
    n_time = max(est["time_jogos"].get(time, 1), 1)
    linhas = []
    for c in candidatos:
        rota_c, certeza, entropia = rotulo_rota(m, c)
        base = sum(p_rota[r] * pjr[r][c] for r in livres)
        melhor_r = max(livres, key=lambda r: p_rota[r] * pjr[r][c]) if livres else None
        jogador = m.elenco.get((time, melhor_r)) if melhor_r else None
        pool = m.pool.get(jogador, Counter())
        total_pool = sum(pool.values()) or 1
        f_sin, melhor = m.fator_sinergia(c, picks_time)
        op = adv_na_rota.get(melhor_r)
        duelo = m.duelo(c, op, melhor_r) if op else 1.0
        # o adversário ainda pode querer esse campeão (ele é ameaça para o outro lado)?
        ameaca_adv = sum(m.pool.get(m.elenco.get((adversario, r)), Counter()).get(c, 0)
                         for r in livres_adv)
        linhas.append({
            "campeao": c, "score_modelo": scores.get(c, 0), "log_score": _log(scores.get(c, 0)), "rank_modelo": rank[c],
            "base_pool_rota": base, "log_base": _log(base),
            "pool_share": pool.get(c, 0) / total_pool, "jogos_jogador": math.log1p(m.jogos_jogador.get(jogador, Counter()).get(c, 0)),
            "jogos_jogador_rec": est["jog_rec"].get((jogador, c), 0),
            "p_rota_melhor": p_rota.get(melhor_r, 0) if melhor_r else 0,
            "rota_principal_aberta": float(rota_c in livres), "certeza_rota": certeza, "flex": entropia,
            "meta_pick": meta_total.get(c, 0), "pick_rec": est["pick_rec"].get(c, 0), "ban_rec": est["ban_rec"].get(c, 0),
            "log_sinergia": _log(f_sin), "melhor_lift": melhor[1] if melhor else 1.0,
            "log_duelo": _log(duelo), "tem_oponente": float(op is not None),
            "conforto_time": est["time_picks"].get((time, c), 0) / n_time,
            "ameaca_adv": ameaca_adv,
            "time_bane_c": est["time_bans"].get((time, c), 0) / n_time,
            "adv_bane_c": est["time_bans"].get((adversario, c), 0) / max(est["time_jogos"].get(adversario, 1), 1),
            **extra,
        })
    return linhas


def features_ban(m, est, time, adversario, ordem, picks_time, picks_adv, candidatos, extra):
    scores, _ = m._ban(time, adversario, ordem, picks_time, picks_adv, candidatos)
    scores = _normalizar(scores)
    ordenado = sorted(scores, key=lambda c: -scores[c])
    rank = {c: i + 1 for i, c in enumerate(ordenado)}
    _, livres_adv = m.rotas_ocupadas(adversario, picks_adv)
    _, livres_meu = m.rotas_ocupadas(time, picks_time)
    fase = 1 if ordem <= 3 else 2
    hist = _normalizar({c: m.bans_time.get(time, Counter()).get(c, 0) for c in candidatos})
    hist_fase = _normalizar({c: m.bans_fase.get((time, fase), Counter()).get(c, 0) for c in candidatos})
    meta = _normalizar({c: m.meta_ban.get(c, 0) for c in candidatos})
    n_adv = max(est["time_jogos"].get(adversario, 1), 1)
    n_time = max(est["time_jogos"].get(time, 1), 1)
    linhas = []
    for c in candidatos:
        _, certeza, entropia = rotulo_rota(m, c)
        ameaca, ameaca_rec, maior_share = 0.0, 0, 0.0
        for r in livres_adv:
            jog = m.elenco.get((adversario, r))
            pool = m.pool.get(jog, Counter())
            ameaca += pool.get(c, 0)
            ameaca_rec += est["jog_rec"].get((jog, c), 0)
            tot = sum(pool.values()) or 1
            maior_share = max(maior_share, pool.get(c, 0) / tot)
        meu_pool = 0.0
        for r in livres_meu:
            pool = m.pool.get(m.elenco.get((time, r)), Counter())
            tot = sum(pool.values()) or 1
            meu_pool = max(meu_pool, pool.get(c, 0) / tot)
        f_sin, _ = m.fator_sinergia(c, picks_adv)
        linhas.append({
            "campeao": c, "score_modelo": scores.get(c, 0), "log_score": _log(scores.get(c, 0)), "rank_modelo": rank[c],
            "ameaca": ameaca, "ameaca_rec": ameaca_rec, "ameaca_share": maior_share,
            "log_sinergia_adv": _log(f_sin),
            "hist_geral": hist.get(c, 0), "hist_fase": hist_fase.get(c, 0), "meta_ban": meta.get(c, 0),
            "pick_rec": est["pick_rec"].get(c, 0), "ban_rec": est["ban_rec"].get(c, 0),
            "conforto_adv": est["time_picks"].get((adversario, c), 0) / n_adv,
            "conforto_meu": est["time_picks"].get((time, c), 0) / n_time,
            "meu_pool_share": meu_pool, "flex": entropia, "certeza_rota": certeza,
            "fase": fase,
            **extra,
        })
    return linhas
