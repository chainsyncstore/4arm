"""Phase 6: Anti-Detection & Hardening migration.

Creates device_fingerprints table and adds behavior_profile column to instances.

Revision ID: 001
Revises:
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '001'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema for Phase 6 anti-detection features."""
    
    # Create device_fingerprints table
    op.create_table(
        'device_fingerprints',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), onupdate=sa.text('now()'), nullable=False),
        sa.Column('instance_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('android_id', sa.String(length=16), nullable=False),
        sa.Column('device_model', sa.String(length=100), nullable=False),
        sa.Column('device_brand', sa.String(length=50), nullable=False),
        sa.Column('device_manufacturer', sa.String(length=50), nullable=False),
        sa.Column('build_fingerprint', sa.String(length=255), nullable=False),
        sa.Column('gsfid', sa.String(length=20), nullable=False),
        sa.Column('screen_density', sa.Integer(), nullable=False),
        sa.Column('locale', sa.String(length=10), nullable=False),
        sa.Column('timezone', sa.String(length=50), nullable=False),
        sa.Column('advertising_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['instance_id'], ['instances.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('instance_id')
    )
    
    # Add behavior_profile column to instances table
    op.add_column('instances', sa.Column('behavior_profile', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema - remove Phase 6 features."""
    
    # Drop behavior_profile column from instances
    op.drop_column('instances', 'behavior_profile')
    
    # Drop device_fingerprints table
    op.drop_table('device_fingerprints')
