"""Roda um SQL (texto ou arquivo .sql) no draft.db e mostra o resultado como tabela.

    python main.py consulta "SELECT * FROM v_player_pool WHERE player = 'Chovy'"
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import sqlite3

import pandas as pd

from caminhos import BANCO


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    arg = sys.argv[1]
    sql = Path(arg).read_text(encoding="utf-8") if arg.endswith(".sql") else arg
    with sqlite3.connect(BANCO) as con:
        df = pd.read_sql_query(sql, con)
    pd.set_option("display.max_rows", 200, "display.width", 200)
    print(df.to_string(index=False))
    print(f"\n{len(df)} linhas")


if __name__ == "__main__":
    main()
