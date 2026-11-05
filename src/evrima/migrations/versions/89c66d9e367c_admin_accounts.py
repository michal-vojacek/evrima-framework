"""Admin accounts: administrators, sessions, trusted devices, login PINs,
lockout counters, one-time links and the audit log.

Revision ID: 89c66d9e367c
Revises: 
Create Date: 2026-10-14 15:29:52.399976

Rules: in PATCH and MINOR releases a migration only adds. New columns are
nullable or have a server default, so the previous code keeps working.
"""

from alembic import op
import sqlalchemy as sa


revision = '89c66d9e367c'
down_revision = None
branch_labels = ('evrima',)
depends_on = None


def upgrade() -> None:
    op.create_table('evrima_administrators',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('password_hash', sa.String(length=255), nullable=True),
    sa.Column('language', sa.String(length=5), nullable=False),
    sa.Column('totp_secret', sa.Text(), nullable=True),
    sa.Column('totp_pending_secret', sa.Text(), nullable=True),
    sa.Column('totp_last_step', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('password_changed_at', sa.DateTime(), nullable=True),
    sa.Column('last_login_at', sa.DateTime(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_administrators')),
    sa.UniqueConstraint('email', name=op.f('uq_evrima_administrators_email'))
    )
    op.create_table('evrima_login_failures',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('count', sa.Integer(), nullable=False),
    sa.Column('last_failed_at', sa.DateTime(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_login_failures')),
    sa.UniqueConstraint('key', name=op.f('uq_evrima_login_failures_key'))
    )
    op.create_table('evrima_account_links',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('administrator_id', sa.Integer(), nullable=False),
    sa.Column('purpose', sa.String(length=10), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('expires_at', sa.DateTime(), nullable=False),
    sa.Column('used_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['administrator_id'], ['evrima_administrators.id'], name=op.f('fk_evrima_account_links_administrator_id_evrima_administrators'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_account_links')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_evrima_account_links_token_hash'))
    )
    op.create_index(op.f('ix_evrima_account_links_administrator_id'), 'evrima_account_links', ['administrator_id'], unique=False)

    op.create_table('evrima_admin_sessions',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('administrator_id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('last_seen_at', sa.DateTime(), nullable=False),
    sa.Column('user_agent', sa.String(length=200), nullable=False),
    sa.ForeignKeyConstraint(['administrator_id'], ['evrima_administrators.id'], name=op.f('fk_evrima_admin_sessions_administrator_id_evrima_administrators'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_admin_sessions')),
    sa.UniqueConstraint('token_hash', name=op.f('uq_evrima_admin_sessions_token_hash'))
    )
    op.create_index(op.f('ix_evrima_admin_sessions_administrator_id'), 'evrima_admin_sessions', ['administrator_id'], unique=False)

    op.create_table('evrima_audit_log',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('administrator_id', sa.Integer(), nullable=True),
    sa.Column('email', sa.String(length=254), nullable=False),
    sa.Column('action', sa.String(length=60), nullable=False),
    sa.Column('detail', sa.Text(), nullable=False),
    sa.Column('ip', sa.String(length=45), nullable=False),
    sa.ForeignKeyConstraint(['administrator_id'], ['evrima_administrators.id'], name=op.f('fk_evrima_audit_log_administrator_id_evrima_administrators'), ondelete='SET NULL'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_evrima_audit_log'))
    )
    op.create_index(op.f('ix_evrima_audit_log_created_at'), 'evrima_audit_log', ['created_at'], unique=False)

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



def downgrade() -> None:
    op.drop_index(op.f('ix_evrima_trusted_devices_administrator_id'), table_name='evrima_trusted_devices')
    op.drop_table('evrima_trusted_devices')
    op.drop_index(op.f('ix_evrima_login_challenges_administrator_id'), table_name='evrima_login_challenges')
    op.drop_table('evrima_login_challenges')
    op.drop_index(op.f('ix_evrima_audit_log_created_at'), table_name='evrima_audit_log')
    op.drop_table('evrima_audit_log')
    op.drop_index(op.f('ix_evrima_admin_sessions_administrator_id'), table_name='evrima_admin_sessions')
    op.drop_table('evrima_admin_sessions')
    op.drop_index(op.f('ix_evrima_account_links_administrator_id'), table_name='evrima_account_links')
    op.drop_table('evrima_account_links')
    op.drop_table('evrima_login_failures')
    op.drop_table('evrima_administrators')
