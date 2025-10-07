"""merge heads 9f1b2c3d4e5f and add_pgvector_support

Revision ID: merge_9f1b2c3d4e5f_addpg
Revises: 9f1b2c3d4e5f, add_pgvector_support
Create Date: 2025-10-07 00:30:00.000000

This is a merge revision created to unify two heads in the migration history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'merge_9f1b2c3d4e5f_addpg'
down_revision: Union[str, Sequence[str], None] = ('9f1b2c3d4e5f', 'add_pgvector_support')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revision - no schema changes. This file exists only to unify heads.
    pass


def downgrade() -> None:
    # Downgrade intentionally left empty; reverting a merge is non-trivial.
    pass
