"""capturar.py — salva 1 frame por segundo do vídeo calibrado em dados/tela/frames/.

Use enquanto assiste ao draft de um VOD (semifinal) para montar o conjunto
de teste do reconhecimento. Ctrl+C para parar.

    python main.py capturar            # 1 frame/s
    python main.py capturar 0.5        # 1 frame a cada 0,5 s
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import json
import time
from datetime import datetime

import cv2
import mss
import numpy as np

from caminhos import CALIBRACAO, FRAMES
from leitura_tela.layout import ALTURA, LARGURA

SAIDA = FRAMES


def main():
    intervalo = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
    calib = json.loads(CALIBRACAO.read_text(encoding="utf-8"))
    SAIDA.mkdir(parents=True, exist_ok=True)
    n = 0
    with getattr(mss, "MSS", mss.mss)() as sct:  # versões novas do mss usam MSS
        print("Capturando... Ctrl+C para parar.")
        try:
            while True:
                img = np.array(sct.grab(calib))[:, :, :3]
                video = cv2.resize(img, (LARGURA, ALTURA))
                nome = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                cv2.imwrite(str(SAIDA / f"{nome}.png"), video)
                n += 1
                time.sleep(intervalo)
        except KeyboardInterrupt:
            print(f"\n{n} frames salvos em {SAIDA}")


if __name__ == "__main__":
    main()
