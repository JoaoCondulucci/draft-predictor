from pathlib import Path

CODIGO = Path(__file__).resolve().parent
RAIZ = CODIGO.parent

DADOS = RAIZ / "dados"
BRUTO = DADOS / "bruto"
CSVS = DADOS / "csvs"
DDRAGON = DADOS / "ddragon"
TELA = DADOS / "tela"
FRAMES = TELA / "frames"
BANCO = DADOS / "draft.db"
SERIE = DADOS / "serie_atual.json"
CALIBRACAO = TELA / "calibracao.json"
PREVIA_SLOTS = TELA / "previa_slots.png"

SCHEMA = CODIGO / "coleta" / "schema.sql"
RESULTADOS = RAIZ / "resultados"


def csv_oracles_elixir():
    """O CSV mais recente do Oracle's Elixir que estiver em dados/bruto/."""
    arquivos = sorted(BRUTO.glob("*OraclesElixir*.csv"))
    if not arquivos:
        raise FileNotFoundError(
            f"Coloque o CSV do Oracle's Elixir em {BRUTO} (https://oracleselixir.com/tools/downloads)")
    return arquivos[-1]
