"""Alembic: move per-session safety timeouts from client startup params to DB defaults.

``app/db/session.py`` used to send ``statement_timeout`` / ``lock_timeout`` /
``idle_in_transaction_session_timeout`` via asyncpg's ``server_settings``
(Postgres startup-packet parameters). That breaks the moment PgBouncer sits
in front of the app in transaction-pooling mode — PgBouncer only forwards a
fixed whitelist of startup parameters and rejects the rest with
``unsupported startup parameter: statement_timeout`` (confirmed live against
a real PgBouncer 1.22 instance). ``ALTER DATABASE ... SET`` applies the same
GUCs as a database-level default instead: Postgres attaches them to every new
backend session regardless of whether the client connected directly or
through a pooler, so behavior is identical either way.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "067_db_session_timeouts"
down_revision: Union[str, None] = "066_bot_auto_trial_default"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SETTINGS = {
    "statement_timeout": "30000",
    "lock_timeout": "10000",
    "idle_in_transaction_session_timeout": "60000",
}


def upgrade() -> None:
    bind = op.get_bind()
    dbname = bind.execute(sa.text("SELECT current_database()")).scalar_one()
    quoted = '"' + dbname.replace('"', '""') + '"'
    for key, value in _SETTINGS.items():
        bind.execute(sa.text(f"ALTER DATABASE {quoted} SET {key} = '{value}'"))


def downgrade() -> None:
    bind = op.get_bind()
    dbname = bind.execute(sa.text("SELECT current_database()")).scalar_one()
    quoted = '"' + dbname.replace('"', '""') + '"'
    for key in _SETTINGS:
        bind.execute(sa.text(f"ALTER DATABASE {quoted} RESET {key}"))
