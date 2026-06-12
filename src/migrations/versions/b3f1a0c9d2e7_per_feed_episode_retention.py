"""per feed episode retention count

Revision ID: b3f1a0c9d2e7
Revises: 2e25a15d11de
Create Date: 2026-06-10 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "b3f1a0c9d2e7"
down_revision = "2e25a15d11de"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("episode_retention_count", sa.Integer(), nullable=True)
        )


def downgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_column("episode_retention_count")
