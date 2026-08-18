-- Visual bot-builder tables: flows / flow_nodes / flow_edges
CREATE TABLE IF NOT EXISTS flows (
    id UUID PRIMARY KEY,
    bot_id UUID NOT NULL REFERENCES bots(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL DEFAULT 'Untitled Flow',
    published_version INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    graph_snapshot JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_flows_bot_id ON flows (bot_id);
CREATE INDEX IF NOT EXISTS ix_flows_is_active ON flows (is_active);

CREATE TABLE IF NOT EXISTS flow_nodes (
    id UUID PRIMARY KEY,
    flow_id UUID NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
    canvas_id VARCHAR(128) NOT NULL,
    type VARCHAR(64) NOT NULL DEFAULT 'text_message',
    position JSONB NOT NULL DEFAULT '{"x": 0, "y": 0}'::jsonb,
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    meta JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_flow_nodes_flow_canvas UNIQUE (flow_id, canvas_id)
);

CREATE INDEX IF NOT EXISTS ix_flow_nodes_flow_id ON flow_nodes (flow_id);
CREATE INDEX IF NOT EXISTS ix_flow_nodes_type ON flow_nodes (type);

CREATE TABLE IF NOT EXISTS flow_edges (
    id UUID PRIMARY KEY,
    flow_id UUID NOT NULL REFERENCES flows(id) ON DELETE CASCADE,
    canvas_id VARCHAR(128) NOT NULL,
    source VARCHAR(128) NOT NULL,
    target VARCHAR(128) NOT NULL,
    type VARCHAR(64) NOT NULL DEFAULT 'default',
    data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_flow_edges_flow_canvas UNIQUE (flow_id, canvas_id)
);

CREATE INDEX IF NOT EXISTS ix_flow_edges_flow_id ON flow_edges (flow_id);
CREATE INDEX IF NOT EXISTS ix_flow_edges_source ON flow_edges (source);
CREATE INDEX IF NOT EXISTS ix_flow_edges_target ON flow_edges (target);
