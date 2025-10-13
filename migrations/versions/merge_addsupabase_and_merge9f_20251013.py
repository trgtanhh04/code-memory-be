"""merge add_supabase_user_id_20251009 and merge_9f1b2c3d4e5f_addpg

Revision ID: merge_addsupabase_and_merge9f_20251013
Revises: add_supabase_user_id_20251009, merge_9f1b2c3d4e5f_addpg
Create Date: 2025-10-13 00:00:00.000000

This is a merge revision created to unify two heads in the migration history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'merge_20251013_01'
down_revision: Union[str, Sequence[str], None] = ('add_supabase_user_id_20251009', 'merge_9f1b2c3d4e5f_addpg')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revision - no schema changes. This file exists only to unify heads.
    pass


def downgrade() -> None:
    # Downgrade intentionally left empty; reverting a merge is non-trivial.
    pass
