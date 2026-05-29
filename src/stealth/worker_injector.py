"""
Web Worker & multi-thread fingerprint injection via CDP. v8.0

Cloudflare Turnstile probes environments in Web Workers, Service Workers,
and Shared Workers. Most stealth frameworks only patch the main thread,
leaving Worker contexts vulnerable to detection.

This module uses Chrome DevTools Protocol's Target domain to:
1. Enumerate all execution contexts (pages, workers, iframes)
2. Attach to each target
3. Inject the full fingerprint spoofing script into every context
4. Synchronize timing jitter between main thread and workers

Key CDP methods used:
- Target.getTargets() — discover all targets
- Target.attachToTarget() — attach debugger to worker
- Runtime.evaluate() — inject script into worker context
- Page.addScriptToEvaluateOnNewDocument() — ensure injection on new documents
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("hltv.stealth.worker_injector")


# ── Cross-context timing synchronization script ──
# This script runs in BOTH main thread and worker threads.
# It ensures performance.now() returns synchronized, naturally-jittered
# values across all execution contexts.

CROSS_CONTEXT_TIMING_SCRIPT = """
(function() {
    'use strict';

    // Shared time base (milliseconds offset from epoch)
    // All contexts derive their noise from this shared base
    const TIME_BASE = Date.now();
    let _noiseAccum = 0;
    let _lastCall = 0;

    const origNow = performance.now.bind(performance);
    performance.now = function() {
        const real = origNow();
        const now = Date.now();

        // Natural micro-jitter: 0.005-0.05ms per call
        // Real hardware has clock drift and interrupt latency
        const jitter = (Math.random() - 0.5) * 0.01;
        _noiseAccum += jitter;

        // Prevent large drift (keep within 2ms of real time)
        if (Math.abs(_noiseAccum) > 2.0) {
            _noiseAccum = _noiseAccum * 0.9;
        }

        // Ensure monotonic (time never goes backward)
        const result = Math.max(_lastCall, real + _noiseAccum);
        _lastCall = result;
        return result;
    };

    // performance.timeOrigin consistency
    Object.defineProperty(performance, 'timeOrigin', {
        get: function() { return TIME_BASE - performance.now(); },
        configurable: true
    });

    // Date.now() consistency
    const origDateNow = Date.now.bind(Date);
    Date.now = function() {
        return origDateNow() + (_noiseAccum * 0.001);
    };
})();
"""


# ── Worker fingerprint injection script ──
# Minimal version of the full fingerprint that works in Worker contexts
# (Workers don't have DOM, so Canvas/WebGL/DOM APIs are unavailable)

WORKER_FINGERPRINT_SCRIPT = """
(function() {
    'use strict';

    // Navigator properties (available in Workers)
    if (typeof navigator !== 'undefined') {
        Object.defineProperties(navigator, {
            hardwareConcurrency: { get: () => 8, configurable: true },
            deviceMemory: { get: () => 8, configurable: true },
            platform: { get: () => 'Win32', configurable: true },
            language: { get: () => 'en-US', configurable: true },
            languages: { get: () => ['en-US', 'en'], configurable: true },
            userAgent: {
                get: () => 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
                configurable: true
            },
        });
    }

    // Performance API (available in Workers)
    if (typeof performance !== 'undefined') {
        let _noise = 0;
        const origNow = performance.now.bind(performance);
        performance.now = function() {
            _noise += (Math.random() - 0.5) * 0.01;
            const v = origNow() + _noise;
            if (Math.abs(_noise) > 1.5) _noise *= 0.9;
            return v;
        };
    }

    // Crypto API consistency
    if (typeof crypto !== 'undefined' && crypto.getRandomValues) {
        const origGetRandom = crypto.getRandomValues.bind(crypto);
        crypto.getRandomValues = function(buf) {
            return origGetRandom(buf);
        };
    }

    // Block detection of Worker type
    if (typeof self !== 'undefined') {
        Object.defineProperty(self, 'name', {
            get: () => '',
            configurable: true
        });
    }

    // Clean automation markers in Worker scope
    const AUTO_KEYS = [
        '__webdriver_evaluate', '__selenium_evaluate',
        '__driver_evaluate', '__webdriver_script_fn',
        '__chrome', '__chromedriver',
    ];
    AUTO_KEYS.forEach(function(k) {
        try { delete self[k]; } catch(e) {}
    });
})();
"""


class WorkerInjector:
    """CDP-based injection into all Worker and iframe contexts.

    Usage:
        injector = WorkerInjector(browser)
        await injector.inject_all(fingerprint_script)
    """

    def __init__(self, browser: Any) -> None:
        self._browser = browser
        self._injected_targets: set[str] = set()
        self._inject_count: int = 0

    async def inject_all(self, fingerprint_script: str = "") -> None:
        """Inject fingerprint into all discoverable targets.

        This includes:
        - All open pages
        - Service Workers
        - Shared Workers
        - Dedicated Workers (if discoverable)
        - Iframes within pages
        """
        try:
            import nodriver as uc

            # Get all targets
            targets = await self._browser.send(
                uc.cdp.target.get_targets()
            )

            target_infos = targets.get("targetInfos", [])
            logger.debug("Discovered %d CDP targets", len(target_infos))

            for target_info in target_infos:
                target_id = target_info.get("targetId", "")
                target_type = target_info.get("type", "")
                target_url = target_info.get("url", "")

                # Skip already injected
                if target_id in self._injected_targets:
                    continue

                # Only inject into relevant targets
                if target_type not in ("page", "worker", "service_worker", "shared_worker", "iframe"):
                    continue

                # Skip chrome:// and devtools:// pages
                if target_url.startswith(("chrome://", "devtools://", "chrome-extension://")):
                    continue

                try:
                    await self._inject_into_target(target_id, target_type, fingerprint_script)
                    self._injected_targets.add(target_id)
                    self._inject_count += 1
                except Exception as e:
                    logger.debug(
                        "Failed to inject into %s (%s): %s",
                        target_type, target_id[:8], e,
                    )

            logger.debug(
                "Worker injection complete: %d targets patched",
                self._inject_count,
            )

        except Exception as e:
            logger.debug("Worker injection error: %s", e)

    async def _inject_into_target(
        self,
        target_id: str,
        target_type: str,
        fingerprint_script: str,
    ) -> None:
        """Attach to a target and inject scripts."""
        import nodriver as uc

        # Attach to the target
        session = await self._browser.send(
            uc.cdp.target.attach_to_target(
                targetId=target_id,
                flatten=True,
            )
        )
        session_id = session.get("sessionId", "")

        if not session_id:
            return

        # Enable Runtime domain to evaluate scripts
        await self._browser.send(
            uc.cdp.runtime.enable(),
            session_id=session_id,
        )

        # Inject timing synchronization (all contexts)
        await self._browser.send(
            uc.cdp.runtime.evaluate(
                expression=CROSS_CONTEXT_TIMING_SCRIPT,
                contextId=None,  # Evaluate in default context
            ),
            session_id=session_id,
        )

        # Inject worker fingerprint (worker-specific)
        if target_type in ("worker", "service_worker", "shared_worker"):
            await self._browser.send(
                uc.cdp.runtime.evaluate(
                    expression=WORKER_FINGERPRINT_SCRIPT,
                    contextId=None,
                ),
                session_id=session_id,
            )

        # Inject full fingerprint into page contexts
        if target_type == "page" and fingerprint_script:
            await self._browser.send(
                uc.cdp.runtime.evaluate(
                    expression=fingerprint_script,
                    contextId=None,
                ),
                session_id=session_id,
            )

        # Ensure injection on new documents
        if target_type == "page":
            await self._browser.send(
                uc.cdp.page.add_script_to_evaluate_on_new_document(
                    source=fingerprint_script or CROSS_CONTEXT_TIMING_SCRIPT,
                ),
                session_id=session_id,
            )

        logger.debug("Injected into %s (session=%s)", target_type, session_id[:8])

    def get_stats(self) -> dict[str, Any]:
        return {
            "targets_injected": self._inject_count,
            "unique_targets": len(self._injected_targets),
        }


__all__ = [
    "WorkerInjector",
    "CROSS_CONTEXT_TIMING_SCRIPT",
    "WORKER_FINGERPRINT_SCRIPT",
]
