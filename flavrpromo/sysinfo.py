"""
A few numbers about the always-on PC itself for /status: how long it has been up, how full the
data disk is, and the load. Read from /proc (Linux; inside Docker these are the host's own
uptime and load) and the data folder's disk.
"""

from __future__ import annotations

import os
import shutil
from typing import Any, Dict


def info(data_dir: str = "/data") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        with open("/proc/uptime") as f:
            out["uptime_sec"] = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        pass
    try:
        out["load"] = round(os.getloadavg()[0], 2)
    except (OSError, AttributeError):
        pass
    try:
        du = shutil.disk_usage(data_dir if os.path.isdir(data_dir) else "/")
        out["disk_free_gb"] = round(du.free / 1e9, 1)
        out["disk_used_pct"] = round(100 * du.used / du.total)
    except OSError:
        pass
    return out
