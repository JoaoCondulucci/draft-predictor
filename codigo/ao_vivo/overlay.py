"""overlay.py — janela transparente por cima do vídeo, que desenha o estado do draft.

- Sempre por cima, sem borda, o clique passa direto para o navegador (Windows).
- Excluída das capturas de tela (SetWindowDisplayAffinity), para o leitor não ler os
  próprios desenhos. Mesmo se isso falhar, nada é desenhado nas áreas de reconhecimento:
  nomes ficam na parte de baixo dos cards e o painel fica em cima da torcida.

Usado pelo draft_ao_vivo.py; não precisa rodar sozinho.
"""
import ctypes
import tkinter as tk


def _dpi_real():
    """Faz o Windows usar pixels reais nesta janela.

    Sem isso, num monitor com escala de 125%/150% o tkinter "aumenta" as coordenadas e o
    overlay fica deslocado em relação à área calibrada (que o mss mede em pixels reais).
    """
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass   # não é Windows

from leitura_tela.layout import ALTURA, LARGURA, slots

TRANSPARENTE = "#010101"
AMARELO, AZUL, VERMELHO = "#ffd400", "#3aa0ff", "#ff4a4a"
PAINEL_BG, CINZA = "#141414", "#a8a8a8"
PAINEL = (40, 250, 330, 456)     # x0, y0, x1, y1 no quadro 1280x720 (área da torcida)


class Overlay:
    def __init__(self, calib, obter_snapshot, intervalo_ms=250):
        self.calib = calib
        self.obter = obter_snapshot
        self.intervalo = intervalo_ms
        self.sx = calib["width"] / LARGURA
        self.sy = calib["height"] / ALTURA
        self.slots = slots()
        self._fechar = False

        _dpi_real()                    # antes de criar a janela
        self.root = tk.Tk()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.geometry(f"{calib['width']}x{calib['height']}+{calib['left']}+{calib['top']}")
        self.root.configure(bg=TRANSPARENTE)
        try:
            self.root.attributes("-transparentcolor", TRANSPARENTE)
        except tk.TclError:
            self.root.attributes("-alpha", 0.85)
        self.canvas = tk.Canvas(self.root, bg=TRANSPARENTE, highlightthickness=0,
                                width=calib["width"], height=calib["height"])
        self.canvas.pack()
        self.root.update_idletasks()
        self._ajustes_windows()

    def _ajustes_windows(self):
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
            GWL_EXSTYLE, WS_EX_LAYERED, WS_EX_TRANSPARENT = -20, 0x80000, 0x20
            estilo = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, estilo | WS_EX_LAYERED | WS_EX_TRANSPARENT)
            WDA_EXCLUDEFROMCAPTURE = 0x11
            if not user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE):
                print("[overlay] não deu para excluir da captura (Windows antigo?); seguindo assim mesmo")
        except AttributeError:
            pass   # não é Windows

    # ---------------------------------------------------- desenho

    def _p(self, x, y):
        return x * self.sx, y * self.sy

    def _ret(self, x0, y0, x1, y1, **kw):
        a, b = self._p(x0, y0)
        c, d = self._p(x1, y1)
        self.canvas.create_rectangle(a, b, c, d, **kw)

    def _txt(self, x, y, texto, tam=10, cor="white", peso="normal", ancora="nw"):
        a, b = self._p(x, y)
        self.canvas.create_text(a, b, text=texto, fill=cor, anchor=ancora,
                                font=("Segoe UI", max(7, int(tam * self.sy)), peso))

    def desenhar(self):
        if self._fechar:
            self.root.destroy()
            return
        self.canvas.delete("all")
        snap = self.obter()
        if snap:
            self._desenhar(snap)
        self.root.after(self.intervalo, self.desenhar)

    def _desenhar(self, s):
        # nomes dos picks já confirmados (parte de baixo do card: fora da área de leitura)
        for slot, nome in s["valores"].items():
            if "pick" not in slot or not nome:
                continue
            x0, y0, x1, y1 = self.slots[slot]
            self._ret(x0 + 3, y1 - 86, x1 - 3, y1 - 70, fill=PAINEL_BG, outline="")
            self._txt((x0 + x1) / 2, y1 - 78, nome, 8, "white", ancora="center")

        if s["passo"] is None:
            return
        slot = s["passo"]["slot"]
        x0, y0, x1, y1 = self.slots[slot]
        # contorno do próximo slot, POR FORA do slot (não atrapalha a leitura)
        if "ban" in slot:
            self._ret(x0 - 2, y0 - 3, x1 + 2, y1, outline=AMARELO, width=3)
        else:
            self._ret(x0 - 1, y0 - 1, x1 + 1, y1, outline=AMARELO, width=3)

        # painel com as previsões, em cima da torcida, do lado do time da vez
        px0, py0, px1, py1 = PAINEL
        if s["passo"]["lado"] == "red":
            px0, px1 = LARGURA - px1, LARGURA - px0
        self._ret(px0, py0, px1, py1, fill=PAINEL_BG, outline=AMARELO)
        cor_time = AZUL if s["passo"]["lado"] == "blue" else VERMELHO
        titulo = s["titulo"] or f"{s['passo']['tipo'].upper()} {s['passo']['n']}"
        self._txt(px0 + 10, py0 + 8, titulo, 12, cor_time, "bold")
        hover = f"selecionando: {s['hover']}" if s.get("hover") else "aguardando a escolha..."
        self._txt(px0 + 10, py0 + 30, hover, 8, CINZA)
        maior = max((p for _, p, _ in s["previsao"]), default=1) or 1
        for i, (campeao, prob, motivo) in enumerate(s["previsao"][:5]):
            y = py0 + 52 + i * 30
            self._txt(px0 + 10, y, campeao, 11, "white", "bold")
            barra = 70 * prob / maior
            self._ret(px0 + 170, y + 4, px0 + 170 + barra, y + 12, fill=AMARELO, outline="")
            self._txt(px1 - 10, y, f"{prob:.0%}", 9, "white", ancora="ne")
            self._txt(px0 + 10, y + 16, motivo if len(motivo) <= 56 else motivo[:55] + "…", 7, CINZA)

    def rodar(self):
        self.desenhar()
        self.root.mainloop()

    def fechar(self):
        # tkinter não pode ser chamado de outra thread: só marcamos, e o desenhar() fecha
        self._fechar = True
