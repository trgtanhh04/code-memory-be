"""Enable pgvector extension and update embeddings column

Revision ID: add_pgvector_support
Revises: 694a99143351
Create Date: 2025-10-02 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector

# revision identifiers, used by Alembic.
revision = 'add_pgvector_support'
down_revision = '694a99143351'  # Replace với revision ID mới nhất
branch_labels = None
depends_on = None

def upgrade():
    # Enable pgvector extension
    op.execute('CREATE EXTENSION IF NOT EXISTS vector')
    
    # Drop old embedding column if exists
    op.drop_column('memories', 'embedding')
    
    # Add new pgvector embedding column (768 dimensions for text-embedding-004)
    op.add_column('memories', sa.Column('embedding', Vector(768), nullable=True))
    
    # Create index for fast similarity search
    # "CREATE INDEX CONCURRENTLY" cannot be run inside a transaction block.
    # Use Alembic's autocommit_block to run it outside the transaction so Postgres accepts it.
    with op.get_context().autocommit_block():
        op.execute(
            'CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_memories_embedding '
            'ON memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)'
        )

def downgrade():
    # Drop pgvector index
    op.execute('DROP INDEX IF EXISTS idx_memories_embedding')
    
    # Drop pgvector column
    op.drop_column('memories', 'embedding')
    
    # Add back old embedding column
    op.add_column('memories', sa.Column('embedding', sa.ARRAY(sa.Float), nullable=True))
    
    # Drop pgvector extension (careful - only if no other tables use it)
    # op.execute('DROP EXTENSION IF EXISTS vector')