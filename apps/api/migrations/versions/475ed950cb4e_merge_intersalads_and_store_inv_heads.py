"""merge intersalads/nursery and store-inv-004 heads

VINES-OPS-001A closure: a no-op Alembic merge revision joining the two
Alembic heads that existed side-by-side before this ticket --

    b7e2f4a9c1d6 (intersalads transplant placement -- the Nursery/InterSalads
                  branch this ticket's own InterVines migration continues)
    86b9cf24d6ff (STORE-INV-004: consumption, return and scrap -- an
                  unrelated, already-merged-to-main Inventory branch)

Both were independently valid heads because each was authored and migrated
on its own feature branch with no shared Alembic ancestor node inserted at
integration time. Neither branch's own migration is touched, edited, or
reinterpreted here -- this revision does no schema work of its own
(`upgrade()`/`downgrade()` are both no-ops); it exists purely to give the
migration graph a single, deterministic head again, which the normal
`alembic upgrade head` test/production path requires. `810e24e6ce43`
(InterVines Transplant placement) is rebased downstream of this merge
point instead of directly onto `b7e2f4a9c1d6` alone, so the final graph is:

    b7e2f4a9c1d6 --\\
                     >-- 475ed950cb4e (this revision) -- 810e24e6ce43
    86b9cf24d6ff --/

Revision ID: 475ed950cb4e
Revises: b7e2f4a9c1d6, 86b9cf24d6ff
Create Date: 2026-09-08 00:00:00.000000

"""
from typing import Sequence, Union


revision: str = '475ed950cb4e'
down_revision: Union[str, Sequence[str], None] = ('b7e2f4a9c1d6', '86b9cf24d6ff')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
