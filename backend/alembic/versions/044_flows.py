"""Alembic: organization-scoped Flow Builder graphs (flows / nodes / edges).

Revision ID: 044_flows
Revises: 043_omnichannel_messages
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "044_flows"
down_revision: Union[str, None] = "043_omnichannel_messages"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _tables() -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return set(inspector.get_table_names())


def _columns(table: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if table not in inspector.get_table_names():
        return set()
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    tables = _tables()

    if "flows" not in tables:
        op.create_table(
            "flows",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "organization_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("companies.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "bot_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("bots.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("name", sa.String(length=255), nullable=False, server_default="Untitled Flow"),
            sa.Column("published_version", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("true"),
            ),
            sa.Column(
                "graph_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )
        op.create_index("ix_flows_organization_id", "flows", ["organization_id"])
        op.create_index("ix_flows_bot_id", "flows", ["bot_id"])
    else:
        cols = _columns("flows")
        if "organization_id" not in cols:
            op.add_column(
                "flows",
                sa.Column(
                    "organization_id",
                    postgresql.UUID(as_uuid=True),
                    sa.ForeignKey("companies.id", ondelete="CASCADE"),
                    nullable=True,
                ),
            )
            op.create_index("ix_flows_organization_id", "flows", ["organization_id"])
        if "bot_id" in cols:
            # Allow org-only flows without a bot.
            op.alter_column("flows", "bot_id", existing_type=postgresql.UUID(as_uuid=True), nullable=True)

    tables = _tables()
    if "flow_nodes" not in tables:
        op.create_table(
            "flow_nodes",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "flow_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("flows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("canvas_id", sa.String(length=128), nullable=False),
            sa.Column("type", sa.String(length=64), nullable=False, server_default="text_message"),
            sa.Column(
                "position",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{\"x\": 0, \"y\": 0}'::jsonb"),
            ),
            sa.Column(
                "data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "meta",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("flow_id", "canvas_id", name="uq_flow_nodes_flow_canvas"),
        )
        op.create_index("ix_flow_nodes_flow_id", "flow_nodes", ["flow_id"])

    if "flow_edges" not in tables:
        op.create_table(
            "flow_edges",
            sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
            sa.Column(
                "flow_id",
                postgresql.UUID(as_uuid=True),
                sa.ForeignKey("flows.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("canvas_id", sa.String(length=128), nullable=False),
            sa.Column("source", sa.String(length=128), nullable=False),
            sa.Column("target", sa.String(length=128), nullable=False),
            sa.Column("type", sa.String(length=64), nullable=False, server_default="default"),
            sa.Column(
                "data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.UniqueConstraint("flow_id", "canvas_id", name="uq_flow_edges_flow_canvas"),
        )
        op.create_index("ix_flow_edges_flow_id", "flow_edges", ["flow_id"])


def downgrade() -> None:
    tables = _tables()
    if "flow_edges" in tables:
        op.drop_index("ix_flow_edges_flow_id", table_name="flow_edges")
        op.drop_table("flow_edges")
    if "flow_nodes" in tables:
        op.drop_index("ix_flow_nodes_flow_id", table_name="flow_nodes")
        op.drop_table("flow_nodes")
    if "flows" in tables:
        cols = _columns("flows")
        if "organization_id" in cols:
            op.drop_index("ix_flows_organization_id", table_name="flows")
            op.drop_column("flows", "organization_id")
        # Do not drop the whole flows table on downgrade if it pre-existed for bot builder.
