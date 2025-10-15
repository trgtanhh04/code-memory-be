"""merge add_project_fields_20251013 and remove_apikey_from_project

Revision ID: merge_20251013_02
Revises: add_project_fields_20251013, remove_apikey_from_project
Create Date: 2025-10-13 00:30:00.000000

This is a merge revision created to unify two heads in the migration history.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'merge_20251013_02'
down_revision: Union[str, Sequence[str], None] = ('add_project_fields_20251013', 'remove_apikey_from_project')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Merge revision - no schema changes. This file exists only to unify heads.
    pass


def downgrade() -> None:
    # Downgrade intentionally left empty; reverting a merge is non-trivial.
    pass
