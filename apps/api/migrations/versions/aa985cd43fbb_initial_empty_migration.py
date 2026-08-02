"""initial empty migration

Revision ID: aa985cd43fbb
Revises: 
Create Date: 2026-08-02 10:34:51.313402

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'aa985cd43fbb'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
