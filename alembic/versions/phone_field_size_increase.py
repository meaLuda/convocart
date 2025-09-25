"""Increase phone number field size to support E164 format

Revision ID: phone_field_size_increase
Revises: c8418221aad8
Create Date: 2025-09-18 09:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'phone_field_size_increase'
down_revision: Union[str, None] = 'c8418221aad8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema to support E164 phone number format (+XXXXXXXXXXX)"""
    
    # Increase phone number field sizes from 20 to 25 characters
    # This supports full E164 format with country code (up to 15 digits + '+' sign)
    
    # Users table
    op.alter_column('users', 'phone_number',
                   existing_type=sa.VARCHAR(length=20),
                   type_=sa.VARCHAR(length=25),
                   existing_nullable=True)
    
    # Customers table
    op.alter_column('customers', 'phone_number',
                   existing_type=sa.VARCHAR(length=20),
                   type_=sa.VARCHAR(length=25),
                   existing_nullable=False)
    
    # Groups table (contact_phone)
    op.alter_column('groups', 'contact_phone',
                   existing_type=sa.VARCHAR(length=20),
                   type_=sa.VARCHAR(length=25),
                   existing_nullable=True)
    
    # Message delivery status table
    op.alter_column('message_delivery_status', 'recipient_phone',
                   existing_type=sa.VARCHAR(length=20),
                   type_=sa.VARCHAR(length=25),
                   existing_nullable=False)
    
    # Media attachments table
    op.alter_column('media_attachments', 'from_number',
                   existing_type=sa.VARCHAR(length=20),
                   type_=sa.VARCHAR(length=25),
                   existing_nullable=True)


def downgrade() -> None:
    """Downgrade schema back to original phone field sizes"""
    
    # Revert phone number field sizes back to 20 characters
    # WARNING: This may truncate data if any phone numbers are longer than 20 chars
    
    # Media attachments table
    op.alter_column('media_attachments', 'from_number',
                   existing_type=sa.VARCHAR(length=25),
                   type_=sa.VARCHAR(length=20),
                   existing_nullable=True)
    
    # Message delivery status table
    op.alter_column('message_delivery_status', 'recipient_phone',
                   existing_type=sa.VARCHAR(length=25),
                   type_=sa.VARCHAR(length=20),
                   existing_nullable=False)
    
    # Groups table (contact_phone)
    op.alter_column('groups', 'contact_phone',
                   existing_type=sa.VARCHAR(length=25),
                   type_=sa.VARCHAR(length=20),
                   existing_nullable=True)
    
    # Customers table
    op.alter_column('customers', 'phone_number',
                   existing_type=sa.VARCHAR(length=25),
                   type_=sa.VARCHAR(length=20),
                   existing_nullable=False)
    
    # Users table
    op.alter_column('users', 'phone_number',
                   existing_type=sa.VARCHAR(length=25),
                   type_=sa.VARCHAR(length=20),
                   existing_nullable=True)