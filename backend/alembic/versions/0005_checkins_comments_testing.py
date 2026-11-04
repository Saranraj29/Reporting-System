"""Testing status, morning + end-of-day check-ins, comment kinds (system notes) and internal notes

Revision ID: 0005
Revises: 0004
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check")
    op.execute(
        "ALTER TABLE tasks ADD CONSTRAINT tasks_status_check "
        "CHECK (status IN ('todo','in_progress','in_review','testing','blocked','done'))"
    )
    # activity feed: human comments, plus system notes ("moved to Testing", "logged 2h") written by the API
    op.execute("ALTER TABLE task_comments ADD COLUMN kind text NOT NULL DEFAULT 'comment' CHECK (kind IN ('comment','system'))")
    op.execute("ALTER TABLE task_comments ADD COLUMN is_internal boolean NOT NULL DEFAULT false")
    # daily status becomes two check-ins a day: morning plan and end-of-day update, each timestamped
    op.execute("ALTER TABLE daily_status ADD COLUMN plan_today text NOT NULL DEFAULT ''")
    op.execute("ALTER TABLE daily_status ADD COLUMN morning_at timestamptz")
    op.execute("ALTER TABLE daily_status ADD COLUMN eod_at timestamptz")
    op.execute("UPDATE daily_status SET eod_at = updated_at WHERE did_today <> ''")  # existing rows were end-of-day updates


def downgrade() -> None:
    op.execute("ALTER TABLE daily_status DROP COLUMN eod_at, DROP COLUMN morning_at, DROP COLUMN plan_today")
    op.execute("ALTER TABLE task_comments DROP COLUMN is_internal, DROP COLUMN kind")
    op.execute("UPDATE tasks SET status = 'in_review' WHERE status = 'testing'")
    op.execute("ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_status_check")
    op.execute("ALTER TABLE tasks ADD CONSTRAINT tasks_status_check CHECK (status IN ('todo','in_progress','blocked','in_review','done'))")
