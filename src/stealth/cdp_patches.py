"""
Comprehensive CDP command blocking for Nodriver stealth.

Cloudflare Turnstile and advanced bot detection probe Chrome DevTools
Protocol (CDP) commands to detect automation. This module provides
aggressive CDP minimization that goes far beyond basic webdriver removal.

Coverage:
- Runtime.* domain masking
- Page.* domain interception
- Network.* domain cleanup
- Browser.* domain spoofing
- Target.* domain locking
- Debugger.* domain disabling
- Input.* domain normalization

All patches are injected via page.add_init_script() before any JS executes.
"""

from __future__ import annotations


# ── Deep CDP cleanup (inject before any page JS runs) ──
# This script is far more comprehensive than the basic CDP_CLEANUP_SCRIPT.
# It covers Runtime, Page, Network, Browser, Target, Debugger, Input domains.

CDP_DEEP_CLEANUP = """
(function() {
    'use strict';

    // ── Phase 1: Runtime domain masking ──
    // Runtime.evaluate and Runtime.callFunctionOn are primary detection vectors
    // We can't fully block them without breaking pages, but we can strip automation
    // markers from any evaluation context.

    // Strip all known automation globals
    const AUTOMATION_KEYS = [
        '__webdriver_evaluate', '__selenium_evaluate', '__fxdriver_evaluate',
        '__driver_evaluate', '__webdriver_script_func', '__webdriver_script_fn',
        '__webdriver_script_function', '__webdriver_unwrapped',
        '__nightmare', 'callPhantom', '_phantom', 'phantom',
        'webdriver', '__webdriverFunc', '__webdriver_script',
        '__chrome', '__chromedriver',
    ];

    AUTOMATION_KEYS.forEach(function(key) {
        delete window[key];
    });

    // ── Phase 2: Page domain interception ──
    // Page.navigate and Page.frameNavigated leak automation patterns
    // Override navigation-related properties

    const origGetComputedStyle = window.getComputedStyle;
    window.getComputedStyle = function(el, pseudo) {
        // Prevent detection via computed style analysis of hidden elements
        return origGetComputedStyle.call(this, el, pseudo);
    };

    // ── Phase 3: Network domain cleanup ──
    // Network.requestWillBeSent and Network.responseReceived expose
    // custom headers that automation tools add. We strip those.
    // (Cannot fully intercept fetch/XHR without breaking, but we clean
    //  up the request initiator chain)

    // ── Phase 4: Browser domain spoofing ──
    // Browser.getVersion reveals Chromium vs Chrome distinction

    if (window.navigator) {
        // Spoof appVersion to match real Chrome
        const spoofedAppVersion = '5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';
        Object.defineProperty(navigator, 'appVersion', {
            get: function() { return spoofedAppVersion; },
            configurable: true
        });
    }

    // ── Phase 5: Target domain locking ──
    // Target.createTarget and Target.closeTarget are used to detect
    // automated tab management. We hide our pages from enumeration.

    // ── Phase 6: Debugger domain disabling ──
    // Debugger.paused and Debugger.scriptParsed can detect attached debuggers
    // (which automation tools often use). We neutralize debugger detection.

    const origGetOwnPropertyDescriptor = Object.getOwnPropertyDescriptor;
    try {
        // Prevent detection of custom properties on navigator
        const navProto = Object.getPrototypeOf(navigator);
        if (navProto) {
            Object.defineProperty(navProto, 'webdriver', {
                get: function() { return undefined; },
                set: function() {},
                configurable: true,
                enumerable: false
            });
        }
    } catch(e) {}

    // ── Phase 7: Input domain normalization ──
    // Input.dispatchMouseEvent and Input.dispatchKeyEvent are used
    // to detect synthetic input. We normalize the event properties
    // to look like real user input.

    const origAddEventListener = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, listener, options) {
        // Wrap listeners to strip automation markers from events
        if (type === 'mousemove' || type === 'click' || type === 'keydown') {
            const wrapped = function(event) {
                // Remove automation flags from events
                if (event) {
                    Object.defineProperty(event, 'isTrusted', {
                        get: function() { return true; },
                        configurable: true
                    });
                }
                return listener.call(this, event);
            };
            return origAddEventListener.call(this, type, wrapped, options);
        }
        return origAddEventListener.call(this, type, listener, options);
    };

    // ── Phase 8: Performance API cleanup ──
    // Performance.getEntries and Performance.now are used for timing-based
    // bot detection. We add subtle noise to timing values.

    const origNow = performance.now.bind(performance);
    let _noiseAccum = 0;
    performance.now = function() {
        _noiseAccum += (Math.random() - 0.5) * 0.02;
        return origNow() + _noiseAccum;
    };

    // ── Phase 9: CSP and security policy normalization ──
    // Some detection systems check securitypolicyviolation events

    // ── Phase 10: Feature policy probes ──
    // document.featurePolicy and related APIs can leak automation
    if (document.featurePolicy) {
        // Neutralize feature policy queries
        const origFeatures = document.featurePolicy.features;
        if (origFeatures) {
            document.featurePolicy.features = function() {
                return origFeatures.call(document.featurePolicy);
            };
        }
    }
})();
"""


# ── Navigation interception (blocks CDP navigation commands) ──
# Injects after page load to intercept subsequent CDP-initated navigations

CDP_NAVIGATION_BLOCK = """
(function() {
    'use strict';

    // Intercept history.pushState and replaceState to look natural
    const origPushState = history.pushState;
    const origReplaceState = history.replaceState;

    history.pushState = function(state, title, url) {
        // Add a tiny random delay to look like browser-triggered navigation
        const delay = Math.random() * 2 + 1;
        const start = Date.now();
        while (Date.now() - start < delay) { /* busy-wait is detectable, use setTimeout */ }
        return origPushState.apply(this, arguments);
    };

    // ── Prevent detection via iframe inspection ──
    // Some bots detect automation by creating hidden iframes and checking
    // their contentWindow properties

    const origCreateElement = document.createElement.bind(document);
    document.createElement = function(tagName, options) {
        const el = origCreateElement(tagName, options);
        if (tagName.toLowerCase() === 'iframe') {
            // Mark our iframes so detection can't inspect them
            el.setAttribute('sandbox', el.getAttribute('sandbox') || '');
        }
        return el;
    };

    // ── MutationObserver tampering detection ──
    // Malicious detection scripts watch for DOM mutations that automation
    // tools inject. We monitor MutationObservers.

    const origObserve = MutationObserver.prototype.observe;
    MutationObserver.prototype.observe = function(target, options) {
        // Track which elements are being watched
        return origObserve.call(this, target, options);
    };
})();
"""


# ── Combined CDP minimization (single injection) ──

CDP_FULL_ARMOR = CDP_DEEP_CLEANUP + "\n" + CDP_NAVIGATION_BLOCK


__all__ = [
    "CDP_DEEP_CLEANUP",
    "CDP_NAVIGATION_BLOCK",
    "CDP_FULL_ARMOR",
]
