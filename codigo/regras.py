ROTAS = ["top", "jng", "mid", "bot", "sup"]

# Nome no Oracle's Elixir -> sigla mostrada no overlay
SIGLAS = {
    "Gen.G": "GEN", "Bilibili Gaming": "BLG", "Invictus Gaming": "IG", "T1": "T1",
    "Top Esports": "TES", "JD Gaming": "JDG", "Anyone's Legend": "AL", "Team WE": "WE",
    "Hanwha Life Esports": "HLE", "Dplus Kia": "DK", "G2 Esports": "G2", "Karmine Corp": "KC",
    "Movistar KOI": "MKOI", "Team Liquid": "TL", "Cloud9": "C9", "FURIA": "FUR", "LYON": "LYON",
    "CTBC Flying Oyster": "CFO", "Team Secret Whales": "TSW", "MVK Esports": "MVK", "LØS": "LØS",
}


def sigla(time):
    return SIGLAS.get(time, time)

# Ordem dos 20 passos do draft: (fase, tipo, quem).
# FP = time com o first pick, SP = o outro.
ORDEM_DRAFT = (
    [("ban1", "ban", q) for q in ["FP", "SP", "FP", "SP", "FP", "SP"]]
    + [("pick1", "pick", q) for q in ["FP", "SP", "SP", "FP", "FP", "SP"]]
    + [("ban2", "ban", q) for q in ["SP", "FP", "SP", "FP"]]
    + [("pick2", "pick", q) for q in ["SP", "FP", "FP", "SP"]]
)
assert len(ORDEM_DRAFT) == 20
