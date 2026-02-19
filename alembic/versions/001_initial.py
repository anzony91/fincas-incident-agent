"""Initial migration - create all tables

Revision ID: 001_initial
Revises: 
Create Date: 2026-02-16

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001_initial'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create tickets table
    op.create_table(
        'tickets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ticket_code', sa.String(length=12), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.Enum('NEW', 'NEEDS_INFO', 'VALIDATING', 'DISPATCHED', 'SCHEDULED', 
                                     'IN_PROGRESS', 'NEEDS_CONFIRMATION', 'WAITING_INVOICE', 
                                     'CLOSED', 'ESCALATED', name='ticketstatus'), nullable=False),
        sa.Column('category', sa.Enum('WATER', 'ELEVATOR', 'ELECTRICITY', 'GARAGE_DOOR', 
                                       'CLEANING', 'SECURITY', 'OTHER', name='category'), nullable=False),
        sa.Column('priority', sa.Enum('URGENT', 'HIGH', 'MEDIUM', 'LOW', name='priority'), nullable=False),
        sa.Column('reporter_email', sa.String(length=255), nullable=False),
        sa.Column('reporter_name', sa.String(length=255), nullable=True),
        sa.Column('assigned_provider_id', sa.Integer(), nullable=True),
        sa.Column('community_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_tickets_ticket_code', 'tickets', ['ticket_code'], unique=True)
    op.create_index('ix_tickets_reporter_email', 'tickets', ['reporter_email'], unique=False)
    
    # Create providers table
    op.create_table(
        'providers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('email', sa.String(length=255), nullable=False),
        sa.Column('phone', sa.String(length=50), nullable=True),
        sa.Column('category', sa.Enum('WATER', 'ELEVATOR', 'ELECTRICITY', 'GARAGE_DOOR', 
                                       'CLEANING', 'SECURITY', 'OTHER', name='category'), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, default=False),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('notes', sa.String(length=1000), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_providers_email', 'providers', ['email'], unique=False)
    op.create_index('ix_providers_category', 'providers', ['category'], unique=False)
    
    # Create emails table
    op.create_table(
        'emails',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('message_id', sa.String(length=255), nullable=False),
        sa.Column('subject', sa.String(length=500), nullable=False),
        sa.Column('body_text', sa.Text(), nullable=True),
        sa.Column('body_html', sa.Text(), nullable=True),
        sa.Column('from_address', sa.String(length=255), nullable=False),
        sa.Column('from_name', sa.String(length=255), nullable=True),
        sa.Column('to_address', sa.String(length=255), nullable=False),
        sa.Column('cc_addresses', sa.Text(), nullable=True),
        sa.Column('direction', sa.Enum('INBOUND', 'OUTBOUND', name='emaildirection'), nullable=False),
        sa.Column('in_reply_to', sa.String(length=255), nullable=True),
        sa.Column('references_header', sa.Text(), nullable=True),
        sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_emails_ticket_id', 'emails', ['ticket_id'], unique=False)
    op.create_index('ix_emails_message_id', 'emails', ['message_id'], unique=True)
    
    # Create events table
    op.create_table(
        'events',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('event_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('payload', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('created_by', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['ticket_id'], ['tickets.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_events_ticket_id', 'events', ['ticket_id'], unique=False)
    op.create_index('ix_events_event_type', 'events', ['event_type'], unique=False)
    
    # Create attachments table
    op.create_table(
        'attachments',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('email_id', sa.Integer(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('filepath', sa.String(length=500), nullable=False),
        sa.Column('content_type', sa.String(length=100), nullable=True),
        sa.Column('size_bytes', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['email_id'], ['emails.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_attachments_email_id', 'attachments', ['email_id'], unique=False)


def downgrade() -> None:
    op.drop_table('attachments')
    op.drop_table('events')
    op.drop_table('emails')
    op.drop_table('providers')
    op.drop_table('tickets')
    
    # Drop enums
    op.execute('DROP TYPE IF EXISTS ticketstatus')
    op.execute('DROP TYPE IF EXISTS category')
    op.execute('DROP TYPE IF EXISTS priority')
    op.execute('DROP TYPE IF EXISTS emaildirection')
