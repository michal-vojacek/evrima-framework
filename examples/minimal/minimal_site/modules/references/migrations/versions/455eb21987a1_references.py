"""References module: the references table.

Revision ID: 455eb21987a1
Revises:
Create Date: 2026-10-15 17:00:00

The first revision of the module's own branch ("references"). It needs the
framework's media table for the image, hence depends_on.

Rules: in PATCH and MINOR releases a migration only adds. New columns are
nullable or have a server default, so the previous code keeps working.
"""

from alembic import op
import sqlalchemy as sa


revision = '455eb21987a1'
down_revision = None
branch_labels = ('references',)
depends_on = '9701535e0597'


def upgrade() -> None:
    op.create_table('references_items',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('client_name', sa.String(length=200), nullable=False),
    sa.Column('website_url', sa.String(length=500), nullable=False),
    sa.Column('description', sa.Text(), nullable=False),
    sa.Column('image_id', sa.Integer(), nullable=True),
    sa.Column('consent_on', sa.Date(), nullable=True),
    sa.Column('consent_proof', sa.String(length=500), nullable=False),
    sa.Column('published', sa.Boolean(), nullable=False),
    sa.Column('position', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('updated_at', sa.DateTime(), nullable=False),
    sa.CheckConstraint('NOT published OR consent_on IS NOT NULL', name=op.f('ck_references_items_published_needs_consent')),
    sa.ForeignKeyConstraint(['image_id'], ['evrima_media.id'], name=op.f('fk_references_items_image_id_evrima_media'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_references_items'))
    )
    op.create_index(op.f('ix_references_items_position'), 'references_items', ['position'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_references_items_position'), table_name='references_items')
    op.drop_table('references_items')
