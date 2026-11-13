# draftanalyse — previsão de draft de LoL ao vivo

Lê a tela de draft da transmissão (Worlds 2026) e mostra, por cima do vídeo, os campeões
mais prováveis para o próximo pick/ban. Dados: Oracle's Elixir. Imagens: Data Dragon (Riot).

Projeto de fã, sem relação com a Riot Games.

## Estrutura

```
draftanalyse/
├── main.py            atalho para todos os comandos (rode sempre daqui)
├── requirements.txt
├── codigo/
│   ├── caminhos.py     onde fica cada pasta/arquivo (mude só aqui)
│   ├── regras.py       ordem do draft (First Selection) e rotas
│   ├── coleta/         CSV do Oracle's Elixir -> recortes -> draft.db (SQLite)
│   ├── leitura_tela/   calibração, captura, reconhecimento dos campeões (OpenCV)
│   ├── previsao/       modelo de previsão + backtest
│   ├── analise/        avaliação completa, tendências e planilha
│   └── ao_vivo/        acompanhamento do draft + overlay
├── dados/              gerado/baixado (não vai pro GitHub)
│   ├── bruto/          coloque aqui o CSV do Oracle's Elixir
│   ├── csvs/           recortes
│   ├── ddragon/        imagens dos campeões
│   ├── tela/           calibracao.json, previa_slots.png e frames/ de teste
│   ├── draft.db
│   └── serie_atual.json  campeões bloqueados pelo Fearless na série em andamento
└── resultados/         acoes.csv, tend_*.csv, avaliacao_worlds.xlsx
```

## Primeira vez

```
pip install -r requirements.txt
python main.py dados        # precisa do CSV em dados/bruto/
python main.py ddragon      # baixa as imagens dos campeões
python main.py calibrar     # com o vídeo aberto: marque a área do vídeo
python main.py ranking      # treina o ranking aprendido (depois de cada "dados")
```

## No dia (cada jogo da série)

Na tela de draft: time da ESQUERDA = azul; o lado com "1ST PICK" embaixo do logo = `--fp`.

```
python main.py aovivo --fp red --azul GEN --vermelho BLG --nova-serie   # jogo 1
python main.py aovivo --fp blue --azul BLG --vermelho GEN               # jogos 2 em diante
```

Comandos no terminal durante o draft: `fix red_pick2 kled`, `passo 9`, `estado`, `sair`.
`--sem-overlay` mostra só no terminal.

## Testes e análises

```
python main.py capturar                       # grava frames de um VOD em dados/tela/frames/
python main.py aovivo --replay dados/tela/frames --fp red --jogo LOLTMNT02_487213 --azul GEN --vermelho IG
python main.py aovivo --fp red --azul GEN --vermelho IG --fearless-de LOLTMNT02_488209   # VOD do jogo 2
python main.py backtest --todos-os-times
python main.py avaliacao                      # gera resultados/avaliacao_worlds.xlsx
python main.py consulta "SELECT * FROM v_player_pool WHERE player = 'Chovy'"
```
