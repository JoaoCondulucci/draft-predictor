"""Prevê o próximo pick ou ban a partir do draft.db, sem machine learning (poucos jogos por time).

Pick: soma, em cada rota aberta, de P(rota | nº do pick, time) x P(campeão | jogador da rota),
      com peso por recência, um pouco do meta, sinergia com os aliados e counter da rota.
Ban:  ameaça (pool dos adversários nas rotas abertas) + histórico de bans do time + meta.
Campeões já usados no jogo ou bloqueados pelo Fearless nunca entram.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import math
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime

from caminhos import BANCO
from regras import ROTAS, sigla

MEIA_VIDA_DIAS = 45      # peso de um jogo cai pela metade a cada 45 dias
SUAVIZACAO = 2.0         # "jogos imaginários" vindos do meta, para campeões fora do pool
PESO_META_PICK = 0.15
PESOS_BAN = {"ameaca": 0.5, "historico": 0.25, "meta": 0.25}        # 2ª fase de bans
PESOS_BAN_FASE1 = {"ameaca": 0.5, "historico": 0.25, "meta": 0.25}  # 1ª fase de bans
LIGA_META = "WLDs"

# Sinergias e counters usam lift: quantas vezes mais o par aparece do que o acaso
# explicaria (1 = indiferente). Base: todos os jogos de 2026, todas as ligas.
ALFA_PAR = 5.0           # suavização: pares com poucos jogos ficam perto de 1
BETA_SINERGIA = 0.5      # força da sinergia com os aliados já escolhidos
GAMA_COUNTER = 0.5       # força do "costuma ser escolhido contra" o adversário de rota
LIMITE_FATOR = (0.2, 4.0)
PESO_TENDENCIA = 5.0     # quanto "puxar" a tendência do time para a média geral (poucos jogos)
MEIA_VIDA_PARES = 0       # dias; 0 = todos os jogos de 2026 pesam igual nas sinergias/counters
PESO_BAN_FASE = 0.6      # no histórico de bans, quanto vale o que o time bane NESSA fase
USAR_TODOS_BANS = True   # histórico de bans de todas as ligas (False = só GEN/BLG/Worlds)


def _data(texto):
    return datetime.strptime(texto[:19], "%Y-%m-%d %H:%M:%S")


def _normalizar(d):
    total = sum(d.values())
    return {k: v / total for k, v in d.items()} if total > 0 else {}


class Modelo:
    """Estatísticas calculadas do draft.db usando só jogos ANTES de `ate` (para backtest honesto)."""

    def __init__(self, banco=BANCO, ate=None):
        self.ate = ate
        self.ranking = None      # ranking aprendido (previsao/ranking.py), opcional
        con = sqlite3.connect(banco)
        filtro, args = ("WHERE g.date_utc < ?", (ate,)) if ate else ("", ())
        ref = _data(ate) if ate else _data(con.execute("SELECT MAX(date_utc) FROM games").fetchone()[0])

        def peso(data):
            return 0.5 ** (max((ref - _data(data)).days, 0) / MEIA_VIDA_DIAS)

        self.pool = defaultdict(Counter)        # jogador -> campeão -> peso
        self.jogos_jogador = defaultdict(Counter)
        self.elenco = {}                         # (time, rota) -> jogador mais recente
        self.rota_do_campeao = defaultdict(Counter)  # campeão -> rota -> peso (todas as equipes)
        self.meta_pick = defaultdict(Counter)    # rota -> campeão -> nº picks no Worlds
        ultimo = {}
        # Pool de todos os jogos de 2026 quando a tabela tem o jogador (cobre adversários de outras ligas)
        colunas = {c[1] for c in con.execute("PRAGMA table_info(todos_picks)")}
        self.usa_todos = "player" in colunas
        if self.usa_todos:
            sql = f"""SELECT team, role, player, champion, date_utc, league FROM todos_picks
                      {filtro.replace('g.', '') or 'WHERE 1=1'} AND player IS NOT NULL"""
        else:
            sql = f"""SELECT pg.team, pg.role, pg.player, pg.champion, g.date_utc, g.league
                      FROM player_games pg JOIN games g ON g.game_id = pg.game_id {filtro}"""
        for time, rota, jogador, campeao, data, liga in con.execute(sql, args):
            w = peso(data)
            self.pool[jogador][campeao] += w
            self.jogos_jogador[jogador][campeao] += 1
            self.rota_do_campeao[campeao][rota] += w
            if liga == LIGA_META:
                self.meta_pick[rota][campeao] += 1
            if data > ultimo.get((time, rota), ""):
                ultimo[(time, rota)] = data
                self.elenco[(time, rota)] = jogador

        # Que rota o time costuma garantir no 1º, 2º... pick (padrão do time)
        self.rota_por_ordem = defaultdict(Counter)
        self.bans_time = defaultdict(Counter)
        self.meta_ban = Counter()
        self.n_jogos_meta = 0
        for time, tipo, ordem, campeao, data, liga, rota in con.execute(f"""
                SELECT d.team, d.action_type, d.team_order, d.champion, g.date_utc, g.league, pg.role
                FROM draft_actions d
                JOIN games g ON g.game_id = d.game_id
                LEFT JOIN player_games pg
                  ON pg.game_id = d.game_id AND pg.team = d.team AND pg.champion = d.champion
                {filtro}""", args):
            if campeao is None:
                continue
            w = peso(data)
            if tipo == "pick" and rota and not self.usa_todos:
                self.rota_por_ordem[(time, ordem)][rota] += w
            elif tipo == "ban":
                self.bans_time[time][campeao] += w
                if liga == LIGA_META:
                    self.meta_ban[campeao] += 1
        # Bans de todas as ligas por fase: 1ª (bans 1-3) e 2ª (bans 4-5) têm alvos diferentes
        self.bans_fase = defaultdict(Counter)
        self.n_bans_fase = defaultdict(Counter)
        tabelas = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "todos_bans" in tabelas and USAR_TODOS_BANS:
            self.bans_time = defaultdict(Counter)
            for time, ordem, campeao, data in con.execute(
                    f"""SELECT team, team_order, champion, date_utc FROM todos_bans
                        {filtro.replace('g.', '')}""", args):
                w = peso(data)
                self.bans_time[time][campeao] += w
                self.bans_fase[(time, 1 if ordem <= 3 else 2)][campeao] += w
                self.n_bans_fase[(time, 1 if ordem <= 3 else 2)][campeao] += 1

        if self.usa_todos:
            for time, ordem, rota, data in con.execute(
                    f"""SELECT team, team_order, role, date_utc FROM todos_picks
                        {filtro.replace('g.', '') or 'WHERE 1=1'} AND team_order IS NOT NULL""", args):
                self.rota_por_ordem[(time, ordem)][rota] += peso(data)
        self.n_jogos_meta = con.execute(
            f"SELECT COUNT(*) FROM games g {filtro + (' AND' if filtro else 'WHERE')} g.league = ?",
            args + (LIGA_META,)).fetchone()[0]
        self.campeoes = set(self.rota_do_campeao) | set(self.meta_ban)
        self._carregar_pares(con, filtro.replace("g.", ""), args, ref)
        con.close()

    def _carregar_pares(self, con, filtro, args, ref):
        """Conta, em todos os jogos de 2026, duplas do mesmo time, duelos de rota e a ordem das rotas."""
        times = defaultdict(dict)
        peso_jogo = {}
        ordens = defaultdict(dict)
        try:
            linhas = con.execute(
                f"SELECT game_id, side, role, champion, team_order, date_utc FROM todos_picks {filtro}",
                args).fetchall()
        except sqlite3.OperationalError:
            linhas = []
            print("[previsao] draft.db sem a tabela todos_picks: rode: python main.py dados "
                  "para ativar sinergias, counters e padrão de rotas")
        for g, lado, rota, campeao, ordem, data in linhas:
            times[(g, lado)][rota] = campeao
            if g not in peso_jogo:
                dias = max((ref - _data(data)).days, 0)
                peso_jogo[g] = 0.5 ** (dias / MEIA_VIDA_PARES) if MEIA_VIDA_PARES else 1.0
            if ordem:
                ordens[(g, lado)][ordem] = rota

        # Padrão de rotas: que rota sai no pick n, sabendo quais rotas o time já pegou
        self.seq_rotas = defaultdict(Counter)
        self.marg_rotas = defaultdict(Counter)
        for seq in ordens.values():
            if len(seq) != 5:
                continue
            pegas = set()
            for n in range(1, 6):
                self.seq_rotas[(frozenset(pegas), n)][seq[n]] += 1
                self.marg_rotas[n][seq[n]] += 1
                pegas.add(seq[n])
        self.n_time = Counter()
        self.n_par = Counter()  # (a, b) em ordem alfabética -> jogos juntos no mesmo time
        self.n_rota = defaultdict(Counter)
        self.n_duelo = Counter()                 # (c, adversário, rota) -> nº
        jogos = defaultdict(dict)
        for (g, lado), rotas in times.items():
            w = peso_jogo[g]
            campeoes = sorted(set(rotas.values()))
            for a in campeoes:
                self.n_time[a] += w
            for i, a in enumerate(campeoes):
                for b in campeoes[i + 1:]:
                    self.n_par[(a, b)] += w
            for r, c in rotas.items():
                self.n_rota[r][c] += w
            jogos[g][lado] = rotas
        for g, lados in jogos.items():
            if len(lados) != 2:
                continue
            azul, verm = lados.get("Blue", {}), lados.get("Red", {})
            for r in ROTAS:
                if r in azul and r in verm:
                    w = peso_jogo[g]
                    self.n_duelo[(azul[r], verm[r], r)] += w
                    self.n_duelo[(verm[r], azul[r], r)] += w
        self.N_times = max(sum(peso_jogo[g] for (g, _) in times), 1e-9)
        self.N_jogos = max(sum(peso_jogo[g] for g in jogos), 1e-9)

    def sinergia(self, a, b):
        par = (a, b) if a < b else (b, a)
        esperado = self.n_time[a] * self.n_time[b] / self.N_times
        return (self.n_par[par] + ALFA_PAR) / (esperado + ALFA_PAR)

    def duelo(self, c, adversario, rota):
        esperado = self.n_rota[rota][c] * self.n_rota[rota][adversario] / self.N_jogos
        return (self.n_duelo[(c, adversario, rota)] + ALFA_PAR) / (esperado + ALFA_PAR)

    @staticmethod
    def _limitar(x):
        return min(max(x, LIMITE_FATOR[0]), LIMITE_FATOR[1])

    def fator_sinergia(self, c, aliados):
        """Multiplicador e o melhor parceiro (para o motivo)."""
        if not aliados or BETA_SINERGIA == 0:
            return 1.0, None
        lifts = {a: self.sinergia(c, a) for a in aliados}
        fator = math.exp(BETA_SINERGIA * sum(math.log(v) for v in lifts.values()))
        melhor = max(lifts, key=lifts.get)
        return self._limitar(fator), (melhor, lifts[melhor])


    def p_meta_rota(self, rota):
        return _normalizar(self.meta_pick[rota])

    def p_campeao_jogador(self, jogador, rota, candidatos):
        """P(campeão | jogador), suavizada com o meta da rota."""
        pool = self.pool.get(jogador, Counter())
        meta = self.p_meta_rota(rota)
        total = sum(pool.values())
        return {c: (pool.get(c, 0) + SUAVIZACAO * meta.get(c, 0)) / (total + SUAVIZACAO)
                for c in candidatos}

    def rotas_ocupadas(self, time, picks):
        """Descobre a rota de cada campeão já escolhido pelo time (o pick não diz a rota)."""
        livres, ocupadas = list(ROTAS), {}
        # Primeiro os campeões com rota mais "óbvia"
        def certeza(c):
            d = _normalizar(self.rota_do_campeao.get(c, Counter()))
            return max(d.values()) if d else 0
        for c in sorted(picks, key=certeza, reverse=True):
            melhor, score = None, -1
            for r in livres:
                jogador = self.elenco.get((time, r))
                s = (self.pool.get(jogador, Counter()).get(c, 0) + 0.01) * \
                    (_normalizar(self.rota_do_campeao.get(c, Counter())).get(r, 0) + 0.01)
                if s > score:
                    melhor, score = r, s
            if melhor:
                ocupadas[c] = melhor
                livres.remove(melhor)
        return ocupadas, livres


    def prever(self, time, adversario, tipo, ordem, picks_time, picks_adv, indisponiveis, k=5):
        """Top-k para a próxima ação.

        time/adversario: nomes como no banco ('Gen.G'); tipo: 'pick' ou 'ban';
        ordem: nº do pick/ban DENTRO do time (1..5); picks_*: campeões já escolhidos;
        indisponiveis: tudo que não pode sair (bans, picks, Fearless).
        Retorna [(campeão, probabilidade, motivo)].
        """
        candidatos = self.campeoes - set(indisponiveis)
        if tipo == "pick":
            scores, motivos = self._pick(time, adversario, ordem, picks_time, picks_adv, candidatos)
        else:
            scores, motivos = self._ban(time, adversario, ordem, picks_time, picks_adv, candidatos)
        if self.ranking is not None:
            scores = self.ranking.notas(self, tipo, time, adversario, ordem, picks_time, picks_adv, candidatos)
        else:
            scores = _normalizar(scores)
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        return [(c, p, motivos.get(c, "")) for c, p in top]

    def p_proxima_rota(self, time, ordem, ocupadas, livres):
        """P(rota do pick nº `ordem`), dado o que o time já pegou.

        Base: todos os jogos de 2026 (ex.: já pegou jng + bot -> sup é muito provável).
        Ajuste: a tendência do PRÓPRIO time nesse nº de pick (ex.: BLG segura o mid pro fim).
        """
        base = self.seq_rotas.get((frozenset(ocupadas), ordem), Counter())
        p = _normalizar({r: base.get(r, 0) + 1 for r in livres})
        marg = _normalizar(self.marg_rotas.get(ordem, Counter()))
        hist = self.rota_por_ordem.get((time, ordem), Counter())
        total_hist = sum(hist.values())
        if marg:
            for r in livres:
                m = marg.get(r, 0.2) or 0.2
                tendencia = (hist.get(r, 0) + PESO_TENDENCIA * m) / (total_hist + PESO_TENDENCIA)
                p[r] *= tendencia / m
        return _normalizar(p)

    def _pick(self, time, adversario, ordem, picks_time, picks_adv, candidatos):
        ocupadas, livres = self.rotas_ocupadas(time, picks_time)
        rota_adv, _ = self.rotas_ocupadas(adversario, picks_adv)
        adv_na_rota = {r: c for c, r in rota_adv.items()}
        p_rota = self.p_proxima_rota(time, ordem, set(ocupadas.values()), livres)
        scores, motivos, melhor_contrib, extra = Counter(), {}, {}, {}
        for r, pr in p_rota.items():
            jogador = self.elenco.get((time, r))
            oponente = adv_na_rota.get(r)
            for c, pc in self.p_campeao_jogador(jogador, r, candidatos).items():
                f_duelo = 1.0
                if oponente and GAMA_COUNTER:
                    f_duelo = self._limitar(self.duelo(c, oponente, r) ** GAMA_COUNTER)
                contrib = pr * pc * f_duelo
                scores[c] += contrib
                if contrib > melhor_contrib.get(c, 0):
                    melhor_contrib[c] = contrib
                    n = self.jogos_jogador.get(jogador, Counter()).get(c, 0)
                    motivos[c] = f"{jogador} · {n} jogos" if n else "meta do Worlds"
                    extra[c] = f" · contra {oponente}" if f_duelo >= 1.5 else ""
        meta_total = _normalizar(sum((self.meta_pick[r] for r in livres), Counter()))
        for c in candidatos:
            scores[c] = (1 - PESO_META_PICK) * scores[c] + PESO_META_PICK * meta_total.get(c, 0)
            f_sin, melhor = self.fator_sinergia(c, picks_time)
            scores[c] *= f_sin
            if c in motivos:
                if melhor and melhor[1] >= 2:
                    motivos[c] += f" · combo com {melhor[0]}"
                motivos[c] += extra.get(c, "")
        return scores, motivos

    def _ban(self, time, adversario, ordem, picks_time, picks_adv, candidatos):
        rota_minha, _ = self.rotas_ocupadas(time, picks_time)
        meu_na_rota = {r: c for c, r in rota_minha.items()}
        _, livres_adv = self.rotas_ocupadas(adversario, picks_adv)
        ameaca, motivos, maior = Counter(), {}, {}
        for r in livres_adv:
            jogador = self.elenco.get((adversario, r))
            pool = self.pool.get(jogador, Counter())
            meu = meu_na_rota.get(r)
            for c in candidatos:
                v = pool.get(c, 0)
                if meu and GAMA_COUNTER:       # o adversário pegaria c contra o meu campeão?
                    v *= self._limitar(self.duelo(c, meu, r) ** GAMA_COUNTER)
                ameaca[c] += v
                if v > maior.get(c, 0):
                    maior[c] = v
                    n = self.jogos_jogador[jogador][c]
                    motivos[c] = f"tira de {jogador} ({n} jogos)"
        for c in candidatos:                    # ... e completaria um combo do adversário?
            f_sin, melhor = self.fator_sinergia(c, picks_adv)
            ameaca[c] *= f_sin
            if c in motivos and melhor and melhor[1] >= 2:
                motivos[c] += f" · combo com {melhor[0]}"
        hist = self.bans_time.get(time, Counter())
        fase = 1 if ordem <= 3 else 2
        hist_fase = self.bans_fase.get((time, fase), Counter())
        geral = _normalizar({c: hist.get(c, 0) for c in candidatos})
        da_fase = _normalizar({c: hist_fase.get(c, 0) for c in candidatos})
        historico = ({c: PESO_BAN_FASE * da_fase.get(c, 0) + (1 - PESO_BAN_FASE) * geral.get(c, 0)
                      for c in candidatos} if da_fase else geral)
        partes = {"ameaca": _normalizar({c: ameaca[c] for c in candidatos}),
                  "historico": historico,
                  "meta": _normalizar({c: self.meta_ban.get(c, 0) for c in candidatos})}
        scores = Counter()
        for nome, peso in (PESOS_BAN_FASE1 if fase == 1 else PESOS_BAN).items():
            for c, v in partes[nome].items():
                scores[c] += peso * v
        # Motivo: até 2 pedaços, do mais específico ao mais geral
        vezes = self.n_bans_fase.get((time, fase), Counter())
        for c in candidatos:
            pedacos = [motivos[c]] if partes["ameaca"].get(c, 0) >= 0.02 and c in motivos else []
            if vezes.get(c, 0):
                pedacos.append(f"{sigla(time)} baniu {vezes[c]}x na fase")
            if len(pedacos) < 2 and self.meta_ban.get(c, 0):
                pedacos.append(f"banido em {self.meta_ban[c] / max(self.n_jogos_meta, 1):.0%} do Worlds")
            if pedacos:
                motivos[c] = " · ".join(pedacos[:2])
        return scores, motivos


def estado_para_previsao(passos_feitos, passo_atual, time_por_lado, fearless=()):
    """Converte o draft (lista de passos já feitos) nos argumentos de Modelo.prever.

    passos_feitos: [(lado, tipo, campeão)] em ordem; passo_atual: (lado, tipo, nº no time).
    time_por_lado: {'blue': 'Gen.G', 'red': 'Bilibili Gaming'}.
    """
    lado, tipo, ordem = passo_atual
    adv = "red" if lado == "blue" else "blue"
    picks = {l: [c for (ll, t, c) in passos_feitos if ll == l and t == "pick" and c] for l in ("blue", "red")}
    indisponiveis = {c for (_, _, c) in passos_feitos if c} | set(fearless)
    return dict(time=time_por_lado[lado], adversario=time_por_lado[adv], tipo=tipo, ordem=ordem,
                picks_time=picks[lado], picks_adv=picks[adv], indisponiveis=indisponiveis)


if __name__ == "__main__":
    m = Modelo()
    args = estado_para_previsao([], ("blue", "ban", 1), {"blue": "Gen.G", "red": "Bilibili Gaming"})
    for c, p, motivo in m.prever(**args):
        print(f"{c:15} {p:5.1%}  {motivo}")
