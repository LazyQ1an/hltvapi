"""
Server resource monitoring via psutil.

v4.0: Real-time CPU, memory, disk, network, and process metrics.
Used by scheduler for adaptive load control and by /resources API endpoint.
"""

from __future__ import annotations

from typing import Any

try:
    import psutil
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False


def get_resource_usage() -> dict[str, Any]:
    """Get current CPU, memory, disk, and network usage.

    Returns:
        Dict with resource metrics, or error dict if psutil unavailable.
    """
    if not _HAS_PSUTIL:
        return {"error": "psutil not installed", "available": False}

    try:
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()
        per_cpu = psutil.cpu_percent(interval=0.0, percpu=True)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage("/")
        net = psutil.net_io_counters()

        proc = psutil.Process()
        proc_mem = proc.memory_info()

        return {
            "available": True,
            "cpu": {
                "percent": cpu_percent,
                "count": cpu_count,
                "per_cpu": per_cpu,
            },
            "memory": {
                "total_gb": round(mem.total / (1024**3), 1),
                "available_gb": round(mem.available / (1024**3), 1),
                "used_gb": round(mem.used / (1024**3), 1),
                "percent": mem.percent,
            },
            "disk": {
                "total_gb": round(disk.total / (1024**3), 1),
                "used_gb": round(disk.used / (1024**3), 1),
                "percent": disk.percent,
            },
            "network": {
                "sent_mb": round(net.bytes_sent / (1024**2), 1),
                "recv_mb": round(net.bytes_recv / (1024**2), 1),
            },
            "process": {
                "memory_mb": round(proc_mem.rss / (1024**2), 1),
                "cpu_percent": proc.cpu_percent(interval=0.1),
                "threads": proc.num_threads(),
            },
        }
    except Exception as e:
        return {"error": str(e), "available": False}


def get_system_load_average() -> float:
    """Get normalized system load average (0.0-1.0+).

    On Linux: returns 1-min load average / cpu_count.
    On Windows: returns cpu_percent / 100.
    """
    if not _HAS_PSUTIL:
        return 0.0
    try:
        load = psutil.getloadavg()
        cpu_count = psutil.cpu_count() or 1
        return round(load[0] / cpu_count, 2)
    except (AttributeError, OSError):
        return round(psutil.cpu_percent(interval=0.1) / 100, 2)
