"""init schema

Revision ID: 123456789abc
Revises: 
Create Date: 2025-09-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers
revision = '123456789abc'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'bus_user',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('bus_number', sa.String, nullable=False),
        sa.Column('IMEI', sa.String, unique=True, nullable=False),
    )

    op.create_table(
        'routes',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('bus_id', sa.String, sa.ForeignKey('bus_user.id')),
        sa.Column('start_point', sa.String, nullable=False),
        sa.Column('end_point', sa.String, nullable=False),
        sa.Column('start_time_approx', sa.TIMESTAMP(timezone=True)),
        sa.Column('end_time_approx', sa.TIMESTAMP(timezone=True)),
    )

    op.create_table(
        'gps_data',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('bus_id', sa.String, sa.ForeignKey('bus_user.id')),
        sa.Column('route_id', sa.String, sa.ForeignKey('routes.id')),
        sa.Column('latitude', sa.Float),
        sa.Column('longitude', sa.Float),
        sa.Column('speed', sa.Integer),
        sa.Column('last_updated', sa.TIMESTAMP(timezone=True)),
    )

    op.create_table(
        'stop_data',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('stop_name', sa.String, nullable=False),
        sa.Column('latitude', sa.Float),
        sa.Column('longitude', sa.Float),
    )

    op.create_table(
        'route_stops',
        sa.Column('id', sa.String, primary_key=True),
        sa.Column('stop_id', sa.String, sa.ForeignKey('stop_data.id')),
        sa.Column('route_id', sa.String, sa.ForeignKey('routes.id')),
        sa.Column('bus_id', sa.String, sa.ForeignKey('bus_user.id')),
        sa.Column('approx_time', sa.TIMESTAMP(timezone=True)),
    )


def downgrade():
    op.drop_table('route_stops')
    op.drop_table('stop_data')
    op.drop_table('gps_data')
    op.drop_table('routes')
    op.drop_table('bus_user')
