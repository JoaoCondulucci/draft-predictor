"""layout.py — onde fica cada slot do draft na transmissão do Worlds 2026.

Todas as coordenadas estão num quadro PADRÃO de 1280x720. O vídeo capturado
é sempre redimensionado para esse tamanho antes de recortar os slots, então
tanto faz assistir em modo teatro, tela cheia ou outro monitor.

Medido a partir de um print do VOD GEN x IG (semifinal).
"""

LARGURA, ALTURA = 1280, 720

# Faixa dos bans (ícones quadrados)
BAN_Y0, BAN_Y1 = 472, 519
BAN_W = 48

# Cards de pick (arte vertical). Só a parte de cima é usada para reconhecer o
# campeão, porque embaixo ficam o nome do jogador e o ícone da rota.
CARD_Y0, CARD_Y1 = 527, 720
CARD_W = 1280 / 12          # 5 cards azuis + bloco central (2 cards) + 5 vermelhos
CARD_TOPO = 0.6             # fração do card usada no reconhecimento

# Barra do timer: a cor indica qual time está escolhendo
TIMER = (460, 520, 820, 527)


def _ret(x0, y0, x1, y1):
    return (int(round(x0)), int(round(y0)), int(round(x1)), int(round(y1)))


def slots():
    """Retorna {nome: (x0, y0, x1, y1)} para os 20 slots.

    Nomes: blue_ban1..5, red_ban1..5, blue_pick1..5, red_pick1..5.
    O número é a ordem DENTRO DO TIME (igual a ban1..5 / pick1..5 do Oracle's Elixir).
    - Bans azuis enchem da esquerda para o centro; bans vermelhos, da direita para o centro.
    - Picks dos dois lados enchem da esquerda para a direita (ordem top -> sup dos jogadores).
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
