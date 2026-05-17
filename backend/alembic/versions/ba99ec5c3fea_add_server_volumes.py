"""add_server_volumes

Revision ID: ba99ec5c3fea
Revises: 1497143a4122
Create Date: 2026-05-16 23:30:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = 'ba99ec5c3fea'
down_revision = '1497143a4122'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create server_volumes association table
    op.create_table(
        'server_volumes',
        sa.Column('server_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('servers.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('volume_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('volumes.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('mount_path', sa.String(255), nullable=False, default='/data'),
        sa.Column('mode', sa.String(20), default='read_write'),
        sa.Column('is_primary', sa.Boolean(), default=False),
        sa.Column('created_at', sa.DateTime(), default=sa.func.now()),
    )
    
    # Migrate existing data: servers.volume_id + servers.volume_mode -> server_volumes
    conn = op.get_bind()
    
    # Get existing server-volume relationships
    result = conn.execute(
        sa.text("""
            SELECT s.id, s.volume_id, s.volume_mode, u.username 
            FROM servers s 
            LEFT JOIN users u ON s.user_id = u.id 
            WHERE s.volume_id IS NOT NULL
        """)
    )
    
    for row in result:
        server_id = str(row[0])
        volume_id = str(row[1])
        volume_mode = row[2] or 'read_write'
        username = row[3] or 'user'
        mount_path = f'/home/{username}'
        
        conn.execute(
            sa.text("""
                INSERT INTO server_volumes (server_id, volume_id, mount_path, mode, is_primary)
                VALUES (:server_id, :volume_id, :mount_path, :mode, true)
                ON CONFLICT (server_id, volume_id) DO NOTHING
            """),
            {
                'server_id': server_id,
                'volume_id': volume_id,
                'mount_path': mount_path,
                'mode': volume_mode,
            }
        )


def downgrade() -> None:
    op.drop_table('server_volumes')
