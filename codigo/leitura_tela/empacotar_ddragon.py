"""empacotar_ddragon.py — junta as imagens do Data Dragon num único arquivo .npz.

    python main.py ddragon

Gera dados/ddragon/pacote.npz (alguns MB) com o ícone quadrado e a arte vertical de
cada campeão já redimensionados. O reconhecedor carrega esse arquivo uma vez
só, o que é bem mais rápido que abrir 350 imagens a cada execução.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import json

import cv2
import numpy as np

from caminhos import DDRAGON as PASTA
SQUARE = (64, 64)      # (largura, altura)
LOADING = (154, 280)


def main():
    info = json.loads((PASTA / "campeoes.json").read_text(encoding="utf-8"))
    ids, nomes, squares, loadings = [], [], [], []
    for c in info["campeoes"]:
        sq = cv2.imread(str(PASTA / "square" / f"{c['id']}.png"))
        lo = cv2.imread(str(PASTA / "loading" / f"{c['id']}.jpg"))
        if sq is None or lo is None:
            print(f"[aviso] faltou imagem de {c['id']}, pulando")
            continue
        ids.append(c["id"])
        nomes.append(c["nome"])
        squares.append(cv2.resize(sq, SQUARE, interpolation=cv2.INTER_AREA))
        loadings.append(cv2.resize(lo, LOADING, interpolation=cv2.INTER_AREA))

    np.savez_compressed(
        PASTA / "pacote.npz",
        ids=np.array(ids), nomes=np.array(nomes), versao=np.array(info["versao"]),
        square=np.stack(squares), loading=np.stack(loadings),
    )
    print(f"{len(ids)} campeões empacotados em {PASTA / 'pacote.npz'}")


if __name__ == "__main__":
    main()
