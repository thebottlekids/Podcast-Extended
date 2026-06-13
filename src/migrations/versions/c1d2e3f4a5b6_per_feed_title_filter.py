"""per feed title filter terms

Revision ID: c1d2e3f4a5b6
Revises: b3f1a0c9d2e7
Create Date: 2026-06-12 00:00:00.000000

"""

import sqlalchemy as sa
from alembic import op

revision = "c1d2e3f4a5b6"
down_revision = "b3f1a0c9d2e7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.add_column(sa.Column("title_filter_include", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("title_filter_exclude", sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table("feed", schema=None) as batch_op:
        batch_op.drop_column("title_filter_exclude")
        batch_op.drop_column("title_filter_include")
