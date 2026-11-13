"""baixar_ddragon.py — baixa as imagens de referência de todos os campeões (Data Dragon).

    python main.py ddragon

Cria dados/ddragon/ com:
  campeoes.json      -> id do Data Dragon, nome (igual ao Oracle's Elixir) e versão
  square/<id>.png    -> ícone quadrado 120x120 (para os BANS)
  loading/<id>.jpg   -> arte vertical 308x560 (candidata para os PICKS)
  splash/<id>.jpg    -> arte horizontal 1215x717 (outra candidata para os PICKS)

Ainda não sabemos se a transmissão usa a arte "loading" ou um recorte da "splash"
nos cards; baixamos as duas e o teste decide. Só usa a biblioteca padrão do Python.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # pasta codigo/

import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from caminhos import DDRAGON as PASTA
BASE = "https://ddragon.leagueoflegends.com"


def baixar_json(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


def baixar_arquivo(url_destino):
    url, destino = url_destino
    if destino.exists():
        return "já existia"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            destino.write_bytes(r.read())
        return "ok"
    except Exception as e:  # noqa: BLE001 — queremos seguir com os outros campeões
        return f"ERRO {e}"


def main():
    versao = baixar_json(f"{BASE}/api/versions.json")[0]
    dados = baixar_json(f"{BASE}/cdn/{versao}/data/en_US/champion.json")["data"]
    print(f"Versão {versao}: {len(dados)} campeões")

    for sub in ("square", "loading", "splash"):
        (PASTA / sub).mkdir(parents=True, exist_ok=True)

    campeoes = sorted(({"id": c["id"], "nome": c["name"]} for c in dados.values()),
                      key=lambda c: c["nome"])
    (PASTA / "campeoes.json").write_text(
        json.dumps({"versao": versao, "campeoes": campeoes}, ensure_ascii=False, indent=2),
        encoding="utf-8")

    tarefas = []
    for c in campeoes:
        cid = c["id"]
        tarefas += [
            (f"{BASE}/cdn/{versao}/img/champion/{cid}.png", PASTA / "square" / f"{cid}.png"),
            (f"{BASE}/cdn/img/champion/loading/{cid}_0.jpg", PASTA / "loading" / f"{cid}.jpg"),
            (f"{BASE}/cdn/img/champion/splash/{cid}_0.jpg", PASTA / "splash" / f"{cid}.jpg"),
        ]

    with ThreadPoolExecutor(max_workers=16) as pool:
        resultados = list(pool.map(baixar_arquivo, tarefas))

    erros = [(t[0], r) for t, r in zip(tarefas, resultados) if r.startswith("ERRO")]
    print(f"{len(tarefas) - len(erros)} arquivos ok, {len(erros)} erros")
    for url, r in erros[:10]:
        print("  ", url, r)


if __name__ == "__main__":
    main()
