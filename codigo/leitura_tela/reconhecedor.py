"""reconhecedor.py — lê a tela de draft da transmissão.

- Bans: comparação direta com o ícone quadrado (cv2.matchTemplate).
- Picks: pontos característicos SIFT contra a splash art (aguenta zoom/recorte diferentes).
- Timer: cor e comprimento da barra embaixo da câmera (de quem é a vez e quando o passo muda).

Todas as funções recebem o frame já no quadro padrão 1280x720 (ver layout.py).
"""
import cv2
import numpy as np

from caminhos import DDRAGON
from leitura_tela.layout import LARGURA, regiao_reconhecimento, slots

CACHE_SIFT = DDRAGON / "sift_splash.npz"

BAN_TAM, BAN_TPL = 44, 48  # referência maior que o recorte: tolera pequenos deslocamentos
BAN_MIN, BAN_MARGEM = 0.75, 0.12

SPLASH_W = 800
SIFT_FEATURES = 800
PICK_MIN = 12                 # pontos coincidentes mínimos
PICK_RAZAO = 2.0              # o 1º colocado precisa ter pelo menos 2x os pontos do 2º

# Xayah e Rakan dividem a mesma splash (espelhada). O desempate usa a posição x
# dos pontos coincidentes dentro da splash de referência.
SPLASH_COMPARTILHADA = {
    frozenset({"Xayah", "Rakan"}): {"referencia": "Xayah", "corte_x": 0.53,
                                    "direita": "Xayah", "esquerda": "Rakan"},
}

TIMER_Y = 521


class Leitura:
    """Resultado de um slot: campeão (ou None), confiança e o 2º colocado."""

    def __init__(self, nome=None, score=0.0, segundo=None, score2=0.0, ok=False):
        self.nome, self.score, self.segundo, self.score2, self.ok = nome, score, segundo, score2, ok

    def __repr__(self):
        estado = "ok" if self.ok else "?"
        return f"{self.nome}({self.score:.2f}, 2º {self.segundo} {self.score2:.2f}) {estado}"


class Reconhecedor:
    def __init__(self):
        p = np.load(DDRAGON / "pacote.npz")
        self.ids = [str(x) for x in p["ids"]]
        self.nomes = [str(x) for x in p["nomes"]]
        self.slots = slots()
        self.ban_tpl = [cv2.resize(sq, (BAN_TPL, BAN_TPL), interpolation=cv2.INTER_AREA)
                        for sq in p["square"]]
        self.sift = cv2.SIFT_create()
        self.bf = cv2.BFMatcher()
        self.pick_des = self._carregar_sift()  # por campeão: [descritores da splash normal, espelhada]
        self._cache = {}                         # slot -> (recorte, excluir, leitura)
        self._ref_compartilhada = {}


    def _carregar_sift(self):
        if CACHE_SIFT.exists():
            c = np.load(CACHE_SIFT)
            if [str(x) for x in c["ids"]] == self.ids:
                des, ini = c["des"].astype(np.float32), c["inicio"]
                return [[des[ini[2 * i]:ini[2 * i + 1]], des[ini[2 * i + 1]:ini[2 * i + 2]]]
                        for i in range(len(self.ids))]
        print("Calculando pontos SIFT das splash arts (só na primeira vez, ~1 min)...")
        sift = cv2.SIFT_create(nfeatures=SIFT_FEATURES)
        blocos, inicio = [], [0]
        for cid in self.ids:
            img = cv2.imread(str(DDRAGON / "splash" / f"{cid}.jpg"))
            if img is None:
                raise FileNotFoundError(f"falta ddragon/splash/{cid}.jpg (rode: python main.py ddragon)")
            img = cv2.resize(img, (SPLASH_W, int(img.shape[0] * SPLASH_W / img.shape[1])),
                             interpolation=cv2.INTER_AREA)
            cinza = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            # Algumas artes aparecem espelhadas na transmissão
            for versao in (cinza, cv2.flip(cinza, 1)):
                _, des = sift.detectAndCompute(versao, None)
                des = des if des is not None else np.zeros((0, 128), np.float32)
                blocos.append(des)
                inicio.append(inicio[-1] + len(des))
        tudo = np.vstack(blocos)
        np.savez_compressed(CACHE_SIFT, ids=np.array(self.ids),
                            des=np.clip(tudo, 0, 255).astype(np.uint8), inicio=np.array(inicio))
        return [[blocos[2 * i], blocos[2 * i + 1]] for i in range(len(self.ids))]


    def _recorte(self, frame, nome_slot, margem):
        x0, y0, x1, y1 = regiao_reconhecimento(nome_slot, self.slots[nome_slot])
        return frame[y0 + margem:y1 - margem, x0 + margem:x1 - margem]

    def _do_cache(self, nome_slot, recorte, excluir):
        """Se o slot quase não mudou desde a última leitura, reaproveita o resultado."""
        anterior = self._cache.get(nome_slot)
        if anterior and anterior[1] == excluir and anterior[0].shape == recorte.shape:
            if np.abs(anterior[0].astype(np.int16) - recorte).mean() < 3:
                return anterior[2]
        return None

    @staticmethod
    def _top2(scores):
        ordem = np.argsort(-scores)
        return ordem[0], ordem[1]


    def ler_ban(self, frame, nome_slot, excluir=frozenset()):
        recorte = self._recorte(frame, nome_slot, 2)
        cache = self._do_cache(nome_slot, recorte, excluir)
        if cache:
            return cache
        q = cv2.resize(recorte, (BAN_TAM, BAN_TAM), interpolation=cv2.INTER_AREA)
        scores = np.array([
            -1.0 if self.nomes[i] in excluir else
            cv2.matchTemplate(t, q, cv2.TM_CCOEFF_NORMED).max()
            for i, t in enumerate(self.ban_tpl)
        ])
        a, b = self._top2(scores)
        ok = scores[a] >= BAN_MIN and scores[a] - scores[b] >= BAN_MARGEM
        leitura = Leitura(self.nomes[a], float(scores[a]), self.nomes[b], float(scores[b]), ok)
        self._cache[nome_slot] = (recorte, excluir, leitura)
        return leitura

    def ler_pick(self, frame, nome_slot, excluir=frozenset()):
        recorte = self._recorte(frame, nome_slot, 4)
        cache = self._do_cache(nome_slot, recorte, excluir)
        if cache:
            return cache
        q = cv2.resize(recorte, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        _, des = self.sift.detectAndCompute(cv2.cvtColor(q, cv2.COLOR_BGR2GRAY), None)
        scores = np.zeros(len(self.ids))
        if des is not None and len(des) >= 2:
            for i, versoes in enumerate(self.pick_des):
                if self.nomes[i] in excluir:
                    continue
                melhor = 0
                for t in versoes:
                    if len(t) < 2:
                        continue
                    pares = self.bf.knnMatch(des, t, k=2)
                    bons = sum(1 for par in pares
                               if len(par) == 2 and par[0].distance < 0.75 * par[1].distance)
                    melhor = max(melhor, bons)
                scores[i] = melhor
        a, b = self._top2(scores)
        ok = scores[a] >= PICK_MIN and scores[a] >= PICK_RAZAO * max(scores[b], 1)
        leitura = Leitura(self.nomes[a], float(scores[a]), self.nomes[b], float(scores[b]), ok)
        par = frozenset({self.nomes[a], self.nomes[b]})
        if not ok and par in SPLASH_COMPARTILHADA and scores[a] >= PICK_MIN:
            leitura = self._desempatar(des, SPLASH_COMPARTILHADA[par], leitura)
        self._cache[nome_slot] = (recorte, excluir, leitura)
        return leitura

    def _desempatar(self, des, regra, leitura):
        """Decide entre campeões de splash compartilhada pela posição dos pontos coincidentes."""
        if regra["referencia"] not in self._ref_compartilhada:
            img = cv2.imread(str(DDRAGON / "splash" / f"{self.ids[self.nomes.index(regra['referencia'])]}.jpg"))
            img = cv2.resize(img, (SPLASH_W, int(img.shape[0] * SPLASH_W / img.shape[1])))
            kp, d = cv2.SIFT_create(nfeatures=SIFT_FEATURES).detectAndCompute(
                cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), None)
            self._ref_compartilhada[regra["referencia"]] = (kp, d)
        kp, d = self._ref_compartilhada[regra["referencia"]]
        pares = self.bf.knnMatch(des, d, k=2)
        xs = [kp[p[0].trainIdx].pt[0] / SPLASH_W for p in pares
              if len(p) == 2 and p[0].distance < 0.75 * p[1].distance]
        if len(xs) < PICK_MIN:
            return leitura
        nome = regra["direita"] if np.median(xs) > regra["corte_x"] else regra["esquerda"]
        outro_nome = leitura.segundo if nome == leitura.nome else leitura.nome
        return Leitura(nome, max(leitura.score, leitura.score2), outro_nome,
                       min(leitura.score, leitura.score2), True)

    def ler_slot(self, frame, nome_slot, excluir=frozenset()):
        if "ban" in nome_slot:
            return self.ler_ban(frame, nome_slot, excluir)
        return self.ler_pick(frame, nome_slot, excluir)

    @staticmethod
    def ler_timer(frame):
        """Devolve (cor, fração). cor: 'red', 'blue', 'cyan' (fase de trocas) ou None.

        A barra encolhe em direção ao CENTRO da tela. Por isso só vale o trecho colorido
        contínuo que passa pelo centro: o resto da linha é vídeo da câmera (luzes do palco).
        """
        linha = cv2.cvtColor(frame[TIMER_Y:TIMER_Y + 1, :LARGURA], cv2.COLOR_BGR2HSV)[0]
        colorido = (linha[:, 1] > 120) & (linha[:, 2] > 120)
        meio = LARGURA // 2
        if not colorido[meio - 10:meio + 10].any():
            return None, 0.0
        # Expande a partir do centro, tolerando falhas de até 3 px (compressão do vídeo)
        esq = dir_ = meio
        falha = 0
        while esq > 0 and falha <= 3:
            esq -= 1
            falha = 0 if colorido[esq] else falha + 1
        falha = 0
        while dir_ < LARGURA - 1 and falha <= 3:
            dir_ += 1
            falha = 0 if colorido[dir_] else falha + 1
        esq, dir_ = esq + 4 if esq > 0 else 0, dir_ - 4 if dir_ < LARGURA - 1 else LARGURA - 1
        if dir_ - esq < 20 or abs((meio - esq) - (dir_ - meio)) > 40:
            return None, 0.0  # assimétrico: luz do palco, não a barra
        frac = (dir_ - esq) / LARGURA
        trecho = colorido[esq:dir_ + 1]
        hue = float(np.median(linha[esq:dir_ + 1][trecho, 0]))
        if hue < 12 or hue > 165:
            return "red", frac
        if 98 <= hue <= 130:
            return "blue", frac
        if 80 <= hue < 98:
            return "cyan", frac
        return None, frac
