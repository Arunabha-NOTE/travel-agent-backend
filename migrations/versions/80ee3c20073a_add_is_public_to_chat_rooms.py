"""add is_public to chat_rooms

Revision ID: 80ee3c20073a
Revises: cf4b17ea6ee0
Create Date: 2026-04-27 22:19:51.820209

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "80ee3c20073a"
down_revision: Union[str, Sequence[str], None] = "cf4b17ea6ee0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add column with a server default to handle existing rows
    op.add_column(
        "chat_rooms",
        sa.Column(
            "is_public", sa.Boolean(), server_default=sa.text("false"), nullable=False
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("chat_rooms", "is_public")
