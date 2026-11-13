"""Acompanha o draft lendo a tela, prevê a próxima ação e desenha o overlay.

    python main.py aovivo --fp blue --azul GEN --vermelho BLG --nova-serie   # jogo 1 da série
    python main.py aovivo --fp red  --azul BLG --vermelho GEN                # jogos seguintes
    python main.py aovivo --replay dados/tela/frames --fp red --jogo <game_id>  # teste com frames

--fp é o LADO com o first pick. --nova-serie zera o Fearless; nos jogos seguintes, os picks
anteriores vêm de dados/serie_atual.json.
Comandos no terminal: fix <slot> <campeão> | passo <N> | estado | sair
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import argparse
import json
import sqlite3
import textwrap
import threading
import time
from datetime import datetime

import cv2
import numpy as np

from caminhos import BANCO, CALIBRACAO, SERIE
from leitura_tela.layout import ALTURA, LARGURA
from leitura_tela.reconhecedor import Reconhecedor
from regras import ORDEM_DRAFT, sigla

ARQ_SERIE = SERIE
MIN_DURACAO_PASSO = 1.0     # segundos: evita contar o mesmo passo duas vezes
GRACA_RESET = 2.5           # segundos após um passo novo em que a barra ainda está enchendo
SALTO_RESET = 0.25          # a barra do timer "volta a encher" mais que isso = passo novo


def outro(lado):
    return "red" if lado == "blue" else "blue"


class Previsor:
    """Liga o EstadoDraft ao modelo do previsao.py."""

    def __init__(self, time_por_lado, ate=None):
        from previsao import ranking
        from previsao.modelo import Modelo
        self.modelo = Modelo(ate=ate)  # só jogos anteriores (replay honesto)
        problema = ranking.carregar(self.modelo)
        self.descricao = ("modelo de contagem + ranking aprendido" if problema is None
                          else f"só o modelo de contagem ({problema})")
        self.time_por_lado = time_por_lado

    def prever(self, estado):
        from previsao.modelo import estado_para_previsao
        p = estado.passo(estado.atual)
        feitos = [(q["lado"], q["tipo"], estado.valor.get(q["slot"]))
                  for q in estado.passos[:estado.atual - 1]]
        args = estado_para_previsao(feitos, (p["lado"], p["tipo"], p["n"]),
                                    self.time_por_lado, estado.fearless)
        return self.modelo.prever(**args, k=5)


class EstadoDraft:
    def __init__(self, reconhecedor, fp_lado, fearless=(), previsor=None):
        self.rec = reconhecedor
        self.fearless = set(fearless)
        self.previsor = previsor
        self.previsao = []         # top 5 do passo atual: [(campeão, prob, motivo)]
        self.previsao_do_passo = {}
        self.trava = threading.Lock()
        self.passos = []
        contagem = {}
        for step, (fase, tipo, quem) in enumerate(ORDEM_DRAFT, start=1):
            lado = fp_lado if quem == "FP" else outro(fp_lado)
            n = contagem[(lado, tipo)] = contagem.get((lado, tipo), 0) + 1
            self.passos.append({"step": step, "fase": fase, "lado": lado, "tipo": tipo,
                                "n": n, "slot": f"{lado}_{tipo}{n}"})
        self.valor = {}            # slot -> campeão confirmado (None = passo sem leitura confiável)
        self.atual = 1             # passo em andamento (21 = draft terminou)
        self.inicio_passo = None
        self.timer_anterior = None
        self.frac_min = 1.0
        self._sinais = 0
        self._cianos = 0
        self.congelado = False     # fim do draft à vista: picks não são mais relidos
        self.provisorios = set()   # picks lidos no aperto do fim: conferidos depois da troca
        self.fim_em = None
        self._proximo_reler = 0
        self.trocas = False        # fase de trocas (barra ciano): picks não mudam mais
        self.hover = None          # leitura provisória do passo atual
        self._candidato = {}
        self.log = []


    def passo(self, n):
        return self.passos[n - 1]

    def usados(self, exceto=None):
        return {v for s, v in self.valor.items() if v and s != exceto} | self.fearless

    def evento(self, t, msg, detalhe=""):
        hora = datetime.fromtimestamp(t).strftime("%H:%M:%S")
        self.log.append(f"{hora}   {msg}" + (f"  [{detalhe}]" if detalhe else ""))
        print(f"{hora}   {msg}")

    def quem(self, p):
        """Sigla do time que faz o passo (ou o lado, se os times não foram informados)."""
        if self.previsor:
            return sigla(self.previsor.time_por_lado[p["lado"]])
        return "azul" if p["lado"] == "blue" else "verm."

    def rotulo(self, p):
        return f"{self.quem(p):<5} {p['tipo']:<4} {p['n']}"

    def posicao_txt(self, p):
        """Onde o campeão escolhido estava na previsão daquele passo."""
        top, valor = self.previsao_do_passo.get(p["step"]), self.valor.get(p["slot"])
        if top is None or not valor:
            return ""
        return f"{top.index(valor) + 1}º da previsão" if valor in top else "fora do top 5"

    def linha_passo(self, p, obs=""):
        valor = self.valor.get(p["slot"])
        if not valor:
            return f"{self.rotulo(p)}   {'??':<14}sem leitura confiável · use: fix {p['slot']} <campeão>"
        return f"{self.rotulo(p)}   {valor:<14}{self.posicao_txt(p)}" + (f"  ({obs})" if obs else "")


    def _ler(self, frame, slot):
        return self.rec.ler_slot(frame, slot, frozenset(self.usados(exceto=slot)))

    def confirmar_atual(self, frame, t, motivo, preferir_hover=False):
        p = self.passo(self.atual)
        if preferir_hover and self.hover and self.hover.ok:
            # Na fase de trocas os cards podem já ter mudado de dono: vale o hover lido antes do ciano
            self.valor[p["slot"]] = self.hover.nome
        else:
            leitura = self._ler(frame, p["slot"])
            self.valor[p["slot"]] = leitura.nome if leitura.ok else None
            if not leitura.ok and self.hover and self.hover.ok:
                self.valor[p["slot"]] = self.hover.nome
        if self.previsor and self.previsao:
            # O acerto é calculado no fim, com o valor final do passo (inclui correções)
            self.previsao_do_passo[p["step"]] = [c for c, _, _ in self.previsao]
        self.evento(t, self.linha_passo(p), detalhe=f"passo {p['step']}, {motivo}")
        self.atual += 1
        self.inicio_passo = t
        self.hover = None
        self.atualizar_previsao()

    def atualizar_previsao(self):
        if not self.previsor or self.atual > 20:
            self.previsao = []
            return
        self.previsao = self.previsor.prever(self)
        p = self.passo(self.atual)
        resumo = " · ".join(f"{c} {prob:.0%}" for c, prob, _ in self.previsao)
        print(f"{'próximo':<8}   {self.rotulo(p)}   {resumo}")

    def fix(self, slot, nome):
        """Correção manual pelo terminal. Aceita o nome em minúsculas ('kled', 'ksante')."""
        simples = lambda s: "".join(ch for ch in s.lower() if ch.isalnum())
        achados = [n for n in self.rec.nomes if simples(n) == simples(nome)]
        if not achados:
            return f"campeão '{nome}' não encontrado"
        if not any(p["slot"] == slot for p in self.passos):
            return f"slot '{slot}' não existe (ex.: blue_pick3, red_ban2)"
        with self.trava:
            self.valor[slot] = achados[0]
            self.atualizar_previsao()
        return f"ok: {slot} = {achados[0]}"

    def snapshot(self):
        """Cópia do estado para o overlay desenhar (chamado de outra thread)."""
        with self.trava:
            passo = self.passo(self.atual) if self.atual <= 20 and not self.trocas else None
            titulo = ""
            if passo and self.previsor:
                titulo = f"{sigla(self.previsor.time_por_lado[passo['lado']])} · {passo['tipo'].upper()} {passo['n']}"
            return {"valores": dict(self.valor), "passo": passo, "titulo": titulo,
                    "hover": self.hover.nome if self.hover and self.hover.ok else None,
                    "previsao": list(self.previsao)}

    def _corrigir(self, frame, t):
        """Relê slots já confirmados: corrige leituras feitas cedo demais (ex.: no hover)."""
        # Picks já lidos: relê só UM por ciclo (rodízio), porque o SIFT custa ~0,5 s
        picks_lidos = [p["slot"] for p in self.passos[:self.atual - 1]
                       if p["tipo"] == "pick" and self.valor.get(p["slot"]) is not None]
        da_vez = None
        if picks_lidos:
            da_vez = picks_lidos[self._proximo_reler % len(picks_lidos)]
            self._proximo_reler += 1
        for p in self.passos[:self.atual - 1]:
            slot = p["slot"]
            if self.trocas and p["tipo"] == "pick":
                continue
            atual = self.valor.get(slot)
            if atual is not None and p["tipo"] == "pick" and slot != da_vez:
                continue
            leitura = self._ler(frame, slot)
            if not leitura.ok or leitura.nome == atual:
                self._candidato.pop(slot, None)
                continue
            nome, vezes = self._candidato.get(slot, (None, 0))
            vezes = vezes + 1 if nome == leitura.nome else 1
            self._candidato[slot] = (leitura.nome, vezes)
            # Passo sem leitura: 2 leituras iguais bastam. Trocar uma leitura já feita: 3.
            if vezes >= (2 if atual is None else 3):
                self.valor[slot] = leitura.nome
                self._candidato.pop(slot)
                obs = "corrigido" if atual is None else f"corrigido, era {atual}"
                self.evento(t, self.linha_passo(p, obs), detalhe=f"passo {p['step']}, releitura")
                self.atualizar_previsao()

    def atualizar(self, frame, t):
        with self.trava:
            self._atualizar(frame, t)

    def terminado(self, t, espera=15):
        """Depois das trocas, continua lendo até tirar as dúvidas (ou por `espera` segundos)."""
        pendente = self.provisorios or any(self.valor.get(p["slot"]) is None
                                           for p in self.passos if p["tipo"] == "pick")
        return not pendente or (self.fim_em is not None and t - self.fim_em > espera)

    def resolver_por_composicao(self, frame, t):
        """Depois da troca de cards, o pick duvidoso de um time é o campeão que sobra nos 5 cards
        tirando os outros 4 picks conhecidos.
        """
        for lado in ("blue", "red"):
            passos_pick = [p for p in self.passos if p["lado"] == lado and p["tipo"] == "pick"]
            duvidosos = [p for p in passos_pick
                         if self.valor.get(p["slot"]) is None or p["slot"] in self.provisorios]
            if len(duvidosos) != 1:
                continue
            alvo = duvidosos[0]
            conhecidos = {self.valor[p["slot"]] for p in passos_pick if p is not alvo}
            vistos = set()
            for n in range(1, 6):
                leitura = self.rec.ler_pick(frame, f"{lado}_pick{n}", frozenset(self.fearless))
                if leitura.ok:
                    vistos.add(leitura.nome)
            sobra = vistos - conhecidos
            if len(vistos) == 5 and len(sobra) == 1:
                nome = sobra.pop()
                antes = self.valor.get(alvo["slot"])
                self.valor[alvo["slot"]] = nome
                self.provisorios.discard(alvo["slot"])
                if nome != antes:
                    obs = "pelos 5 cards" + (f", era {antes}" if antes else "")
                    self.evento(t, self.linha_passo(alvo, obs), detalhe=f"passo {alvo['step']}")

    def _atualizar(self, frame, t):
        if self.trocas:
            if self.provisorios or any(self.valor.get(p["slot"]) is None
                                       for p in self.passos if p["tipo"] == "pick"):
                self.resolver_por_composicao(frame, t)
            return
        if self.previsor and not self.previsao and self.atual <= 20:
            self.atualizar_previsao()
        cor, frac = self.rec.ler_timer(frame)

        # Fim do draft: 3 frames ciano seguidos e o último pick feito. A barra também fica
        # ciano em transições de fase no meio do draft, o que não pode encerrá-lo.
        self._cianos = self._cianos + 1 if cor == "cyan" else 0
        # Ao primeiro frame ciano os times podem começar a trocar campeões de card:
        # a partir daí não relemos picks nem atualizamos o hover.
        if cor == "cyan" and self.atual >= 17:
            self.congelado = True
        elif cor in ("red", "blue"):
            self.congelado = False
        if cor == "cyan" and not self.trocas:
            ultimo = self.passo(20)["slot"]
            # Último pick feito: os 20 passos fecharam, o card 20 é legível ou o hover do passo 20
            # foi confiável. Depois da troca o card 20 pode mostrar outro campeão já usado.
            ultimo_feito = (self.atual > 20 or self._ler(frame, ultimo).ok
                            or (self.atual == 20 and self.hover is not None and self.hover.ok))
            if self._cianos < 3 or self.atual < 17 or not ultimo_feito:
                cor = None
        if cor == "cyan" and not self.trocas:
            while self.atual <= 20:
                p = self.passo(self.atual)
                self.confirmar_atual(frame, t, "fase de trocas", preferir_hover=True)
                if p["tipo"] == "pick":
                    self.provisorios.add(p["slot"])   # confere depois pelos 5 cards
            self.fim_em = t
            # Última chance para picks sem leitura, antes de os campeões trocarem de card
            for p in self.passos:
                if p["tipo"] == "pick" and self.valor.get(p["slot"]) is None:
                    leitura = self._ler(frame, p["slot"])
                    if leitura.ok:
                        self.valor[p["slot"]] = leitura.nome
                        self.evento(t, self.linha_passo(p, "leitura final"), detalhe=f"passo {p['step']}")
            self.trocas = True
            self.evento(t, "fim do draft")

        if self.atual <= 20 and cor in ("red", "blue"):
            if self.inicio_passo is None:
                self.inicio_passo = t
            if self.timer_anterior is None:
                self.timer_anterior, self.frac_min = cor, frac
            # Passo novo = a cor mudou ou a barra voltou a encher, em 2 frames seguidos (contra ruído).
            # Logo após um passo, a animação de encher a barra não conta (GRACA_RESET).
            em_graca = t - self.inicio_passo < GRACA_RESET
            mudou = cor != self.timer_anterior or (not em_graca and frac - self.frac_min > SALTO_RESET)
            if mudou:
                self._sinais += 1
            else:
                self._sinais = 0
                if not em_graca:
                    self.frac_min = min(self.frac_min, frac)
            if self._sinais >= 2 and t - self.inicio_passo >= MIN_DURACAO_PASSO:
                self.confirmar_atual(frame, t, "timer")
                self.timer_anterior, self.frac_min, self._sinais = cor, 1.0, 0
            # A barra é do outro time e o slot atual já tem campeão: o passo acabou sem vermos.
            elif (self._sinais == 0 and cor != self.passo(self.atual)["lado"]
                  and self._ler(frame, self.passo(self.atual)["slot"]).ok):
                self.confirmar_atual(frame, t, "ressincronizado")
                self.timer_anterior, self.frac_min = cor, 1.0

        if self.atual <= 20 and not self.congelado:
            # Plano B: o slot do passo seguinte já tem campeão -> o atual com certeza travou
            while self.atual < 20 and self._ler(frame, self.passo(self.atual + 1)["slot"]).ok:
                self.confirmar_atual(frame, t, "slot seguinte preenchido")
                self.timer_anterior, self.frac_min, self._sinais = cor, 1.0, 0
            if self.atual <= 20:
                self.hover = self._ler(frame, self.passo(self.atual)["slot"])

        if not self.congelado:
            self._corrigir(frame, t)


    def resumo(self):
        linhas = []
        for p in self.passos:
            if p["step"] < self.atual:
                v = f"{self.valor.get(p['slot']) or '??':<14}{self.posicao_txt(p)}"
            else:
                v = "(pendente)"
            linhas.append(f"{p['step']:4d}   {self.rotulo(p)}   {v}")
        return "\n".join(linhas)

    def picks(self):
        return [self.valor.get(p["slot"]) for p in self.passos if p["tipo"] == "pick"]


def tempo_do_arquivo(caminho):
    return datetime.strptime(caminho.stem[:19], "%Y%m%d_%H%M%S_%f").timestamp()


def comparar_com_banco(estado, game_id):
    with sqlite3.connect(BANCO) as con:
        real = dict(con.execute(
            "SELECT step, champion FROM draft_actions WHERE game_id = ?", (game_id,)).fetchall())
    if not real:
        print(f"jogo {game_id} não encontrado no draft.db")
        return
    acertos = 0
    print("\npasso  lido                 real")
    for p in estado.passos:
        lido = estado.valor.get(p["slot"])
        ok = lido == real.get(p["step"])
        acertos += ok
        print(f"{p['step']:5d}  {str(lido):20} {real.get(p['step'])}  {'ok' if ok else 'ERRO'}")
    print(f"\nacerto: {acertos}/20")


def criar_previsor(args):
    if not (args.azul and args.vermelho):
        return None
    ate = None
    if args.jogo:      # o modelo só usa jogos anteriores a este (teste honesto com VOD ou replay)
        with sqlite3.connect(BANCO) as con:
            linha = con.execute("SELECT date_utc FROM games WHERE game_id = ?", (args.jogo,)).fetchone()
            ate = linha[0] if linha else None
    return Previsor({"blue": nome_time(args.azul), "red": nome_time(args.vermelho)}, ate=ate)


def cabecalho(estado, fp_lado, fearless):
    """Primeiras linhas do terminal: confronto, modelo usado e campeões bloqueados."""
    print("-" * 78)
    if estado.previsor:
        times = {lado: sigla(t) for lado, t in estado.previsor.time_por_lado.items()}
        print(f" {times['blue']} (azul) x {times['red']} (vermelho) · first pick: {times[fp_lado]}")
        if estado.previsor.modelo.ranking is None:     # só avisa quando o ranking não ligou
            print(f" Previsão: {estado.previsor.descricao}")
    else:
        print(" Sem times informados (--azul e --vermelho): só a leitura do draft, sem previsão")
    bloqueados = f"{len(fearless)} campeões bloqueados" if fearless else "nenhum campeão bloqueado"
    print(textwrap.fill(f"Fearless: {bloqueados}" + (f" ({', '.join(fearless)})" if fearless else ""),
                        width=78, initial_indent=" ", subsequent_indent="   "))
    print("-" * 78)


def resumo_previsao(estado):
    """Acerto da previsão usando o valor FINAL de cada passo (depois das correções)."""
    posicoes = {"pick": [], "ban": []}
    for p in estado.passos:
        top = estado.previsao_do_passo.get(p["step"])
        real = estado.valor.get(p["slot"])
        if top is None or not real:
            continue
        posicoes[p["tipo"]].append(top.index(real) + 1 if real in top else None)
    todas = posicoes["pick"] + posicoes["ban"]
    if not todas:
        return
    print("\nAcerto da previsão (o campeão escolhido estava entre os primeiros da lista)")
    for nome, lista in (("picks", posicoes["pick"]), ("bans", posicoes["ban"]), ("total", todas)):
        if lista:
            partes = [f"top {k}: {sum(1 for x in lista if x and x <= k):2d}/{len(lista)}" for k in (1, 3, 5)]
            print(f"  {nome:6} " + "   ".join(partes))


def replay(args):
    rec = Reconhecedor()
    fearless = carregar_fearless(args) if args.fearless_de else []
    estado = EstadoDraft(rec, args.fp, fearless, previsor=criar_previsor(args))
    cabecalho(estado, args.fp, fearless)
    arquivos = sorted(Path(args.replay).glob("*.png"))
    if args.pular:
        ini, fim = args.pular.split("-")
        hora = lambda a: datetime.fromtimestamp(tempo_do_arquivo(a)).strftime("%H:%M:%S")
        arquivos = [a for a in arquivos if not (ini <= hora(a) <= fim)]
    print(f"{len(arquivos)} frames")
    inicio = time.time()
    for a in arquivos:
        frame = cv2.imread(str(a))
        if frame.shape[:2] != (ALTURA, LARGURA):
            frame = cv2.resize(frame, (LARGURA, ALTURA))
        estado.atualizar(frame, tempo_do_arquivo(a))
    print(f"\n({time.time() - inicio:.1f} s para processar)\n\nDraft lido")
    print(estado.resumo())
    if args.jogo:
        comparar_com_banco(estado, args.jogo)
    resumo_previsao(estado)


def carregar_fearless(args):
    if args.fearless_de:      # teste com VOD: pega do banco os picks dos jogos anteriores da série
        with sqlite3.connect(BANCO) as con:
            return [c for (c,) in con.execute(
                "SELECT champion FROM v_fearless_locked WHERE game_id = ?", (args.fearless_de,))]
    if args.nova_serie or not ARQ_SERIE.exists():
        return []
    return json.loads(ARQ_SERIE.read_text(encoding="utf-8")).get("picks", [])


def salvar_fearless(picks_anteriores, estado):
    novos = [p for p in estado.picks() if p]
    ARQ_SERIE.write_text(json.dumps({"picks": picks_anteriores + novos}, ensure_ascii=False,
                                    indent=2), encoding="utf-8")
    print(f"Fearless: {len(picks_anteriores) + len(novos)} campeões bloqueados para o próximo jogo")


def ler_comandos(estado, parar):
    for linha in sys.stdin:
        partes = linha.strip().split(maxsplit=2)
        if not partes:
            continue
        cmd = partes[0].lower()
        if cmd == "sair":
            parar.set()
            return
        if cmd == "estado":
            print(estado.resumo())
        elif cmd == "fix" and len(partes) == 3:
            print(estado.fix(partes[1], partes[2]))
        elif cmd == "passo" and len(partes) == 2:
            with estado.trava:
                estado.atual = int(partes[1])
                estado.inicio_passo = time.time()
                estado.atualizar_previsao()
            print(f"ok: passo atual = {estado.atual}")
        else:
            print("comandos: fix <slot> <campeão> | passo <N> | estado | sair")


def loop_captura(estado, calib, parar):
    import mss
    with getattr(mss, "MSS", mss.mss)() as sct:
        while not parar.is_set():
            t = time.time()
            img = np.array(sct.grab(calib))[:, :, :3]
            estado.atualizar(cv2.resize(img, (LARGURA, ALTURA)), t)
            if estado.trocas and estado.terminado(t):
                break
            time.sleep(max(0.0, 0.33 - (time.time() - t)))


def ao_vivo(args):
    calib = json.loads(CALIBRACAO.read_text(encoding="utf-8"))
    rec = Reconhecedor()
    fearless = carregar_fearless(args)
    estado = EstadoDraft(rec, args.fp, fearless, previsor=criar_previsor(args))
    cabecalho(estado, args.fp, fearless)
    parar = threading.Event()
    threading.Thread(target=ler_comandos, args=(estado, parar), daemon=True).start()

    if args.sem_overlay:
        loop_captura(estado, calib, parar)
    else:
        from ao_vivo.overlay import Overlay
        ov = Overlay(calib, estado.snapshot)

        def captura_e_fecha():
            loop_captura(estado, calib, parar)
            time.sleep(15)
            ov.fechar()

        threading.Thread(target=captura_e_fecha, daemon=True).start()
        ov.rodar()                    # o tkinter precisa rodar na thread principal
        parar.set()

    print("\nDraft lido")
    print(estado.resumo())
    resumo_previsao(estado)
    salvar_fearless(fearless, estado)


APELIDOS = {"gen": "Gen.G", "geng": "Gen.G", "gen.g": "Gen.G", "blg": "Bilibili Gaming",
            "bilibili": "Bilibili Gaming", "t1": "T1", "ig": "Invictus Gaming"}


def nome_time(texto):
    return APELIDOS.get(texto.lower(), texto)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--fp", choices=["blue", "red"], required=True,
                    help="lado que tem o first pick neste jogo")
    ap.add_argument("--replay", help="pasta com frames salvos (modo de teste)")
    ap.add_argument("--jogo", help="game_id do draft.db: o modelo só usa jogos anteriores a ele "
                                    "(e, no replay, compara com o draft real)")
    ap.add_argument("--nova-serie", action="store_true", help="ignora o serie_atual.json")
    ap.add_argument("--pular", help="replay: ignora um trecho, ex.: 12:16:08-12:17:23")
    ap.add_argument("--azul", help="time do lado azul (ex.: GEN, BLG ou o nome do banco)")
    ap.add_argument("--vermelho", help="time do lado vermelho")
    ap.add_argument("--sem-overlay", action="store_true", help="só terminal, sem desenhar na tela")
    ap.add_argument("--fearless-de", metavar="GAME_ID",
                    help="teste com VOD: usa o Fearless que esse jogo tinha (vem do draft.db)")
    args = ap.parse_args()
    if args.replay:
        replay(args)
    else:
        ao_vivo(args)


if __name__ == "__main__":
    main()
