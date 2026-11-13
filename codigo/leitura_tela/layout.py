"""Posição de cada slot do draft na transmissão do Worlds 2026.

As coordenadas estão num quadro padrão de 1280x720: todo frame capturado é redimensionado
para esse tamanho antes de recortar os slots.
"""

LARGURA, ALTURA = 1280, 720

BAN_Y0, BAN_Y1 = 472, 519
BAN_W = 48

# Cards de pick: só a parte de cima reconhece o campeão (embaixo ficam o jogador e a rota)
CARD_Y0, CARD_Y1 = 527, 720
CARD_W = 1280 / 12          # 5 cards azuis + bloco central (2 cards) + 5 vermelhos
CARD_TOPO = 0.6

# A cor da barra do timer indica qual time está escolhendo
TIMER = (460, 520, 820, 527)


def _ret(x0, y0, x1, y1):
    return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))


def slots():
    """{nome: (x0, y0, x1, y1)} dos 20 slots, ex.: blue_ban1, red_pick5.

    O número é a ordem dentro do time (ban1..5 / pick1..5 do Oracle's Elixir). Os bans
    enchem das pontas para o centro; os picks, da esquerda para a direita.
    """
    s = {}
    for i in range(5):
        s[f"blue_ban{i + 1}"] = _ret(i * BAN_W, BAN_Y0, (i + 1) * BAN_W, BAN_Y1)
        s[f"red_ban{i + 1}"] = _ret(LARGURA - (i + 1) * BAN_W, BAN_Y0,
                                    LARGURA - i * BAN_W, BAN_Y1)
        s[f"blue_pick{i + 1}"] = _ret(i * CARD_W, CARD_Y0, (i + 1) * CARD_W, CARD_Y1)
        s[f"red_pick{i + 1}"] = _ret((7 + i) * CARD_W, CARD_Y0, (8 + i) * CARD_W, CARD_Y1)
    return s


def regiao_reconhecimento(nome, ret):
    """Para picks, devolve só o topo do card; para bans, o quadrado inteiro."""
    x0, y0, x1, y1 = ret
    if "pick" in nome:
        return (x0, y0, x1, int(y0 + (y1 - y0) * CARD_TOPO))
    return ret
