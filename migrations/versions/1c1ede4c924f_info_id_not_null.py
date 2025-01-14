"""info id not null

Revision ID: 1c1ede4c924f
Revises: 1fed559406c5
Create Date: 2021-11-17 10:03:27.286293

"""
import logging
import uuid

import sqlalchemy as sa
from alembic import op
from sqlalchemy import MetaData

# revision identifiers, used by Alembic.
revision = "1c1ede4c924f"
down_revision = "1fed559406c5"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade():
    connection = op.get_bind()
    meta = MetaData()
    meta.reflect(bind=connection)

    info_table = meta.tables["info"]
    summary_table = meta.tables["summary"]
    summaries = list(
        connection.execute(
            summary_table.select().filter(summary_table.c.info_id.is_(None))
        )
    )

    null_info, num = None, len(summaries)
    for i, summary in enumerate(summaries):
        logger.info(f"Found NULL {i + 1} of {num}: {summary.id}")

        if not null_info:
            null_info = connection.execute(
                info_table.select().where(
                    info_table.c.tags == {},
                )
            ).fetchone()

            if null_info:
                logger.info("Found NULL info")
            else:
                logger.info("No NULL info")
                new_info_id = uuid.uuid4().hex
                connection.execute(
                    info_table.insert().values(
                        id=new_info_id,
                        tags={},
                    )
                )
                null_info = connection.execute(
                    info_table.select().where(
                        info_table.c.tags == {},
                    )
                ).fetchone()

        connection.execute(
            summary_table.update()
            .where(summary_table.c.id == summary.id)
            .values(info_id=null_info.id)
        )

    op.alter_column(
        "summary", "info_id", existing_type=sa.VARCHAR(length=50), nullable=False
    )


def downgrade():
    op.alter_column(
        "summary", "info_id", existing_type=sa.VARCHAR(length=50), nullable=True
    )
