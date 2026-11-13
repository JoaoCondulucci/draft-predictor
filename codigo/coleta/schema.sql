-- schema.sql — banco do projeto de draft (SQLite)
-- Executado automaticamente pelo load.py a cada carga.

-- ============ TABELAS ============

CREATE TABLE games (
    game_id          TEXT PRIMARY KEY,          -- gameid do Oracle's Elixir
    series_id        TEXT NOT NULL,             -- montado no load.py (regra do game == 1)
    game_number      INTEGER NOT NULL CHECK (game_number BETWEEN 1 AND 5),
    league           TEXT NOT NULL,             -- 'LCK', 'LPL', 'WLDs'...
    split            TEXT,
    playoffs         INTEGER NOT NULL CHECK (playoffs IN (0, 1)),
    date_utc         TEXT NOT NULL,             -- ISO: '2026-11-08 00:00:51'
    patch            TEXT NOT NULL,             -- texto, para '26.20' não virar 26.2
    blue_team        TEXT NOT NULL,
    red_team         TEXT NOT NULL,
    first_pick_team  TEXT NOT NULL,
    winner           TEXT NOT NULL,
    duration_s       INTEGER,
    CHECK (blue_team <> red_team),
    CHECK (first_pick_team IN (blue_team, red_team)),
    CHECK (winner IN (blue_team, red_team))
);

CREATE INDEX idx_games_series ON games (series_id, game_number);

CREATE TABLE draft_actions (
    game_id      TEXT NOT NULL REFERENCES games (game_id),
    step         INTEGER NOT NULL CHECK (step BETWEEN 1 AND 20),   -- ordem global (reconstruída)
    team         TEXT NOT NULL,
    action_type  TEXT NOT NULL CHECK (action_type IN ('ban', 'pick')),
    phase        TEXT NOT NULL CHECK (phase IN ('ban1', 'pick1', 'ban2', 'pick2')),
    team_order   INTEGER NOT NULL CHECK (team_order BETWEEN 1 AND 5), -- ban1..5 / pick1..5 do OE
    champion     TEXT,                                             -- NULL = ban não feito
    PRIMARY KEY (game_id, step),
    UNIQUE (game_id, team, action_type, team_order)
);

CREATE INDEX idx_draft_champion ON draft_actions (champion);

CREATE TABLE player_games (
    game_id   TEXT NOT NULL REFERENCES games (game_id),
    team      TEXT NOT NULL,
    role      TEXT NOT NULL CHECK (role IN ('top', 'jng', 'mid', 'bot', 'sup')),
    player    TEXT NOT NULL,
    champion  TEXT NOT NULL,
    win       INTEGER NOT NULL CHECK (win IN (0, 1)),
    PRIMARY KEY (game_id, team, role)
);

CREATE INDEX idx_pg_player ON player_games (player, champion);

-- Picks de TODOS os jogos de 2026 (todas as ligas). Base das sinergias e counters:
-- com só GEN/BLG teríamos poucos pares; aqui são ~10 mil jogos.
CREATE TABLE todos_picks (
    game_id   TEXT NOT NULL,
    date_utc  TEXT NOT NULL,
    league    TEXT NOT NULL,
    side      TEXT NOT NULL CHECK (side IN ('Blue', 'Red')),
    team      TEXT NOT NULL,
    role      TEXT NOT NULL CHECK (role IN ('top', 'jng', 'mid', 'bot', 'sup')),
    champion  TEXT NOT NULL,
    win       INTEGER NOT NULL CHECK (win IN (0, 1)),
    team_order INTEGER CHECK (team_order BETWEEN 1 AND 5),   -- em que pick do time saiu
    player    TEXT,
    PRIMARY KEY (game_id, side, role)
);

CREATE INDEX idx_todos_data ON todos_picks (date_utc);

-- Bans de TODOS os jogos de 2026: histórico de bans de qualquer time (não só GEN/BLG/Worlds)
CREATE TABLE todos_bans (
    game_id    TEXT NOT NULL,
    date_utc   TEXT NOT NULL,
    league     TEXT NOT NULL,
    side       TEXT NOT NULL CHECK (side IN ('Blue', 'Red')),
    team       TEXT NOT NULL,
    team_order INTEGER NOT NULL CHECK (team_order BETWEEN 1 AND 5),  -- 1-3: 1ª fase, 4-5: 2ª fase
    champion   TEXT NOT NULL,
    PRIMARY KEY (game_id, side, team_order)
);

CREATE INDEX idx_bans_time ON todos_bans (team, date_utc);

-- ============ VIEWS ============

-- Para cada jogo: campeões já escolhidos nos jogos anteriores da mesma série (Fearless)
CREATE VIEW v_fearless_locked AS
SELECT g.game_id,
       d.champion
FROM games g
JOIN games prev
  ON prev.series_id = g.series_id
 AND prev.game_number < g.game_number
JOIN draft_actions d
  ON d.game_id = prev.game_id
 AND d.action_type = 'pick';

-- Pool de cada jogador: jogos, vitórias e recência por campeão
CREATE VIEW v_player_pool AS
SELECT
    pg.player,
    pg.team,
    pg.role,
    pg.champion,
    COUNT(*)                                           AS games,
    SUM(pg.win)                                        AS wins,
    ROUND(1.0 * SUM(pg.win) / COUNT(*), 3)             AS winrate,
    MAX(g.date_utc)                                    AS last_played,
    SUM(CASE WHEN g.league = 'WLDs' THEN 1 ELSE 0 END) AS games_worlds,
    SUM(CASE
            WHEN julianday((SELECT MAX(date_utc) FROM games))
               - julianday(g.date_utc) <= 60
            THEN 1 ELSE 0
        END)                                           AS games_last_60d
FROM player_games pg
JOIN games g ON g.game_id = pg.game_id
GROUP BY pg.player, pg.team, pg.role, pg.champion;

-- Em que momento do draft cada time pega/bane cada campeão
CREATE VIEW v_team_priority AS
SELECT
    d.team,
    d.champion,
    d.action_type,
    COUNT(*)              AS times,
    ROUND(AVG(d.step), 1) AS avg_step,
    MIN(d.step)           AS earliest_step
FROM draft_actions d
WHERE d.champion IS NOT NULL
GROUP BY d.team, d.champion, d.action_type;
