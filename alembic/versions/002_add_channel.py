"""add channel and reporter_phone to tickets

Revision ID: 002
Revises: 001
Create Date: 2026-02-19

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add channel enum type and column
    channel_enum = sa.Enum('EMAIL', 'WHATSAPP', 'SMS', 'WEB', 'PHONE', name='channel')
    channel_enum.create(op.get_bind(), checkfirst=True)
    
    op.add_column('tickets', sa.Column('channel', channel_enum, nullable=True))
    op.add_column('tickets', sa.Column('reporter_phone', sa.String(50), nullable=True))
    
    # Set default value for existing rows
    op.execute("UPDATE tickets SET channel = 'EMAIL' WHERE channel IS NULL")
    
    # Make column non-nullable after setting defaults
    op.alter_column('tickets', 'channel', nullable=False)


def downgrade() -> None:
    op.drop_column('tickets', 'reporter_phone')
    op.drop_column('tickets', 'channel')
    
    # Drop enum type
    channel_enum = sa.Enum('EMAIL', 'WHATSAPP', 'SMS', 'WEB', 'PHONE', name='channel')
    channel_enum.drop(op.get_bind(), checkfirst=True)
