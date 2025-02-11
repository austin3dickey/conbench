"""optional_commit

Revision ID: dd6597846acf
Revises: 4eb17510d3e9
Create Date: 2023-04-18 07:15:07.372455

"""
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision = "dd6597846acf"
down_revision = "4eb17510d3e9"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "run", "commit_id", existing_type=sa.VARCHAR(length=50), nullable=True
    )
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column(
        "run", "commit_id", existing_type=sa.VARCHAR(length=50), nullable=False
    )
    # ### end Alembic commands ###
