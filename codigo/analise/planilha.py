"""Junta a avaliação e as tendências em resultados/avaliacao_worlds.xlsx.

As taxas de acerto são fórmulas sobre a aba "Ações": corrigir ou filtrar dados ali
atualiza os resumos.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # permite importar de codigo/

import sqlite3

import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from caminhos import BANCO, RESULTADOS

AV = RESULTADOS
SAIDA = AV / "avaliacao_worlds.xlsx"
LIGA = "WLDs"
DESTAQUE = {"Gen.G", "Bilibili Gaming"}

FONTE = "Arial"
F_NORMAL = Font(name=FONTE, size=10)
F_NEGRITO = Font(name=FONTE, size=10, bold=True)
F_TITULO = Font(name=FONTE, size=14, bold=True)
F_NOTA = Font(name=FONTE, size=9, italic=True, color="666666")
F_CAB = Font(name=FONTE, size=10, bold=True, color="FFFFFF")
FUNDO_CAB = PatternFill("solid", fgColor="1F3A5F")
FUNDO_SUB = PatternFill("solid", fgColor="E8EEF5")
BORDA = Border(bottom=Side(style="thin", color="C9D3DF"))
PCT = "0%"

COLUNAS_ACOES = [
    ("data", "Data"), ("game_id", "Jogo"), ("jogo_da_serie", "Jogo da série"), ("time", "Time"),
    ("adversario", "Adversário"), ("lado", "Lado"), ("tem_first_pick", "Tem first pick"),
    ("venceu", "Venceu"), ("passo", "Passo"), ("fase", "Fase"), ("tipo", "Tipo"),
    ("ordem_no_time", "Nº no time"), ("real", "Campeão real"), ("posicao", "Posição no ranking"),
    ("prob_real", "Prob. do real"), ("top1", "Top 1 previsto"), ("prob_top1", "Prob. top 1"),
    ("motivo_top1", "Motivo do top 1"), ("top5", "Top 5 previsto"),
    ("posicao_baseline", "Posição no 'mais popular'"), ("fearless_bloqueados", "Bloqueados Fearless"),
]


def cabecalho(ws, linha, textos, col=1):
    for i, t in enumerate(textos):
        c = ws.cell(row=linha, column=col + i, value=t)
        c.font, c.fill = F_CAB, FUNDO_CAB
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)


def escrever_tabela(ws, linha, df, col=1, formatos=None, titulo=None):
    """Escreve um DataFrame com cabeçalho; devolve a próxima linha livre."""
    formatos = formatos or {}
    if titulo:
        ws.cell(row=linha, column=col, value=titulo).font = F_NEGRITO
        linha += 1
    cabecalho(ws, linha, list(df.columns), col)
    for r, valores in enumerate(df.itertuples(index=False), start=linha + 1):
        for j, v in enumerate(valores):
            if isinstance(v, float) and pd.isna(v):
                v = None
            c = ws.cell(row=r, column=col + j, value=v)
            c.font, c.border = F_NORMAL, BORDA
            if df.columns[j] in formatos:
                c.number_format = formatos[df.columns[j]]
    return linha + len(df) + 2


def larguras(ws, larg):
    for i, w in enumerate(larg, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def taxas_formula(ws, linha, n_acoes, filtros, col=1):
    """Linha de taxas (ações, top1, top3, top5, baseline top5) com COUNTIFS na aba Ações.

    filtros: lista de (letra_da_coluna_em_Ações, critério_em_texto_de_fórmula).
    """
    fim = n_acoes + 1
    rng = lambda letra: f"'Ações'!${letra}$2:${letra}${fim}"
    base = ",".join(f"{rng(l)},{crit}" for l, crit in filtros)
    pos, posb = col_letra("posicao"), col_letra("posicao_baseline")
    total = f"COUNTIFS({base})"
    ws.cell(row=linha, column=col, value=f"={total}")
    for j, (coluna, lim) in enumerate([(pos, 1), (pos, 3), (pos, 5), (posb, 5)], start=1):
        f = f'=IFERROR(COUNTIFS({base},{rng(coluna)},"<={lim}")/{total},0)'
        c = ws.cell(row=linha, column=col + j, value=f)
        c.number_format = PCT
    for j in range(5):
        ws.cell(row=linha, column=col + j).font = F_NORMAL


def col_letra(nome):
    return get_column_letter([c for c, _ in COLUNAS_ACOES].index(nome) + 1)


def aba_acoes(wb, acoes):
    ws = wb.create_sheet("Ações")
    cabecalho(ws, 1, [t for _, t in COLUNAS_ACOES])
    for r, linha in enumerate(acoes[[c for c, _ in COLUNAS_ACOES]].itertuples(index=False), start=2):
        for j, v in enumerate(linha, start=1):
            if isinstance(v, float) and pd.isna(v):
                v = None
            if isinstance(v, bool):
                v = "sim" if v else "não"
            c = ws.cell(row=r, column=j, value=v)
            c.font = F_NORMAL
    for nome in ("prob_real", "prob_top1"):
        letra = col_letra(nome)
        for r in range(2, len(acoes) + 2):
            ws[f"{letra}{r}"].number_format = "0.0%"
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUNAS_ACOES))}{len(acoes) + 1}"
    larguras(ws, [11, 18, 8, 20, 20, 6, 8, 7, 6, 7, 6, 7, 14, 9, 8, 14, 8, 38, 48, 10, 9])


def aba_resumo(wb, acoes, n_jogos):
    ws = wb.active
    ws.title = "Resumo"
    n = len(acoes)
    ws["A1"] = "Previsão de draft — Worlds 2026"
    ws["A1"].font = F_TITULO
    ws["A2"] = (f"{n_jogos} jogos, {n} ações (picks e bans de todos os times). Para cada ação, o modelo "
                "foi montado só com jogos até o dia anterior.")
    ws["A3"] = ("Top N = o campeão real estava entre os N primeiros do ranking. 'Mais popular' = "
                "o campeão mais escolhido/banido no Worlds até ali, ainda disponível (baseline).")
    for a in ("A2", "A3"):
        ws[a].font = F_NOTA
    T, F, J = col_letra("tipo"), col_letra("fase"), col_letra("jogo_da_serie")
    cols = ["", "Ações", "Top 1", "Top 3", "Top 5", "'Mais popular' top 5"]

    linha = 5
    ws.cell(row=linha, column=1, value="Geral").font = F_NEGRITO
    cabecalho(ws, linha + 1, cols)
    for i, tipo in enumerate(["pick", "ban"]):
        r = linha + 2 + i
        ws.cell(row=r, column=1, value=tipo + "s").font = F_NEGRITO
        taxas_formula(ws, r, n, [(T, f'"{tipo}"')], col=2)

    linha = 10
    ws.cell(row=linha, column=1, value="Por fase do draft").font = F_NEGRITO
    cabecalho(ws, linha + 1, cols)
    for i, (fase, rotulo) in enumerate([("ban1", "bans 1ª fase"), ("pick1", "picks 1ª fase"),
                                        ("ban2", "bans 2ª fase"), ("pick2", "picks 2ª fase")]):
        r = linha + 2 + i
        ws.cell(row=r, column=1, value=rotulo).font = F_NEGRITO
        taxas_formula(ws, r, n, [(F, f'"{fase}"')], col=2)

    linha = 17
    ws.cell(row=linha, column=1, value="Por jogo da série (Fearless: quanto mais tarde, menos campeões)").font = F_NEGRITO
    cabecalho(ws, linha + 1, cols)
    r = linha + 2
    for jogo in range(1, 6):
        for tipo in ("pick", "ban"):
            ws.cell(row=r, column=1, value=f"jogo {jogo} — {tipo}s").font = F_NEGRITO
            taxas_formula(ws, r, n, [(J, str(jogo)), (T, f'"{tipo}"')], col=2)
            r += 1
    ws.cell(row=r + 1, column=1,
            value="Jogo 5 tem poucas ações (só uma série foi até o fim): não tire conclusão dali.").font = F_NOTA
    larguras(ws, [26, 9, 9, 9, 9, 20])


def aba_tendencia(wb, nome, df, formatos, larg, nota):
    ws = wb.create_sheet(nome)
    ws["A1"] = nota
    ws["A1"].font = F_NOTA
    escrever_tabela(ws, 3, df, formatos=formatos)
    ws.freeze_panes = "A4"
    larguras(ws, larg)


def aba_time(wb, time, acoes, n_acoes, tend, jogadores):
    nome_aba = time[:31].replace("/", "-")
    ws = wb.create_sheet(nome_aba)
    ws["A1"] = time
    ws["A1"].font = F_TITULO
    ws["B2"] = time            # célula usada pelas fórmulas
    ws["A2"] = "Time:"
    ws["A2"].font = F_NEGRITO
    ws["B2"].font = F_NORMAL
    TM, T, F = col_letra("time"), col_letra("tipo"), col_letra("fase")

    cabecalho(ws, 4, ["Acerto da previsão", "Ações", "Top 1", "Top 3", "Top 5", "'Mais popular' top 5"])
    linhas = [("picks", [(T, '"pick"')]), ("bans", [(T, '"ban"')]),
              ("bans 1ª fase", [(F, '"ban1"')]), ("picks 1ª fase", [(F, '"pick1"')]),
              ("bans 2ª fase", [(F, '"ban2"')]), ("picks 2ª fase", [(F, '"pick2"')])]
    for i, (rotulo, filtros) in enumerate(linhas):
        r = 5 + i
        ws.cell(row=r, column=1, value=rotulo).font = F_NEGRITO
        taxas_formula(ws, r, n_acoes, [(TM, "$B$2")] + filtros, col=2)

    linha = 13
    fp = tend["first_pick"][tend["first_pick"]["time"] == time].drop(columns=["time"])
    if len(fp):
        fp = fp.rename(columns={"jogos": "Jogos", "pct_com_first_pick": "% com first pick",
                                "pct_lado_azul": "% lado azul", "pct_azul_e_first_pick": "% azul E first pick",
                                "winrate_com_fp": "Vitórias com FP", "winrate_sem_fp": "Vitórias sem FP"})
        linha = escrever_tabela(ws, linha, fp, formatos={c: PCT for c in fp.columns if c != "Jogos"},
                                titulo="Lado e first pick")

    rot = tend["rotas"][tend["rotas"]["time"] == time].drop(columns=["time"])
    if len(rot):
        rot = rot.rename(columns={"pick_do_time": "Pick do time"})
        linha = escrever_tabela(ws, linha, rot, formatos={c: PCT for c in rot.columns if c != "Pick do time"},
                                titulo="Que rota o time pega em cada pick (% dos jogos)")

    bans = tend["bans_time"][tend["bans_time"]["time"] == time]
    for fase, rotulo in (("ban1", "1ª fase"), ("ban2", "2ª fase")):
        b = bans[bans["fase"] == fase][["campeao", "vezes"]].rename(
            columns={"campeao": "Campeão", "vezes": "Vezes"})
        if len(b):
            linha = escrever_tabela(ws, linha, b, titulo=f"Bans mais frequentes — {rotulo}")

    pj = jogadores[jogadores["team"] == time]
    if len(pj):
        pool = (pj.groupby(["role", "player", "champion"])
                  .agg(jogos=("win", "size"), vitorias=("win", "sum")).reset_index()
                  .sort_values(["role", "jogos"], ascending=[True, False]))
        ordem_rota = {"top": 0, "jng": 1, "mid": 2, "bot": 3, "sup": 4}
        pool = pool.sort_values(by=["role", "jogos"], key=lambda s: s.map(ordem_rota) if s.name == "role" else -s)
        pool = pool.rename(columns={"role": "Rota", "player": "Jogador", "champion": "Campeão",
                                    "jogos": "Jogos", "vitorias": "Vitórias"})
        linha = escrever_tabela(ws, linha, pool, titulo="Campeões jogados no Worlds")

    erros = acoes[(acoes["time"] == time) & ~(acoes["posicao"] <= 5)][
        ["data", "adversario", "jogo_da_serie", "passo", "tipo", "real", "posicao", "top1", "motivo_top1"]]
    erros = erros.rename(columns={"data": "Data", "adversario": "Adversário", "jogo_da_serie": "Jogo",
                                  "passo": "Passo", "tipo": "Tipo", "real": "Real",
                                  "posicao": "Posição", "top1": "Top 1 previsto", "motivo_top1": "Motivo"})
    if len(erros):
        escrever_tabela(ws, linha, erros,
                        titulo="Onde a previsão errou (real fora do top 5; posição vazia = além do 60º)")
    larguras(ws, [22, 16, 14, 10, 12, 18, 16, 16, 40])


def main():
    acoes = pd.read_csv(AV / "acoes.csv")
    tend = {n: pd.read_csv(AV / f"tend_{n}.csv") for n in
            ("presenca", "duplas", "rotas", "first_pick", "fearless", "bans_time")}
    con = sqlite3.connect(BANCO)
    jogadores = pd.read_sql_query("""SELECT pg.* FROM player_games pg JOIN games g USING (game_id)
                                     WHERE g.league = ?""", con, params=(LIGA,))
    n_jogos = acoes["game_id"].nunique()

    wb = Workbook()
    aba_resumo(wb, acoes, n_jogos)

    pres = tend["presenca"].rename(columns={
        "campeao": "Campeão", "rota_principal": "Rota", "picks": "Picks", "bans": "Bans",
        "bans_1a_fase": "Bans 1ª fase", "bans_2a_fase": "Bans 2ª fase", "vitorias": "Vitórias",
        "presenca": "Presença (P+B)", "winrate": "Winrate"})
    pres = pres[["Campeão", "Rota", "Presença (P+B)", "Picks", "Bans", "Bans 1ª fase", "Bans 2ª fase",
                 "Vitórias", "Winrate"]]
    aba_tendencia(wb, "Presença", pres, {"Presença (P+B)": PCT, "Winrate": PCT},
                  [14, 7, 12, 7, 7, 10, 10, 9, 9],
                  f"Presença = (picks + bans) / {n_jogos} jogos do Worlds. Winrate só conta jogos em que o campeão foi escolhido.")

    du = tend["duplas"].rename(columns={"campeao_a": "Campeão A", "rota_a": "Rota A", "campeao_b": "Campeão B",
                                        "rota_b": "Rota B", "jogos_juntos": "Jogos juntos", "lift": "Lift"})
    aba_tendencia(wb, "Duplas", du, {"Lift": "0.0x"}, [14, 8, 14, 8, 11, 8],
                  "Lift = quantas vezes mais a dupla aparece no mesmo time do que o acaso explicaria. Mínimo de 4 jogos juntos.")

    fe = tend["fearless"].rename(columns={"campeao": "Campeão", "picks_em_series": "Picks em séries",
                                          "jogo_medio_da_serie": "Jogo médio da série",
                                          "pct_no_jogo_1": "% escolhido no jogo 1"})
    aba_tendencia(wb, "Fearless", fe, {"Jogo médio da série": "0.00", "% escolhido no jogo 1": PCT},
                  [14, 14, 18, 18],
                  "Séries de 2+ jogos. Jogo médio baixo = o time 'gasta' o campeão cedo; alto = guarda para os jogos decisivos. Mínimo de 4 picks.")

    fp = tend["first_pick"].rename(columns={
        "time": "Time", "jogos": "Jogos", "pct_com_first_pick": "% com first pick", "pct_lado_azul": "% lado azul",
        "pct_azul_e_first_pick": "% azul E first pick", "winrate_com_fp": "Vitórias com FP",
        "winrate_sem_fp": "Vitórias sem FP"})
    aba_tendencia(wb, "First pick", fp, {c: PCT for c in fp.columns if c not in ("Time", "Jogos")},
                  [22, 7, 14, 11, 16, 14, 14],
                  "Regra First Selection (2026): quem tem a prioridade escolhe lado OU ordem de pick; o outro time escolhe o que sobrou.")

    times = sorted(set(acoes["time"]), key=lambda t: (t not in DESTAQUE, t))
    for time in times:
        aba_time(wb, time, acoes, len(acoes), tend, jogadores)
    aba_acoes(wb, acoes)

    wb.save(SAIDA)
    print(f"planilha salva em {SAIDA} ({len(wb.sheetnames)} abas)")


if __name__ == "__main__":
    main()
