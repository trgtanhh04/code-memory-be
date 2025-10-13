from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = "remove_apikey_from_project"
down_revision = "merge_20251013_01"
branch_labels = None
depends_on = None


def _column_exists(connection, table_name: str, column_name: str) -> bool:
    insp = Inspector.from_engine(connection)
    cols = [c['name'] for c in insp.get_columns(table_name)] if insp.has_table(table_name) else []
    return column_name in cols


def upgrade():
    conn = op.get_bind()

    # Create a backup table to preserve any existing api_keys.project_id values
    op.create_table(
        'api_key_project_backup',
        sa.Column('api_key_id', sa.UUID(), primary_key=True),
        sa.Column('project_id', sa.UUID(), nullable=True),
    )

    # If the column exists, copy values into backup and then drop the column.
    try:
        if _column_exists(conn, 'api_keys', 'project_id'):
            conn.execute(
                sa.text(
                    "INSERT INTO api_key_project_backup (api_key_id, project_id) SELECT id, project_id FROM api_keys WHERE project_id IS NOT NULL"
                )
            )
            # Drop the column safely
            op.drop_column('api_keys', 'project_id')
    except Exception:
        # If anything goes wrong, do not leave a half-applied state; re-raise after logging
        raise


def downgrade():
    conn = op.get_bind()

    # If backup table exists, restore project_id into api_keys (re-create column if needed)
    insp = Inspector.from_engine(conn)
    if insp.has_table('api_key_project_backup'):
        # Add column back if it doesn't exist
        if not _column_exists(conn, 'api_keys', 'project_id'):
            op.add_column('api_keys', sa.Column('project_id', sa.UUID(), nullable=True))

        # Restore values
        conn.execute(
            sa.text(
                "UPDATE api_keys AS a SET project_id = b.project_id FROM api_key_project_backup AS b WHERE a.id = b.api_key_id"
            )
        )

        # Optionally drop backup table
        op.drop_table('api_key_project_backup')