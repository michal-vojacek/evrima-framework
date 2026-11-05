"""Uploaded files (evrima.media): images with their variants and documents.

Revision ID: 9701535e0597
Revises: 89c66d9e367c
Create Date: 2026-10-15 15:18:52.154145

Rules: in PATCH and MINOR releases a migration only adds. New columns are
nullable or have a server default, so the previous code keeps working.
"""

from alembic import op
import sqlalchemy as sa


revision = '9701535e0597'
down_revision = '89c66d9e367c'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('evrima_media',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('kind', sa.String(length=10), nullable=False),
    sa.Column('stored_name', sa.String(length=64), nullable=False),
    sa.Column('extension', sa.String(length=8), nullable=False),
    sa.Column('content_type', sa.String(length=64), nullable=False),
    sa.Column('original_name', sa.String(length=255), nullable=False),
    sa.Column('size', sa.Integer(), nullable=False),
    sa.Column('width', sa.Integer(), nullable=True),
    sa.Column('height', sa.Integer(), nullable=True),
    sa.Column('variants', sa.String(length=64), nullable=False),
    sa.Column('uploaded_by', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('claimed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['uploaded_by'], ['evrima_administrators.id'], name=op.f('fk_evrima_media_uploaded_by_evrima_administrators'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_media')),
    sa.UniqueConstraint('stored_name', name=op.f('uq_evrima_media_stored_name'))
    )
    op.create_index(op.f('ix_evrima_media_created_at'), 'evrima_media', ['created_at'], unique=False)



def downgrade() -> None:
    op.drop_index(op.f('ix_evrima_media_created_at'), table_name='evrima_media')
    op.drop_table('evrima_media')
