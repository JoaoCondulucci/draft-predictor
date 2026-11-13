# LoL Draft Predictor

Lê a tela de draft da transmissão de LoL e mostra, por cima do vídeo e ao vivo, os campeões
mais prováveis para o próximo pick ou ban.

<!-- Arraste aqui o vídeo da ferramenta funcionando (no editor do GitHub ele vira um link) -->

Feito para o Worlds 2026. Projeto de fã, sem relação com a Riot Games.

## Resultados

Testado só em jogos que o modelo **não tinha visto**: em cada bloco de datas do fim do Worlds,
o modelo é treinado com os jogos anteriores e prevê os seguintes, como acontece numa final.
São 650 picks e 650 bans.

| O campeão real estava... | Top 1 | Top 3 | Top 5 |
| --- | --- | --- | --- |
| **Picks** — ranking aprendido | 27,5% | 54,3% | **68,2%** |
| Picks — só o modelo de contagem | 22,2% | 42,2% | 56,3% |
| **Bans** — ranking aprendido | 23,4% | 45,1% | **58,2%** |
| Bans — só o modelo de contagem | 19,8% | 39,8% | 53,4% |

Para comparar: chutar sempre o campeão mais popular ainda disponível acerta cerca de 23% dos picks
e 39% dos bans no top 5.

A leitura da tela acertou 20 de 20 ações nos replays de jogos do Worlds.

## Como funciona

**1. Leitura da tela** (`codigo/leitura_tela/`)
- Captura a área do vídeo 3 vezes por segundo (`mss`) e normaliza para 1280x720.
- **Bans:** compara cada ícone com os ícones oficiais do Data Dragon (*template matching*, OpenCV).
- **Picks:** acha pontos característicos da splash art de cada campeão (SIFT + teste de razão de Lowe).
- **De quem é a vez:** a cor da barra do timer (azul, vermelha ou ciano na fase de trocas).
- Uma máquina de estados decide quando cada passo terminou e corrige leituras duvidosas
  (releitura em rodízio, dedução do último pick pelos 5 cards depois da troca).

**2. Previsão** (`codigo/previsao/`)
- **Modelo de contagem**, com ~10 mil jogos de 2026 de todas as ligas: pool de cada jogador
  com peso para jogos recentes, ordem de rotas de cada time, sinergias e counters (lift),
  ameaça (o pool dos adversários) e histórico de bans de cada time por fase.
- **Ranking aprendido** (LightGBM LambdaRank) por cima: reordena os candidatos usando a nota
  do modelo de contagem e outros sinais, como taxas recentes de pick e ban, composição do time
  e o que cada time costuma banir. Treinado com o Worlds e os jogos da GEN e da BLG nas ligas deles.
- Respeita o **Fearless Draft**: campeões já usados na série nunca são sugeridos.

**3. Overlay** (`codigo/ao_vivo/`)
- Janela `tkinter` transparente por cima do vídeo, com chamadas à API do Windows (`ctypes`)
  para deixar o clique passar e esconder a janela das capturas, para o leitor não ler os
  próprios desenhos.

## Tecnologias

Python · pandas · SQLite · OpenCV · mss · LightGBM · tkinter · openpyxl.
Dados: [Oracle's Elixir](https://oracleselixir.com/). Imagens: Data Dragon (Riot).

## Como usar

Requer Windows (por causa do overlay) e o CSV de 2026 do Oracle's Elixir.

### Primeira vez

```
pip install -r requirements.txt
python main.py dados        # precisa do CSV em dados/bruto/
python main.py ddragon      # baixa as imagens dos campeões
python main.py ranking      # treina o ranking aprendido (refaça depois de cada "dados")
python main.py calibrar     # com o vídeo aberto: marque a área do vídeo
```

### Num jogo ao vivo

Na tela de draft: time da ESQUERDA = azul; o lado com "1ST PICK" embaixo do logo = `--fp`.

```
python main.py aovivo --fp red --azul GEN --vermelho BLG --nova-serie   # jogo 1 da série
python main.py aovivo --fp blue --azul BLG --vermelho GEN               # jogos 2 em diante
```

Comandos no terminal durante o draft: `fix red_pick2 kled`, `passo 9`, `estado`, `sair`.
`--sem-overlay` mostra só no terminal.

### Testes e análises

```
python main.py capturar                       # grava frames de um VOD em dados/tela/frames/
python main.py aovivo --replay dados/tela/frames --fp red --jogo LOLTMNT02_487213 --azul GEN --vermelho IG
python main.py aovivo --fp red --azul GEN --vermelho IG --fearless-de LOLTMNT02_488209   # VOD de um jogo específico
python main.py backtest --todos-os-times
python main.py avaliacao                      # gera resultados/avaliacao_worlds.xlsx
python main.py consulta "SELECT * FROM v_player_pool WHERE player = 'Chovy'"
```

## Estrutura

```
├── main.py            atalho para todos os comandos (rode sempre daqui)
├── requirements.txt
├── codigo/
│   ├── caminhos.py     onde fica cada pasta e arquivo
│   ├── regras.py       ordem do draft (First Selection) e rotas
│   ├── coleta/         CSV do Oracle's Elixir -> recortes -> draft.db (SQLite)
│   ├── leitura_tela/   calibração, captura e reconhecimento dos campeões (OpenCV)
│   ├── previsao/       modelo de contagem, features, ranking aprendido e backtest
│   ├── analise/        avaliação completa, tendências e planilha
│   └── ao_vivo/        acompanhamento do draft + overlay
├── dados/              gerado/baixado, fica fora do GitHub
│   ├── bruto/          coloque aqui o CSV do Oracle's Elixir
│   ├── ddragon/        imagens dos campeões
│   ├── modelos/        ranking aprendido
│   ├── tela/           calibração e frames de teste
│   └── draft.db
└── resultados/         avaliação e tendências (CSV e planilha)
```

## Limitações

- As posições dos slots são as da transmissão do Worlds 2026; outro layout exige ajustar `codigo/leitura_tela/layout.py`.
- Os números acima são do Worlds. Em VODs de jogos que já estão nos dados de treino, a previsão sai otimista.
- Bans continuam difíceis: dependem muito da preparação de cada time, que não aparece nos dados.
