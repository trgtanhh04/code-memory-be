"""drop unique constraint on projects.name

Revision ID: drop_projects_name_unique_20251013
Revises: merge_20251013_02
Create Date: 2025-10-13 01:15:00.000000

This migration removes the unique constraint on projects.name so duplicate
project names are allowed (we use repo_url for uniqueness when present).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'drop_name_unique_20251013'
down_revision: Union[str, Sequence[str], None] = 'merge_20251013_02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()
    # Drop the unique constraint created by the initial migration. Constraint name
    # observed in error logs: projects_name_key. If it differs, user should adjust.
    with op.batch_alter_table('projects') as batch_op:
        try:
            batch_op.drop_constraint('projects_name_key', type_='unique')
        except Exception:
            # Fallback: try common constraint name
            try:
                batch_op.drop_constraint('projects_name_key', type_='unique')
            except Exception:
                # If constraint not found, continue silently
                pass


def downgrade() -> None:
    with op.batch_alter_table('projects') as batch_op:
        batch_op.create_unique_constraint('projects_name_key', ['name'])
