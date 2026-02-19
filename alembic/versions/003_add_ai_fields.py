"""Add AI fields to ticket

Revision ID: 003_add_ai_fields
Revises: 002_add_channel
Create Date: 2026-02-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '003_add_ai_fields'
down_revision = '002_add_channel'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add address field
    op.add_column('tickets', sa.Column('address', sa.String(500), nullable=True))
    
    # Add location_detail field
    op.add_column('tickets', sa.Column('location_detail', sa.String(500), nullable=True))
    
    # Add ai_context JSON field
    op.add_column('tickets', sa.Column('ai_context', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('tickets', 'ai_context')
    op.drop_column('tickets', 'location_detail')
    op.drop_column('tickets', 'address')
