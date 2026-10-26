# CLEAN-ROOM (spec T1-folded §4): migration 0013 (generation_history.design_recipe)
# is to be reimplemented from the spec. The revision chain identifiers below are
# kept so migration 0014 keeps resolving its parent; upgrade/downgrade are
# placeholders until then.
from typing import Sequence, Union

revision: str = "0013_generation_history_design_recipe"
down_revision: Union[str, None] = "0012_call_sessions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
