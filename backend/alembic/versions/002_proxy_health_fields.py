from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = '002'
down_revision: Union[str, None] = '001'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('proxies', sa.Column('ip', sa.String(length=64), nullable=True))
    op.add_column('proxies', sa.Column('latency_ms', sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column('proxies', 'latency_ms')
    op.drop_column('proxies', 'ip')
