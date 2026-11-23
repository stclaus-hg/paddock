-- Paddock structured store. Idempotent: safe to run on every start.

CREATE EXTENSION IF NOT EXISTS vector;  -- embeddings arrive in stage 2

DO $$
BEGIN
    CREATE TYPE session_type AS ENUM ('race', 'sprint');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$
BEGIN
    CREATE TYPE result_status AS ENUM ('CLASSIFIED', 'RET', 'NC', 'DNS', 'DNQ', 'DSQ', 'EXC', 'WD');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS seasons (
    year        int PRIMARY KEY,
    wiki_title  text NOT NULL,
    revid       bigint NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id           serial PRIMARY KEY,
    season_year  int NOT NULL REFERENCES seasons (year),
    round        int NOT NULL,
    wiki_title   text NOT NULL UNIQUE,
    revid        bigint NOT NULL,
    UNIQUE (season_year, round)
);

-- wiki_title NULL: the rider has no Wikipedia article. revid NULL: no article pinned in the snapshot.
CREATE TABLE IF NOT EXISTS riders (
    id          serial PRIMARY KEY,
    name        text NOT NULL,
    wiki_title  text UNIQUE,
    revid       bigint
);

CREATE TABLE IF NOT EXISTS results (
    id           serial PRIMARY KEY,
    event_id     int NOT NULL REFERENCES events (id),
    rider_id     int NOT NULL REFERENCES riders (id),
    session      session_type NOT NULL,
    position     int,
    status       result_status NOT NULL,
    grid         int,
    points       numeric(5, 1) NOT NULL DEFAULT 0,
    laps         int,
    team         text NOT NULL,
    constructor  text NOT NULL,
    bike_number  int,
    UNIQUE (event_id, session, rider_id),
    CHECK ((status = 'CLASSIFIED') = (position IS NOT NULL))
);

CREATE TABLE IF NOT EXISTS bio_sections (
    id            serial PRIMARY KEY,
    rider_id      int NOT NULL REFERENCES riders (id),
    ordinal       int NOT NULL,
    heading_path  text[] NOT NULL,
    text          text NOT NULL,
    year_from     int,
    year_to       int,
    team          text,
    source_url    text NOT NULL,
    UNIQUE (rider_id, ordinal)
);

CREATE OR REPLACE VIEW rider_seasons AS
SELECT DISTINCT r.rider_id, e.season_year, r.team, r.constructor
FROM results r
JOIN events e ON e.id = r.event_id
WHERE r.session = 'race';
