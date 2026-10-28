"""Darwin can report EPERM when a control-pipe cancellation just killed the group."""
import os
import signal
from types import SimpleNamespace

import pytest

from core.contained_subprocess import OwnedPopen

pytestmark = pytest.mark.skipif(os.name != "posix", reason="POSIX process groups only")


@pytest.mark.parametrize("exited", [True, False])
@pytest.mark.parametrize("probe", ["waitpid", "waitid"])
def test_group_signal_permission_error_is_benign_only_after_owned_leader_exits(monkeypatch, exited, probe):
    # The first probe proves the leader live; the second sees its concurrent
    # control-pipe cancellation. Exercise both native API choices on POSIX CI.
    pid = 12345
    proc = SimpleNamespace(pid=pid, args=[], stdin=None, stdout=None, stderr=None, returncode=None)
    handle = OwnedPopen(proc, -1, -1)
    if probe == "waitpid":
        monkeypatch.delattr(os, "waitid", raising=False)
        replies = iter([(0, 0), (pid, signal.SIGKILL) if exited else (0, 0)])
        monkeypatch.setattr(os, "waitpid", lambda *a: next(replies))
    else:
        for name, value in (("P_PID", 1), ("WEXITED", 4), ("WNOHANG", 1), ("WNOWAIT", 8)):
            monkeypatch.setattr(os, name, value, raising=False)
        replies = iter([None, SimpleNamespace(si_pid=pid) if exited else None])
        monkeypatch.setattr(os, "waitid", lambda *a: next(replies), raising=False)
    def denied(*args):
        raise PermissionError(1, "Operation not permitted")
    monkeypatch.setattr(os, "killpg", denied)
    if exited:
        handle._signal_owned_group(signal.SIGKILL)
        if probe == "waitpid":
            assert proc.returncode == -signal.SIGKILL
    else:
        with pytest.raises(PermissionError):
            handle._signal_owned_group(signal.SIGKILL)
