"""add project fields for UI

Revision ID: add_project_fields_20251013
Revises: merge_20251013_01
Create Date: 2025-10-13 00:00:00.000000

Add columns used by the UI: is_active, repo_url, technologies (JSONB),
memories_count, members_count, last_active_at. Backfill counts from
existing tables.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy import text

# revision identifiers, used by Alembic.
revision = 'add_project_fields_20251013'
down_revision = 'merge_20251013_01'
branch_labels = None
depends_on = None


def upgrade():
    # Add columns
    op.add_column('projects', sa.Column('is_active', sa.Boolean(), server_default=sa.text('true'), nullable=False))
    op.add_column('projects', sa.Column('repo_url', sa.String(), nullable=True))
    op.add_column('projects', sa.Column('technologies', postgresql.JSONB(), nullable=True))
    op.add_column('projects', sa.Column('memories_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('projects', sa.Column('members_count', sa.Integer(), server_default='0', nullable=False))
    op.add_column('projects', sa.Column('last_active_at', sa.DateTime(timezone=True), nullable=True))

    # Backfill aggregated counts and last_active_at from related tables
    conn = op.get_bind()
    # Backfill memories_count
    conn.execute(text(
        """
        UPDATE projects
        SET memories_count = sub.cnt
        FROM (SELECT project_id, COUNT(*) AS cnt FROM memories GROUP BY project_id) AS sub
        WHERE projects.id = sub.project_id
        """
    ))

    # Backfill members_count
    conn.execute(text(
        """
        UPDATE projects
        SET members_count = sub.cnt
        FROM (SELECT project_id, COUNT(*) AS cnt FROM user_projects GROUP BY project_id) AS sub
        WHERE projects.id = sub.project_id
        """
    ))

    # Backfill last_active_at from search_logs (if present)
    conn.execute(text(
        """
        UPDATE projects
        SET last_active_at = sub.max_dt
        FROM (SELECT project_id, MAX(created_at) AS max_dt FROM search_logs GROUP BY project_id) AS sub
        WHERE projects.id = sub.project_id
        """
    ))


def downgrade():
    # Remove added columns (reverse of upgrade)
    op.drop_column('projects', 'last_active_at')
    op.drop_column('projects', 'members_count')
    op.drop_column('projects', 'memories_count')
    op.drop_column('projects', 'technologies')
    op.drop_column('projects', 'repo_url')
    op.drop_column('projects', 'is_active')
