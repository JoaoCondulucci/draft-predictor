"""Carrega os recortes do Oracle's Elixir no draft.db (recria o banco do zero a cada execução)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import sqlite3

import pandas as pd

from caminhos import BANCO, CSVS, SCHEMA
from regras import ORDEM_DRAFT, ROTAS

ARQUIVOS = [CSVS / "gen_blg.csv", CSVS / "worlds_todos.csv"]

ROLES = set(ROTAS)


def ler_csvs():
    """Junta os recortes, sem repetir jogos que aparecem em mais de um arquivo."""
    partes = [pd.read_csv(a, dtype={"patch": str}, low_memory=False) for a in ARQUIVOS]
    df = pd.concat(partes, ignore_index=True)
    return df.drop_duplicates(subset=["gameid", "teamname", "position"])


def texto_ou_none(valor):
    """Converte NaN (célula vazia do pandas) em None, que vira NULL no banco."""
    return None if pd.isna(valor) else str(valor)


def montar_jogos(df):
    """Um registro por jogo, a partir das 2 linhas de time (position == 'team')."""
    linhas_time = df[df["position"] == "team"]
    jogos = []
    for game_id, linhas in linhas_time.groupby("gameid"):
        azul = linhas[linhas["side"] == "Blue"]
        verm = linhas[linhas["side"] == "Red"]
        if len(azul) != 1 or len(verm) != 1:
            print(f"[aviso] {game_id}: não tem exatamente 1 linha azul e 1 vermelha, pulando")
            continue
        azul, verm = azul.iloc[0], verm.iloc[0]

        if azul["firstPick"] == 1:
            first_pick = azul["teamname"]
        elif verm["firstPick"] == 1:
            first_pick = verm["teamname"]
        else:
            print(f"[aviso] {game_id}: firstPick vazio, assumindo lado azul")
            first_pick = azul["teamname"]

        jogos.append({
            "game_id": str(game_id),
            "game_number": int(azul["game"]),
            "league": str(azul["league"]),
            "split": texto_ou_none(azul["split"]),
            "playoffs": int(azul["playoffs"]),
            "date_utc": str(azul["date"]),
            "patch": str(azul["patch"]),
            "blue_team": str(azul["teamname"]),
            "red_team": str(verm["teamname"]),
            "first_pick_team": str(first_pick),
            "winner": str(azul["teamname"] if azul["result"] == 1 else verm["teamname"]),
            "duration_s": None if pd.isna(azul["gamelength"]) else int(azul["gamelength"]),
        })
    return jogos, linhas_time


def montar_series(jogos):
    """Percorre os jogos em ordem de data. Para cada confronto (liga + par de times),
    game == 1 abre uma série nova; os jogos seguintes entram na série aberta."""
    jogos.sort(key=lambda j: j["date_utc"])
    serie_aberta = {}  # confronto -> (series_id, último game_number)
    for j in jogos:
        confronto = (j["league"], *sorted([j["blue_team"], j["red_team"]]))
        anterior = serie_aberta.get(confronto)
        continua = (
            j["game_number"] > 1
            and anterior is not None
            and j["game_number"] == anterior[1] + 1
        )
        if continua:
            series_id = anterior[0]
        else:
            if j["game_number"] != 1:
                print(f"[aviso] {j['game_id']}: game {j['game_number']} sem o jogo anterior; "
                      "abrindo série nova (Fearless desse jogo fica incompleto)")
            series_id = f"{confronto[0]}|{confronto[1]}|{confronto[2]}|{j['date_utc']}"
        j["series_id"] = series_id
        serie_aberta[confronto] = (series_id, j["game_number"])
    return jogos


def montar_draft(jogos, linhas_time):
    """Transforma ban1..5 / pick1..5 de cada time na sequência global de 20 passos."""
    por_time = linhas_time.set_index(["gameid", "teamname"])
    acoes = []
    for j in jogos:
        segundo = j["red_team"] if j["first_pick_team"] == j["blue_team"] else j["blue_team"]
        quem = {"FP": j["first_pick_team"], "SP": segundo}
        usados = {}
        for step, (fase, tipo, q) in enumerate(ORDEM_DRAFT, start=1):
            time = quem[q]
            n = usados.get((time, tipo), 0) + 1
            usados[(time, tipo)] = n
            campeao = por_time.loc[(j["game_id"], time), f"{tipo}{n}"]
            acoes.append((j["game_id"], step, time, tipo, fase, n, texto_ou_none(campeao)))
    return acoes


def montar_jogadores(df, ids_validos):
    linhas = df[df["position"].isin(ROLES) & df["gameid"].isin(ids_validos)]
    return [
        (str(r.gameid), str(r.teamname), str(r.position),
         texto_ou_none(r.playername) or "?", str(r.champion), int(r.result))
        for r in linhas.itertuples()
    ]


def conferir(con):
    """Checagens que pegam bug de carga. As duas contagens devem dar 0."""
    picks_sem_jogador = con.execute("""
        SELECT COUNT(*) FROM draft_actions d
        WHERE d.action_type = 'pick'
          AND d.champion NOT IN (SELECT p.champion FROM player_games p
                                 WHERE p.game_id = d.game_id)
    """).fetchone()[0]

    repetidos_fearless = con.execute("""
        SELECT COUNT(*) FROM draft_actions d
        JOIN v_fearless_locked f ON f.game_id = d.game_id AND f.champion = d.champion
        WHERE d.action_type = 'pick'
    """).fetchone()[0]

    print(f"picks do draft sem jogador correspondente: {picks_sem_jogador}")
    print(f"picks que repetem campeão já usado na série (Fearless): {repetidos_fearless}")


def carregar_todos_picks(con):
    """Picks de todos os jogos de 2026, gerados pelo recortes.py (csvs/todos_picks.csv)."""
    arquivo = CSVS / "todos_picks.csv"
    if not arquivo.exists():
        print("[aviso] csvs/todos_picks.csv não existe: rode: python main.py dados "
              "(sem ele a previsão funciona, mas sem sinergias e counters)")
        return
    t = pd.read_csv(arquivo).dropna(subset=["champion", "side", "position"])
    t = t.drop_duplicates(subset=["gameid", "side", "position"])
    tem_ordem = "team_order" in t.columns
    tem_jogador = "playername" in t.columns
    linhas = [(str(r.gameid), str(r.date), str(r.league), str(r.side), str(r.teamname),
               str(r.position), str(r.champion), int(r.result),
               int(r.team_order) if tem_ordem and not pd.isna(r.team_order) else None,
               texto_ou_none(r.playername) if tem_jogador else None)
              for r in t.itertuples()]
    con.executemany("INSERT INTO todos_picks VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", linhas)
    print(f"todos_picks: {t['gameid'].nunique()} jogos de todas as ligas")

    arquivo_bans = CSVS / "todos_bans.csv"
    if not arquivo_bans.exists():
        print("[aviso] csvs/todos_bans.csv não existe: rode: python main.py dados")
        return
    b = pd.read_csv(arquivo_bans).dropna(subset=["champion"])
    b = b.drop_duplicates(subset=["gameid", "side", "team_order"])
    con.executemany("INSERT INTO todos_bans VALUES (?, ?, ?, ?, ?, ?, ?)",
                    [(str(r.gameid), str(r.date), str(r.league), str(r.side), str(r.teamname),
                      int(r.team_order), str(r.champion)) for r in b.itertuples()])
    print(f"todos_bans: {b['gameid'].nunique()} jogos, {len(b)} bans")


def main():
    df = ler_csvs()
    jogos, linhas_time = montar_jogos(df)
    jogos = montar_series(jogos)
    acoes = montar_draft(jogos, linhas_time)
    jogadores = montar_jogadores(df, {j["game_id"] for j in jogos})

    if BANCO.exists():
        BANCO.unlink()
    con = sqlite3.connect(BANCO)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(SCHEMA.read_text(encoding="utf-8"))

    colunas = ["game_id", "series_id", "game_number", "league", "split", "playoffs",
               "date_utc", "patch", "blue_team", "red_team", "first_pick_team",
               "winner", "duration_s"]
    con.executemany(
        f"INSERT INTO games ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
        [tuple(j[c] for c in colunas) for j in jogos],
    )
    con.executemany("INSERT INTO draft_actions VALUES (?, ?, ?, ?, ?, ?, ?)", acoes)
    con.executemany("INSERT INTO player_games VALUES (?, ?, ?, ?, ?, ?)", jogadores)
    carregar_todos_picks(con)
    con.commit()

    n_series = con.execute("SELECT COUNT(DISTINCT series_id) FROM games").fetchone()[0]
    print(f"{len(jogos)} jogos, {n_series} séries, {len(acoes)} ações de draft, "
          f"{len(jogadores)} linhas de jogador")
    conferir(con)
    con.close()


if __name__ == "__main__":
    main()
