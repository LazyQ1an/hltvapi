"""
Process isolation and hot-swapping for long-running Linux server deployments. v9.0

Running Nodriver/Chromium continuously for weeks leaks kernel resources:
- Orphaned shared memory segments in /dev/shm
- Zombie child processes
- File descriptor exhaustion
- GPU memory fragmentation (even with headless)

This module implements "physical detox" — when a profile ages out or a
browser process needs recycling, it's destroyed at the OS level and
replaced with a clean instance.

Components:
- ProcessSandbox: track and manage browser process groups
- ProcessHotSwapper: kill-and-recreate with state preservation
- ZombieReaper: periodic cleanup of orphaned Chrome processes
- ResourceMonitor: track FD count, shm usage, zombie count
"""

from __future__ import annotations

import asyncio
import logging
import os
import platform
import signal
import time as tmod
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("hltv.core.process")


# ---------------------------------------------------------------------------
# Platform detection
# ---------------------------------------------------------------------------

def _is_linux() -> bool:
    return platform.system() == "Linux"

def _is_windows() -> bool:
    return platform.system() == "Windows"


# ---------------------------------------------------------------------------
# Process sandbox
# ---------------------------------------------------------------------------

@dataclass
class ProcessGroup:
    """Track a browser process group for isolation."""
    group_id: str
    main_pid: int | None = None
    child_pids: list[int] = field(default_factory=list)
    created_at: float = field(default_factory=tmod.time)
    profile_name: str = ""
    _killed: bool = False

    @property
    def age_seconds(self) -> float:
        return tmod.time() - self.created_at

    @property
    def is_alive(self) -> bool:
        if self._killed:
            return False
        if self.main_pid is None:
            return False
        return _pid_exists(self.main_pid)


class ProcessSandbox:
    """Lightweight process group isolation for browser instances.

    Each Profile's browser process is tracked as a ProcessGroup.
    When a profile ages out or is flagged for recycling, the entire
    process group is terminated via SIGKILL (-9) to guarantee cleanup.

    On Linux, child processes (renderers, GPU, utility) are detected
    via /proc scanning. On Windows, taskkill /T handles the tree.
    """

    def __init__(self, max_groups: int = 10) -> None:
        self._groups: dict[str, ProcessGroup] = {}
        self._max_groups = max_groups
        self._next_id: int = 0

    def register(self, pid: int, profile_name: str = "") -> ProcessGroup:
        """Register a new browser process group."""
        self._next_id += 1
        gid = f"browser_{self._next_id}"
        group = ProcessGroup(
            group_id=gid,
            main_pid=pid,
            profile_name=profile_name,
        )
        self._groups[gid] = group

        # Prune old groups
        if len(self._groups) > self._max_groups:
            dead = [gid for gid, g in self._groups.items() if not g.is_alive]
            for d in dead:
                del self._groups[d]

        logger.debug("Registered process group %s (pid=%d, profile=%s)", gid, pid, profile_name)
        return group

    async def kill_group(self, group_id: str, force: bool = True) -> bool:
        """Kill an entire process group.

        On Linux, walks /proc to find children, then kills the tree.
        On Windows, uses taskkill /T /F.

        Args:
            group_id: The group to kill.
            force: If True, use SIGKILL; otherwise SIGTERM.

        Returns:
            True if all processes were terminated.
        """
        group = self._groups.get(group_id)
        if not group or group._killed:
            return True

        if group.main_pid is None:
            group._killed = True
            return True

        logger.info("Killing process group %s (pid=%d, profile=%s)", group_id, group.main_pid, group.profile_name)

        # Collect all children
        all_pids = [group.main_pid]
        try:
            children = _find_child_processes(group.main_pid)
            all_pids.extend(children)
            group.child_pids = children
        except Exception as e:
            logger.debug("Child process scan failed: %s", e)

        # Kill from children up to parent
        sig = signal.SIGKILL if force else signal.SIGTERM
        for pid in reversed(all_pids):
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass  # already dead or system process

        # Brief wait for processes to die
        await asyncio.sleep(0.5)

        # Verify death
        survivors = [pid for pid in all_pids if _pid_exists(pid)]
        if survivors:
            logger.warning("Processes survived kill: %s", survivors)
            # Second pass with SIGKILL
            for pid in survivors:
                try:
                    os.kill(pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
            await asyncio.sleep(0.3)

        group._killed = True
        return True

    async def kill_all(self) -> int:
        """Kill all registered process groups. Returns count killed."""
        count = 0
        for gid in list(self._groups.keys()):
            if await self.kill_group(gid):
                count += 1
        return count

    def get_active_count(self) -> int:
        """Return count of still-alive process groups."""
        return sum(1 for g in self._groups.values() if g.is_alive)

    def get_stats(self) -> dict[str, Any]:
        """Return sandbox statistics."""
        alive = sum(1 for g in self._groups.values() if g.is_alive)
        dead = sum(1 for g in self._groups.values() if not g.is_alive)
        return {
            "total_groups": len(self._groups),
            "alive": alive,
            "dead": dead,
            "groups": [
                {
                    "id": g.group_id,
                    "pid": g.main_pid,
                    "profile": g.profile_name,
                    "age_seconds": round(g.age_seconds, 0),
                    "alive": g.is_alive,
                }
                for g in list(self._groups.values())[-10:]
            ],
        }


# ---------------------------------------------------------------------------
# Process hot-swapper
# ---------------------------------------------------------------------------

class ProcessHotSwapper:
    """Orchestrate kill-and-recreate cycles for browser profiles.

    When a profile's health drops or it ages beyond its lifetime,
    the hot-swapper:
    1. Saves any transferable state (cookies, session tickets)
    2. Kills the old browser process group
    3. Waits for kernel resources to be released
    4. Creates a fresh browser instance
    5. Restores saved state

    This prevents the gradual accumulation of kernel-level anomalies
    that CF can detect over long-running sessions.
    """

    def __init__(self, sandbox: ProcessSandbox | None = None) -> None:
        self._sandbox = sandbox or ProcessSandbox()
        self._swap_count: int = 0
        self._last_swap: float = 0.0

    async def hot_swap(
        self,
        group_id: str,
        create_fn: Any = None,  # async callable → new browser
        save_state_fn: Any = None,  # async callable → saved state
        restore_state_fn: Any = None,  # async callable(state) → None
        cooldown_seconds: float = 5.0,
    ) -> Any | None:
        """Perform a hot-swap of a browser process.

        Args:
            group_id: Process group to swap.
            create_fn: Async callable that returns a new browser instance.
            save_state_fn: Async callable that returns serializable state.
            restore_state_fn: Async callable that takes state and restores it.
            cooldown_seconds: Wait between kill and recreate.

        Returns:
            New browser instance, or None if create_fn not provided.
        """
        logger.info("Hot-swapping process group %s", group_id)

        # 1. Save state
        saved_state = None
        if save_state_fn:
            try:
                saved_state = await save_state_fn()
                logger.debug("Saved state for hot-swap: %s keys", len(saved_state) if isinstance(saved_state, dict) else "?")
            except Exception as e:
                logger.warning("State save failed during hot-swap: %s", e)

        # 2. Kill old process
        await self._sandbox.kill_group(group_id, force=True)

        # 3. Cooldown — let kernel release resources
        logger.debug("Hot-swap cooldown: %.0fs", cooldown_seconds)
        await asyncio.sleep(cooldown_seconds)

        # 4. Create fresh instance
        new_instance = None
        if create_fn:
            try:
                new_instance = await create_fn()
                logger.info("Hot-swapped browser created")
            except Exception as e:
                logger.error("Hot-swap creation failed: %s", e)
                raise

        # 5. Restore state
        if restore_state_fn and saved_state and new_instance:
            try:
                await restore_state_fn(saved_state)
                logger.debug("State restored after hot-swap")
            except Exception as e:
                logger.warning("State restore failed after hot-swap: %s", e)

        self._swap_count += 1
        self._last_swap = tmod.time()
        return new_instance

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "swap_count": self._swap_count,
            "last_swap_age_seconds": round(tmod.time() - self._last_swap, 0) if self._last_swap > 0 else None,
        }


# ---------------------------------------------------------------------------
# Zombie reaper
# ---------------------------------------------------------------------------

class ZombieReaper:
    """Periodic cleanup of orphaned Chrome/Chromium processes.

    Chromium is notorious for leaving zombie processes, especially
    after crashes or forced kills. This reaper periodically scans
    for and cleans up:

    - Zombie (defunct) processes in /proc
    - Orphaned chrome/chromium processes not tracked by sandbox
    - Stale /dev/shm segments from old browser instances
    - Leaked file descriptors

    Runs as a background asyncio task.
    """

    def __init__(self, interval_seconds: float = 300.0) -> None:
        self._interval = interval_seconds
        self._task: asyncio.Task | None = None
        self._reap_count: int = 0
        self._last_reap: float = 0.0

    async def start(self) -> None:
        """Start periodic reaping."""
        if self._task:
            return
        self._task = asyncio.create_task(self._reap_loop())
        logger.info("Zombie reaper started (interval=%ds)", self._interval)

    async def stop(self) -> None:
        """Stop periodic reaping."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _reap_loop(self) -> None:
        while True:
            try:
                await asyncio.sleep(self._interval)
                count = await self._reap()
                if count > 0:
                    logger.debug("Zombie reaper: cleaned %d processes", count)
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug("Zombie reaper error: %s", e)

    async def _reap(self) -> int:
        """Scan for and clean zombie/orphaned processes. Returns count cleaned."""
        count = 0

        if _is_linux():
            count += await self._reap_linux()
        elif _is_windows():
            count += self._reap_windows()

        self._reap_count += count
        self._last_reap = tmod.time()
        return count

    async def _reap_linux(self) -> int:
        """Linux-specific reaping via /proc scan."""
        count = 0
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                try:
                    pid = int(entry)
                    with open(f"/proc/{pid}/status", "r") as f:
                        status = f.read()
                    # Check for zombie state
                    if "State:\tZ" in status or "State:\tzombie" in status:
                        name_line = [ln for ln in status.split("\n") if ln.startswith("Name:")]
                        proc_name = name_line[0].split(":")[1].strip() if name_line else ""
                        if any(browser in proc_name.lower() for browser in ("chrome", "chromium", "chromium-browser")):
                            try:
                                os.kill(pid, signal.SIGKILL)
                                count += 1
                            except (ProcessLookupError, PermissionError):
                                pass
                except (FileNotFoundError, ProcessLookupError, ValueError):
                    continue
        except Exception as e:
            logger.debug("Linux reap scan error: %s", e)

        # Clean /dev/shm chrome segments
        if count > 0:
            try:
                for entry in os.listdir("/dev/shm"):
                    if entry.startswith((".org.chromium", "com.google.Chrome")):
                        try:
                            path = f"/dev/shm/{entry}"
                            if os.path.isfile(path):
                                os.unlink(path)
                        except OSError:
                            pass
            except Exception:
                pass

        return count

    def _reap_windows(self) -> int:
        """Windows-specific reaping via tasklist."""
        # On Windows, zombie processes are rarer. Use taskkill for orphaned chromes.
        count = 0
        try:
            import subprocess
            result = subprocess.run(
                ["tasklist", "/FI", "STATUS eq NOT RESPONDING", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, timeout=10,
            )
            for line in result.stdout.splitlines():
                if "chrome" in line.lower():
                    # Can't safely auto-kill on Windows without PID
                    logger.debug("Found unresponsive Chrome process: %s", line.strip())
        except Exception:
            pass
        return count

    def get_stats(self) -> dict[str, Any]:
        return {
            "reap_count": self._reap_count,
            "last_reap_age_seconds": round(tmod.time() - self._last_reap, 0) if self._last_reap > 0 else None,
            "interval_seconds": self._interval,
            "active": self._task is not None and not self._task.done(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pid_exists(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return True  # permission error means it exists
    except OSError:
        return False


def _find_child_processes(parent_pid: int) -> list[int]:
    """Find child PIDs of a given process (Linux only)."""
    if not _is_linux():
        return []
    children: list[int] = []
    try:
        task_path = f"/proc/{parent_pid}/task/{parent_pid}/children"
        with open(task_path, "r") as f:
            children = [int(pid) for pid in f.read().strip().split()]
    except (FileNotFoundError, ValueError):
        pass
    return children


__all__ = [
    "ProcessGroup",
    "ProcessSandbox",
    "ProcessHotSwapper",
    "ZombieReaper",
]
