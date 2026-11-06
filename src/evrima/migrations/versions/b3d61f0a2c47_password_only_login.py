"""Password-only admin login: drop the e-mailed PIN, trusted devices and TOTP.

Revision ID: b3d61f0a2c47
Revises: 9701535e0597
Create Date: 2026-11-06 18:00:00

Decided by Michal on 2026-11-06 (docs/framework.md, "Admin login"). This
migration removes data and columns, which the rules allow only before 1.0.0
or in a MAJOR release; nothing has been released yet.
"""

from alembic import op
import sqlalchemy as sa


revision = 'b3d61f0a2c47'
down_revision = '9701535e0597'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index(op.f('ix_evrima_trusted_devices_administrator_id'), table_name='evrima_trusted_devices')
    op.drop_table('evrima_trusted_devices')
    op.drop_index(op.f('ix_evrima_login_challenges_administrator_id'), table_name='evrima_login_challenges')
    op.drop_table('evrima_login_challenges')
    # Batch mode: SQLite (development, tests) cannot drop columns in place.
    with op.batch_alter_table('evrima_administrators') as batch:
        batch.drop_column('totp_last_step')
        batch.drop_column('totp_pending_secret')
        batch.drop_column('totp_secret')


def downgrade() -> None:
    with op.batch_alter_table('evrima_administrators') as batch:
        batch.add_column(sa.Column('totp_secret', sa.Text(), nullable=True))
        batch.add_column(sa.Column('totp_pending_secret', sa.Text(), nullable=True))
        batch.add_column(sa.Column('totp_last_step', sa.Integer(), nullable=True))
    op.create_table('evrima_login_challenges',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('administrator_id', sa.Integer(), nullable=False),
    sa.Column('pin_hash', sa.String(length=64), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('attempts', sa.Integer(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['administrator_id'], ['evrima_administrators.id'], name=op.f('fk_evrima_login_challenges_administrator_id_evrima_administrators'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_login_challenges'))
    )
    op.create_index(op.f('ix_evrima_login_challenges_administrator_id'), 'evrima_login_challenges', ['administrator_id'], unique=False)
    op.create_table('evrima_trusted_devices',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('administrator_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('last_used_at', sa.DateTime(), nullable=True),
    sa.Column('user_agent', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['administrator_id'], ['evrima_administrators.id'], name=op.f('fk_evrima_trusted_devices_administrator_id_evrima_administrators'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_trusted_devices')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_evrima_trusted_devices_token_hash'))
    )
    op.create_index(op.f('ix_evrima_trusted_devices_administrator_id'), 'evrima_trusted_devices', ['administrator_id'], unique=False)
