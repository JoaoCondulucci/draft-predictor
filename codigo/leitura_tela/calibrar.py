"""Marca onde o vídeo está na tela (calibracao.json) e gera uma prévia com os 20 slots.

    python main.py calibrar            # conta 5 s e tira o print
    python main.py calibrar print.png  # usa um print já salvo
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import json
import time

import cv2
import numpy as np

from caminhos import CALIBRACAO, PREVIA_SLOTS
from leitura_tela.layout import ALTURA, LARGURA, TIMER, regiao_reconhecimento, slots

ARQ_CALIBRACAO = CALIBRACAO
ARQ_PREVIA = PREVIA_SLOTS
MONITOR = 0  # 0 = todos os monitores juntos
ESPERA = 5


def contagem(segundos):
    print(f"Troque para a janela do vídeo. Print em {segundos} s...")
    for s in range(segundos, 0, -1):
        print(f"  {s}...")
        time.sleep(1)


def capturar_tela():
    import mss
    with getattr(mss, "MSS", mss.mss)() as sct:  # versões novas do mss usam MSS
        mon = sct.monitors[MONITOR]
        img = np.array(sct.grab(mon))[:, :, :3]  # BGRA -> BGR
        return np.ascontiguousarray(img), mon


def desenhar_slots(video):
    """Desenha os slots no quadro padrão 1280x720."""
    out = video.copy()
    for nome, ret in slots().items():
        cor = (255, 140, 0) if nome.startswith("blue") else (0, 0, 230)
        cv2.rectangle(out, ret[:2], ret[2:], cor, 1)
        x0, y0, x1, y1 = regiao_reconhecimento(nome, ret)
        cv2.rectangle(out, (x0 + 2, y0 + 2), (x1 - 2, y1 - 2), (0, 255, 0), 1)
        rotulo = nome.replace("blue_", "B").replace("red_", "R")
        cv2.putText(out, rotulo, (ret[0] + 3, ret[1] + 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.35, (255, 255, 255), 1, cv2.LINE_AA)
    cv2.rectangle(out, TIMER[:2], TIMER[2:], (0, 255, 255), 1)
    return out


def main():
    arg = sys.argv[1] if len(sys.argv) > 1 else None
    if arg and not arg.isdigit():
        tela = cv2.imread(arg)
        mon = {"left": 0, "top": 0}
    else:
        contagem(int(arg) if arg else ESPERA)
        tela, mon = capturar_tela()

    # Reduz o print só para caber na janela de seleção
    escala = min(1.0, 1800 / tela.shape[1], 950 / tela.shape[0])
    exib = cv2.resize(tela, None, fx=escala, fy=escala)
    x, y, w, h = cv2.selectROI("Arraste em cima do VIDEO e aperte ENTER", exib, showCrosshair=False)
    cv2.destroyAllWindows()
    if w == 0 or h == 0:
        print("Nenhuma área selecionada.")
        return
    x, y, w, h = (int(round(v / escala)) for v in (x, y, w, h))

    proporcao = w / h
    if abs(proporcao - 16 / 9) > 0.03:
        print(f"[aviso] a área marcada tem proporção {proporcao:.3f}; um vídeo 16:9 tem 1.778. "
              "Talvez tenha pego barra preta ou cortado o vídeo.")

    calib = {"left": mon["left"] + x, "top": mon["top"] + y, "width": w, "height": h}
    ARQ_CALIBRACAO.parent.mkdir(parents=True, exist_ok=True)
    ARQ_CALIBRACAO.write_text(json.dumps(calib, indent=2), encoding="utf-8")

    video = cv2.resize(tela[y:y + h, x:x + w], (LARGURA, ALTURA))
    cv2.imwrite(str(ARQ_PREVIA), desenhar_slots(video))
    print(f"Calibração salva em {ARQ_CALIBRACAO.name}: {calib}")
    print(f"Confira os retângulos em {ARQ_PREVIA.name}")


if __name__ == "__main__":
    main()
