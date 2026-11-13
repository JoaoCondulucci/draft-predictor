"""Ponto de entrada do projeto: python main.py <comando>. Sem comando, lista as opções."""
import runpy
import sys
from pathlib import Path

CODIGO = Path(__file__).resolve().parent / "codigo"

COMANDOS = {
    "dados":      (["coleta/recortes.py", "coleta/load.py"], "recria os recortes e o draft.db a partir do CSV"),
    "recortes":   (["coleta/recortes.py"], "só os recortes (dados/csvs/)"),
    "load":       (["coleta/load.py"], "só o draft.db (a partir de dados/csvs/)"),
    "consulta":   (["coleta/consulta.py"], 'roda um SQL no banco: consulta "SELECT ..."'),
    "ddragon":    (["leitura_tela/baixar_ddragon.py", "leitura_tela/empacotar_ddragon.py"],
                   "baixa e empacota as imagens dos campeões"),
    "calibrar":   (["leitura_tela/calibrar.py"], "marca onde o vídeo está na tela"),
    "capturar":   (["leitura_tela/capturar.py"], "salva frames do vídeo para testes"),
    "aovivo":     (["ao_vivo/draft_ao_vivo.py"], "acompanha o draft (ao vivo ou --replay)"),
    "backtest":   (["previsao/backtest.py"], "acerto da previsão em jogos passados"),
    "modelo":     (["previsao/modelo.py"], "exemplo de previsão (1º ban GEN x BLG)"),
    "ranking":    (["previsao/treinar_ranking.py"], "treina o ranking aprendido (LightGBM) com o Worlds"),
    "avaliacao":  (["analise/avaliacao.py", "analise/tendencias.py", "analise/planilha.py"],
                   "avaliação completa + tendências + planilha (resultados/)"),
    "tendencias": (["analise/tendencias.py"], "só as tabelas de tendências"),
    "planilha":   (["analise/planilha.py"], "só a planilha (a partir de resultados/)"),
}


def ajuda():
    print(__doc__)
    print("Comandos:")
    for nome, (_, desc) in COMANDOS.items():
        print(f"  {nome:11} {desc}")


def main():
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDOS:
        ajuda()
        return
    nome, extras = sys.argv[1], sys.argv[2:]
    for script in COMANDOS[nome][0]:
        caminho = CODIGO / script
        sys.argv = [str(caminho)] + extras
        runpy.run_path(str(caminho), run_name="__main__")


if __name__ == "__main__":
    main()
