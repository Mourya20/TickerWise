"""track updated ingestion records

Revision ID: f02b84ed10cd
Revises: 27d096cc4138
Create Date: 2026-10-14 17:57:57.330732

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f02b84ed10cd'
down_revision: Union[str, Sequence[str], None] = '27d096cc4138'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        'ingestion_runs',
        sa.Column(
            'records_updated',
            sa.Integer(),
            server_default=sa.text('0'),
            nullable=False,
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('ingestion_runs', 'records_updated')
