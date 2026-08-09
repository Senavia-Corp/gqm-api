"""cloudinary identity en attachments

Revision ID: c60a71121b93
Revises: 8ac457c78452
Create Date: 2026-08-09 09:49:25.604632

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c60a71121b93'
down_revision: Union[str, Sequence[str], None] = '8ac457c78452'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """REG-058: identidad Cloudinary persistida (el delete de raw fallaba)."""
    op.add_column("attachments", sa.Column("cloudinary_public_id", sa.String(), nullable=True))
    op.add_column("attachments", sa.Column("cloudinary_resource_type", sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("attachments", "cloudinary_resource_type")
    op.drop_column("attachments", "cloudinary_public_id")
