"""Add reporters table and expand providers

Revision ID: 004_reporters_providers
Revises: 003_add_ai_fields
Create Date: 2026-02-20

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_reporters_providers'
down_revision: Union[str, None] = '003_add_ai_fields'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create reporters table
    op.create_table(
        'reporters',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('email', sa.String(255), nullable=False, unique=True, index=True),
        sa.Column('phone', sa.String(50), nullable=True),
        sa.Column('phone_secondary', sa.String(50), nullable=True),
        sa.Column('community_name', sa.String(255), nullable=True, index=True),
        sa.Column('address', sa.String(500), nullable=True),
        sa.Column('floor_door', sa.String(50), nullable=True),
        sa.Column('dni_nif', sa.String(20), nullable=True),
        sa.Column('role', sa.String(50), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('preferred_contact_method', sa.String(50), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=False),
    )
    
    # Add new columns to providers table
    op.add_column('providers', sa.Column('company_name', sa.String(255), nullable=True))
    op.add_column('providers', sa.Column('cif_nif', sa.String(20), nullable=True))
    op.add_column('providers', sa.Column('phone_secondary', sa.String(50), nullable=True))
    op.add_column('providers', sa.Column('phone_emergency', sa.String(50), nullable=True))
    op.add_column('providers', sa.Column('contact_person', sa.String(255), nullable=True))
    op.add_column('providers', sa.Column('contact_position', sa.String(100), nullable=True))
    op.add_column('providers', sa.Column('address', sa.String(500), nullable=True))
    op.add_column('providers', sa.Column('city', sa.String(100), nullable=True))
    op.add_column('providers', sa.Column('postal_code', sa.String(10), nullable=True))
    op.add_column('providers', sa.Column('specialties', sa.String(500), nullable=True))
    op.add_column('providers', sa.Column('service_areas', sa.String(500), nullable=True))
    op.add_column('providers', sa.Column('availability_hours', sa.String(255), nullable=True))
    op.add_column('providers', sa.Column('has_emergency_service', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('providers', sa.Column('rating', sa.Float(), nullable=True))
    op.add_column('providers', sa.Column('hourly_rate', sa.Float(), nullable=True))
    op.add_column('providers', sa.Column('payment_terms', sa.String(255), nullable=True))
    op.add_column('providers', sa.Column('bank_account', sa.String(34), nullable=True))
    
    # Alter notes column to Text type (was String(1000))
    op.alter_column('providers', 'notes',
                    existing_type=sa.String(1000),
                    type_=sa.Text(),
                    existing_nullable=True)


def downgrade() -> None:
    # Remove new columns from providers
    op.drop_column('providers', 'bank_account')
    op.drop_column('providers', 'payment_terms')
    op.drop_column('providers', 'hourly_rate')
    op.drop_column('providers', 'rating')
    op.drop_column('providers', 'has_emergency_service')
    op.drop_column('providers', 'availability_hours')
    op.drop_column('providers', 'service_areas')
    op.drop_column('providers', 'specialties')
    op.drop_column('providers', 'postal_code')
    op.drop_column('providers', 'city')
    op.drop_column('providers', 'address')
    op.drop_column('providers', 'contact_position')
    op.drop_column('providers', 'contact_person')
    op.drop_column('providers', 'phone_emergency')
    op.drop_column('providers', 'phone_secondary')
    op.drop_column('providers', 'cif_nif')
    op.drop_column('providers', 'company_name')
    
    # Revert notes column type
    op.alter_column('providers', 'notes',
                    existing_type=sa.Text(),
                    type_=sa.String(1000),
                    existing_nullable=True)
    
    # Drop reporters table
    op.drop_table('reporters')
