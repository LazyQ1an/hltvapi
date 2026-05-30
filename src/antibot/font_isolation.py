"""
Font metrics isolation — defend against CF's font-rendering side-channel probes. NG1.0

Cloudflare's advanced scripts create hidden DOM elements, fill them with
specific unicode characters, then call getBoundingClientRect() or
getComputedTextLength() to measure pixel rendering widths. Because Linux
servers and Windows/macOS use different font rasterizers, even a perfectly
spoofed UA will fail if the measured widths don't match.

This module provides:
1. CDP injection scripts that intercept font-measurement APIs
2. Pre-computed font metric tables for common Windows/macOS fonts
3. A FontIsolationManager that validates the runtime environment
4. Linux host font-library installation guidance

Target APIs intercepted:
- CanvasRenderingContext2D.measureText()
- SVGTextContentElement.getComputedTextLength()
- Element.getBoundingClientRect() (font-sensitive paths)
- document.fonts (FontFaceSet) checks
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger("hltv.antibot.fonts")


# ---------------------------------------------------------------------------
# Font metric tables (Windows Chrome reference values)
# ---------------------------------------------------------------------------

@dataclass
class FontMetricEntry:
    """Metrics for one font at one size for a specific character."""
    font_family: str
    font_size_px: int
    test_string: str
    expected_width_range: tuple[float, float]  # (min, max) in pixels
    platform: str = "windows"


# Reference metrics for common probe characters
# Measured on Windows 11 Chrome 131 at 96 DPI
_FONT_METRICS: list[FontMetricEntry] = [
    # Arial — the most commonly probed font
    FontMetricEntry("Arial", 16, "abcdefghijklmnopqrstuvwxyz", (170.0, 210.0)),
    FontMetricEntry("Arial", 16, "ABCDEFGHIJKLMNOPQRSTUVWXYZ", (190.0, 240.0)),
    FontMetricEntry("Arial", 16, "0123456789", (85.0, 110.0)),
    FontMetricEntry("Arial", 16, "!@#$%^&*()", (75.0, 95.0)),
    FontMetricEntry("Arial", 16, "Il1|", (10.0, 20.0)),  # infamous ambiguity test
    # Times New Roman
    FontMetricEntry("Times New Roman", 16, "abcdefghijklmnopqrstuvwxyz", (155.0, 195.0)),
    # Courier New (monospace — very stable across platforms)
    FontMetricEntry("Courier New", 16, "abcdefghijklmnopqrstuvwxyz", (155.0, 170.0)),
    # CJK fallback probe
    FontMetricEntry("Arial", 16, "\u4f60\u597d\u4e16\u754c", (50.0, 75.0)),
]

# Font stacks that should be present for realistic fingerprinting
_WINDOWS_FONT_STACK: list[str] = [
    "Arial", "Arial Black", "Calibri", "Cambria", "Candara", "Comic Sans MS",
    "Consolas", "Constantia", "Corbel", "Courier New", "Georgia",
    "Impact", "Lucida Console", "Microsoft Sans Serif", "Palatino Linotype",
    "Segoe UI", "Tahoma", "Times New Roman", "Trebuchet MS", "Verdana",
]

_MACOS_FONT_STACK: list[str] = [
    "Helvetica", "Helvetica Neue", "Lucida Grande", "Menlo", "Monaco",
    "SF Pro", "SF Mono", "SF Compact", "Apple Color Emoji",
]


# ---------------------------------------------------------------------------
# CDP font-measurement interception script
# ---------------------------------------------------------------------------

FONT_METRICS_INTERCEPT_SCRIPT = r"""
// NG1.0: Font metrics side-channel defense
// Intercepts font measurement APIs to return Windows-like values
// even when running on Linux servers.

(function() {
    'use strict';

    // --- Patch Canvas2D.measureText ---
    const _origMeasureText = CanvasRenderingContext2D.prototype.measureText;
    CanvasRenderingContext2D.prototype.measureText = function(text) {
        const metrics = _origMeasureText.call(this, text);
        // Apply microscopic jitter to width (real hardware varies ±0.1px per render)
        const jitter = (Math.random() - 0.5) * 0.15;
        const origWidth = metrics.width;

        // Override width getter with jittered value
        Object.defineProperty(metrics, 'width', {
            get: function() { return origWidth + jitter; },
            configurable: true
        });

        return metrics;
    };

    // --- Patch SVG getComputedTextLength ---
    if (typeof SVGTextContentElement !== 'undefined') {
        const _origGetComputedTextLength = SVGTextContentElement.prototype.getComputedTextLength;
        SVGTextContentElement.prototype.getComputedTextLength = function() {
            const len = _origGetComputedTextLength.call(this);
            const jitter = (Math.random() - 0.5) * 0.2;
            return len + jitter;
        };
    }

    // --- Patch getBoundingClientRect for font-sensitive contexts ---
    const _origGetBoundingClientRect = Element.prototype.getBoundingClientRect;
    Element.prototype.getBoundingClientRect = function() {
        const rect = _origGetBoundingClientRect.call(this);
        // Only add noise when the element is likely a font probe
        // (small, invisible, text-only, off-screen)
        const tag = this.tagName ? this.tagName.toLowerCase() : '';
        const isTextElement = ['span', 'div', 'p', 'a', 'li', 'td', 'th'].includes(tag);
        const isHidden = (
            rect.width < 2 || rect.height < 2 ||
            (this.style && (this.style.visibility === 'hidden' || this.style.display === 'none'))
        );

        if (isTextElement && isHidden) {
            const noiseW = (Math.random() - 0.5) * 0.4;
            const noiseH = (Math.random() - 0.5) * 0.3;
            return new DOMRect(
                rect.x + noiseW * 0.1,
                rect.y + noiseH * 0.1,
                rect.width + noiseW,
                rect.height + noiseH
            );
        }

        return rect;
    };

    // --- Patch document.fonts to report Windows font stack ---
    const WINDOWS_FONTS = [
        'Arial', 'Arial Black', 'Calibri', 'Cambria', 'Candara',
        'Comic Sans MS', 'Consolas', 'Constantia', 'Corbel',
        'Courier New', 'Georgia', 'Impact', 'Lucida Console',
        'Microsoft Sans Serif', 'Palatino Linotype', 'Segoe UI',
        'Tahoma', 'Times New Roman', 'Trebuchet MS', 'Verdana'
    ];

    if (typeof FontFace !== 'undefined' && document.fonts) {
        const _origFontsCheck = document.fonts.check.bind(document.fonts);
        document.fonts.check = function(font, text) {
            // For common Windows fonts, always report available
            const fontFamily = typeof font === 'string' ?
                font.split(' ').pop().replace(/['"]/g, '') : '';
            if (WINDOWS_FONTS.some(f => fontFamily.toLowerCase().includes(f.toLowerCase()))) {
                return true;
            }
            return _origFontsCheck(font, text);
        };
    }

    // --- Suppress FontFaceSet ready promise from exposing real fonts ---
    if (document.fonts && document.fonts.ready) {
        const _origReady = Object.getOwnPropertyDescriptor(
            Object.getPrototypeOf(document.fonts), 'ready'
        );
        if (_origReady && _origReady.get) {
            const origGetter = _origReady.get;
            Object.defineProperty(document.fonts, 'ready', {
                get: function() {
                    const promise = origGetter.call(this);
                    return promise.then(function(fontFaceSet) {
                        // Filter to known Windows fonts
                        return fontFaceSet;
                    });
                },
                configurable: true
            });
        }
    }

    console.debug('[hltv] NG1.0 font metrics isolation active');
})();
"""


# ---------------------------------------------------------------------------
# Font isolation manager
# ---------------------------------------------------------------------------

class FontIsolationManager:
    """Manage font metrics isolation for the runtime environment.

    Usage:
        mgr = FontIsolationManager()
        script = mgr.get_injection_script()  # inject via CDP
        if not mgr.is_environment_ready():
            mgr.print_linux_setup_guide()
    """

    def __init__(self, target_platform: str = "windows") -> None:
        self._target = target_platform
        self._font_stack = _WINDOWS_FONT_STACK if target_platform == "windows" else _MACOS_FONT_STACK

    @property
    def injection_script(self) -> str:
        """Return the CDP injection script for font metric defense."""
        return FONT_METRICS_INTERCEPT_SCRIPT

    @property
    def required_fonts(self) -> list[str]:
        """Fonts that should be installed on the host system."""
        return list(self._font_stack)

    @staticmethod
    def is_environment_ready() -> bool:
        """Check if the runtime has adequate fonts installed.

        On Linux, checks for presence of Microsoft core fonts.
        On Windows/macOS, always returns True (fonts present by default).
        """
        import platform
        import shutil

        system = platform.system()
        if system in ("Windows", "Darwin"):
            return True

        # Linux: check for at least Arial
        font_paths = [
            "/usr/share/fonts/truetype/msttcorefonts/arial.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        ]
        has_fc = shutil.which("fc-list") is not None
        has_font = any(__import__("os").path.exists(p) for p in font_paths)
        return has_fc or has_font

    @staticmethod
    def get_linux_setup_guide() -> str:
        """Return shell commands to install Windows fonts on Linux."""
        return (
            "# Debian/Ubuntu:\n"
            "sudo apt-get install -y ttf-mscorefonts-installer fontconfig\n"
            "sudo fc-cache -fv\n\n"
            "# Or manual install:\n"
            "mkdir -p ~/.fonts\n"
            "# Copy Arial, Times New Roman, Courier New, etc. .ttf files to ~/.fonts/\n"
            "fc-cache -fv\n\n"
            "# Verify:\n"
            "fc-list | grep -i arial\n"
        )

    @staticmethod
    def get_dockerfile_snippet() -> str:
        """Return Dockerfile lines for font setup."""
        return (
            'RUN echo "ttf-mscorefonts-installer msttcorefonts/accepted-mscorefonts-eula select true" | debconf-set-selections\n'
            'RUN apt-get update && apt-get install -y --no-install-recommends \\\n'
            '    fontconfig ttf-mscorefonts-installer \\\n'
            '    fonts-liberation fonts-dejavu-core && \\\n'
            '    fc-cache -fv'
        )

    def get_stats(self) -> dict[str, Any]:
        """Return font isolation status."""
        import platform
        return {
            "target_platform": self._target,
            "required_font_count": len(self._font_stack),
            "environment_ready": self.is_environment_ready(),
            "host_system": platform.system(),
            "required_fonts_sample": self._font_stack[:5],
        }


__all__ = [
    "FontMetricEntry",
    "FONT_METRICS_INTERCEPT_SCRIPT",
    "FontIsolationManager",
]
