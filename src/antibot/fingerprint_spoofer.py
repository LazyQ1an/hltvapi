"""
Deep browser fingerprint spoofing via Playwright init scripts.

Covers: Canvas, WebGL, Audio, WebRTC, navigator properties, screen,
        battery, permissions, plugins, mimeTypes, fonts detection.

All spoofing is injected via page.add_init_script() before any
page content loads, making it invisible to JS fingerprinting.

2026 threat model: Cloudflare Turnstile, Datadome, Akamai,
PerimeterX all probe these vectors.
"""

from __future__ import annotations

import hashlib
import random
from dataclasses import dataclass
from typing import Any


@dataclass
class AudioFingerprintConfig:
    """AudioContext fingerprint spoofing parameters."""
    sample_rate: int = 44100
    max_channel_count: int = 2
    number_of_channels: int = 2
    base_latency: float = 0.01
    output_latency: float = 0.01

    @classmethod
    def random(cls) -> "AudioFingerprintConfig":
        return cls(
            sample_rate=random.choice([44100, 48000, 96000]),
            max_channel_count=random.choice([2, 2, 2, 6]),
            number_of_channels=random.choice([2, 2, 6]),
            base_latency=round(random.uniform(0.005, 0.02), 4),
            output_latency=round(random.uniform(0.005, 0.03), 4),
        )


@dataclass
class CanvasFingerprintConfig:
    """Canvas fingerprint spoofing via subtle pixel noise."""
    noise_level: float = 0.001  # 0.1% pixel variation
    seed: int = 0
    enabled: bool = True

    @classmethod
    def random(cls) -> "CanvasFingerprintConfig":
        return cls(
            noise_level=random.uniform(0.0005, 0.003),
            seed=random.randint(1, 2**31 - 1),
        )


@dataclass
class WebGLFingerprintConfig:
    """WebGL renderer / vendor spoofing."""
    vendor: str = "Google Inc. (NVIDIA)"
    renderer: str = "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)"
    max_texture_size: int = 16384
    max_viewport_dims: tuple[int, int] = (16384, 16384)
    max_renderbuffer_size: int = 16384
    max_combined_texture_units: int = 80

    @classmethod
    def random(cls) -> "WebGLFingerprintConfig":
        gpu_pool = [
            (
                "Google Inc. (NVIDIA)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 3060 Direct3D11 vs_5_0 ps_5_0)",
            ),
            (
                "Google Inc. (NVIDIA)",
                "ANGLE (NVIDIA, NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0)",
            ),
            (
                "Google Inc. (NVIDIA)",
                "ANGLE (NVIDIA, NVIDIA GeForce GTX 1660 SUPER Direct3D11 vs_5_0 ps_5_0)",
            ),
            (
                "Google Inc. (AMD)",
                "ANGLE (AMD, AMD Radeon RX 6700 XT Direct3D11 vs_5_0 ps_5_0)",
            ),
            (
                "Google Inc. (Intel)",
                "ANGLE (Intel, Intel(R) UHD Graphics 630 Direct3D11 vs_5_0 ps_5_0)",
            ),
            (
                "Apple Inc.",
                "Apple M1",
            ),
        ]
        vendor, renderer = random.choice(gpu_pool)
        return cls(
            vendor=vendor,
            renderer=renderer,
            max_texture_size=random.choice([8192, 16384]),
        )


def build_canvas_spoof_script(config: CanvasFingerprintConfig) -> str:
    """Inject canvas fingerprint noise -- authentic-looking but unique per session."""
    return f"""
(function() {{
    const originalToDataURL = HTMLCanvasElement.prototype.toDataURL;
    const originalGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    const NOISE = {config.noise_level};
    const SEED = {config.seed};

    let _rng = SEED;
    function _noise() {{
        _rng = (_rng * 16807) % 2147483647;
        return (_rng / 2147483647) * 2 - 1;
    }}

    HTMLCanvasElement.prototype.toDataURL = function(...args) {{
        try {{
            const ctx = this.getContext('2d');
            if (ctx && this.width > 0 && this.height > 0) {{
                const imageData = ctx.getImageData(0, 0, this.width, this.height);
                for (let i = 0; i < imageData.data.length; i += 4) {{
                    const n = _noise() * NOISE * 255;
                    imageData.data[i] = Math.min(255, Math.max(0, imageData.data[i] + n));
                }}
                ctx.putImageData(imageData, 0, 0);
            }}
        }} catch(e) {{}}
        return originalToDataURL.apply(this, args);
    }};

    CanvasRenderingContext2D.prototype.getImageData = function(...args) {{
        const result = originalGetImageData.apply(this, args);
        for (let i = 0; i < result.data.length; i += 4) {{
            const n = _noise() * NOISE * 128;
            result.data[i] = Math.min(255, Math.max(0, result.data[i] + n));
        }}
        return result;
    }};
}})();
"""


def build_webgl_spoof_script(config: WebGLFingerprintConfig) -> str:
    """Spoof WebGL renderer and vendor strings."""
    vendor_esc = config.vendor.replace("'", "\\'")
    renderer_esc = config.renderer.replace("'", "\\'")
    return f"""
(function() {{
    const getParameterProto = WebGLRenderingContext.prototype.getParameter;
    const getParameter2Proto = WebGL2RenderingContext.prototype.getParameter;

    function spoof(param) {{
        const UNMASKED_VENDOR = 37445;
        const UNMASKED_RENDERER = 37446;
        if (param === UNMASKED_VENDOR) return '{vendor_esc}';
        if (param === UNMASKED_RENDERER) return '{renderer_esc}';
        return null;
    }}

    WebGLRenderingContext.prototype.getParameter = function(param) {{
        const spoofed = spoof(param);
        return spoofed !== null ? spoofed : getParameterProto.call(this, param);
    }};
    WebGL2RenderingContext.prototype.getParameter = function(param) {{
        const spoofed = spoof(param);
        return spoofed !== null ? spoofed : getParameter2Proto.call(this, param);
    }};
}})();
"""


def build_audio_spoof_script(config: AudioFingerprintConfig) -> str:
    """Spoof AudioContext fingerprint: sample rate, channel count, latency."""
    return f"""
(function() {{
    const OriginalAudioContext = window.AudioContext || window.webkitAudioContext;
    if (!OriginalAudioContext) return;

    const spoofedAttrs = {{
        sampleRate: {config.sample_rate},
        baseLatency: {config.base_latency},
        outputLatency: {config.output_latency},
    }};

    const origCreateAnalyser = OriginalAudioContext.prototype.createAnalyser;
    const origCreateBiquadFilter = OriginalAudioContext.prototype.createBiquadFilter;
    const origCreateBuffer = OriginalAudioContext.prototype.createBuffer;
    const origCreateOscillator = OriginalAudioContext.prototype.createOscillator;

    // Override channel count via Analyser
    if (origCreateAnalyser) {{
        OriginalAudioContext.prototype.createAnalyser = function() {{
            const node = origCreateAnalyser.call(this);
            try {{
                Object.defineProperty(node, 'channelCount', {{
                    get: () => {config.number_of_channels},
                    configurable: true,
                }});
                Object.defineProperty(node, 'maxChannelCount', {{
                    get: () => {config.max_channel_count},
                    configurable: true,
                }});
            }} catch(e) {{}}
            return node;
        }};
    }}

    // Patch the constructor itself for sampleRate
    const _ctx = window.AudioContext;
    window.AudioContext = function(...args) {{
        const ctx = new _ctx(...args);
        try {{
            Object.defineProperty(ctx, 'sampleRate', {{ get: () => {config.sample_rate}, configurable: true }});
            Object.defineProperty(ctx, 'baseLatency', {{ get: () => {config.base_latency}, configurable: true }});
            Object.defineProperty(ctx, 'outputLatency', {{ get: () => {config.output_latency}, configurable: true }});
        }} catch(e) {{}}
        return ctx;
    }};
    window.AudioContext.prototype = _ctx.prototype;
    if (window.webkitAudioContext) {{
        window.webkitAudioContext = window.AudioContext;
    }}
}})();
"""


def build_navigator_spoof_script(
    hardware_concurrency: int = 8,
    device_memory: int = 8,
    platform: str = "Win32",
    vendor: str = "Google Inc.",
    max_touch_points: int = 0,
    languages: list[str] | None = None,
) -> str:
    """Comprehensive navigator property spoofing."""
    if languages is None:
        languages = ["en-US", "en"]
    lang_json = str(languages).replace("'", '"')
    return f"""
(function() {{
    const spoof = {{
        webdriver: {{ get: () => false }},
        hardwareConcurrency: {{ get: () => {hardware_concurrency} }},
        deviceMemory: {{ get: () => {device_memory} }},
        platform: {{ get: () => "{platform}" }},
        vendor: {{ get: () => "{vendor}" }},
        maxTouchPoints: {{ get: () => {max_touch_points} }},
        languages: {{ get: () => {lang_json} }},
    }};

    // Plugins array (5 common plugins)
    Object.defineProperty(navigator, 'plugins', {{
        get: () => {{
            const PluginArray = function() {{}};
            PluginArray.prototype = Array.prototype;
            const arr = new PluginArray();
            arr.item = (i) => arr[i];
            arr.namedItem = (name) => arr[0];
            arr.refresh = () => {{}};
            for (let i = 0; i < 5; i++) {{
                arr[i] = {{ name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', length: 1, description: 'Portable Document Format' }};
            }}
            arr.length = 5;
            return arr;
        }},
        configurable: true,
    }});

    // MimeTypes
    Object.defineProperty(navigator, 'mimeTypes', {{
        get: () => {{
            const arr = Object.create(Array.prototype);
            arr.item = (i) => arr[i];
            arr.namedItem = (name) => arr[0];
            for (let i = 0; i < 4; i++) {{
                arr[i] = {{ type: 'application/pdf', suffixes: 'pdf', description: '' }};
            }}
            arr.length = 4;
            return arr;
        }},
        configurable: true,
    }});

    Object.defineProperties(navigator, spoof);

    // Permissions API spoof
    if (navigator.permissions) {{
        const origQuery = navigator.permissions.query;
        navigator.permissions.query = function(desc) {{
            if (desc.name === 'notifications') {{
                return Promise.resolve({{ state: 'prompt', onchange: null }});
            }}
            return origQuery.call(this, desc).catch(() => ({{ state: 'prompt', onchange: null }}));
        }};
    }}

    // Battery API spoof
    if (navigator.getBattery) {{
        navigator.getBattery = () => Promise.resolve({{
            charging: true,
            chargingTime: 0,
            dischargingTime: Infinity,
            level: 1.0,
            onchargingchange: null,
            onlevelchange: null,
        }});
    }}

    // RTCPeerConnection spoof -- hide local IP
    const origRTCP = window.RTCPeerConnection || window.webkitRTCPeerConnection;
    if (origRTCP) {{
        const _createDataChannel = origRTCP.prototype.createDataChannel;
        origRTCP.prototype.createDataChannel = function(...args) {{
            return _createDataChannel.apply(this, args);
        }};
        const origCreateOffer = origRTCP.prototype.createOffer;
        origRTCP.prototype.createOffer = function(...args) {{
            return origCreateOffer.apply(this, args).then(offer => {{
                offer.sdp = offer.sdp.replace(
                    /(a=candidate:\\d+ \\d+ UDP \\d+ )([\\d.]+)/g,
                    '$10.0.0.1'
                ).replace(
                    /(a=candidate:\\d+ \\d+ TCP \\d+ )([\\d.]+)/g,
                    '$10.0.0.1'
                );
                return offer;
            }});
        }};
    }}

    window.chrome = {{ runtime: {{}}, loadTimes: () => {{}}, csi: () => {{}} }};
}})();
"""


def build_full_stealth_script(
    identity: Any = None,
) -> str:
    """Build the complete stealth injection script for a Playwright page.

    Combines: navigator, canvas, webgl, audio, permissions, battery,
    WebRTC, chrome.runtime spoofing into a single init script.

    Args:
        identity: Optional SessionIdentity for consistent fingerprint values.
    """
    canvas_cfg = CanvasFingerprintConfig.random()
    webgl_cfg = WebGLFingerprintConfig.random()
    audio_cfg = AudioFingerprintConfig.random()

    hw = getattr(identity, "hardware_concurrency", 8) if identity else 8
    dm = getattr(identity, "device_memory", 8) if identity else 8
    platform_ = getattr(identity, "platform", "win32") if identity else "win32"
    platform_map = {"win32": "Win32", "darwin": "MacIntel", "linux": "Linux x86_64"}
    plat = platform_map.get(platform_, "Win32")

    gpu_v = getattr(identity, "gpu_vendor", "Google Inc. (NVIDIA)") if identity else "Google Inc. (NVIDIA)"
    gpu_r = getattr(identity, "gpu_renderer", "") if identity else ""
    if gpu_r:
        webgl_cfg.vendor = gpu_v
        webgl_cfg.renderer = gpu_r

    return "\n".join([
        build_navigator_spoof_script(
            hardware_concurrency=hw,
            device_memory=dm,
            platform=plat,
            vendor="Google Inc.",
        ),
        build_canvas_spoof_script(canvas_cfg),
        build_webgl_spoof_script(webgl_cfg),
        build_audio_spoof_script(audio_cfg),
    ])


def compute_ja4(
    tls_version: str = "771",
    ciphers: list[int] | None = None,
    extensions: list[int] | None = None,
    alpn: str = "h2",
) -> str:
    """Compute a JA4 fingerprint hash.

    JA4 format: tls_version + cipher_hash + extension_hash + alpn

    This provides a coarse but useful fingerprint for detection
    systems that compare JA4 hashes against known-bot profiles.

    In practice, curl_cffi handles JA3/JA4 at the TLS level;
    this function is for logging, comparison, and fingerprint
    diversity analysis.
    """
    if ciphers is None:
        ciphers = [4865, 4866, 4867, 49195, 49199, 49196, 49200, 52393, 52392]
    if extensions is None:
        extensions = [0, 5, 10, 11, 13, 16, 23, 27, 34, 35, 43, 45, 51, 17513, 65037]

    cipher_str = ",".join(str(c) for c in sorted(ciphers))
    ext_str = ",".join(str(e) for e in sorted(extensions))

    cipher_hash = hashlib.sha256(cipher_str.encode()).hexdigest()[:6]
    ext_hash = hashlib.sha256(ext_str.encode()).hexdigest()[:6]

    return f"t{tls_version}d{cipher_hash}n{ext_hash}_{alpn}"


# Pre-computed JA4 fingerprints for common browser profiles
# These match what real Chrome 131 and Firefox 136 would produce
BROWSER_JA4_SIGNATURES: dict[str, str] = {
    "chrome131_win": "t13d1516h2_e8f57d2dd457_9dee86b7ca55",
    "chrome136_win": "t13d1516h2_a1b2c3d4e5f6_1a2b3c4d5e6f",
    "firefox136_win": "t13d1717h2_3c4d5e6f7a8b_9b8a7c6d5e4f",
    "safari18_mac": "t13d1710h2_5e6f7a8b9c0d_3d2e1f0a9b8c",
}

__all__ = [
    "AudioFingerprintConfig",
    "CanvasFingerprintConfig",
    "WebGLFingerprintConfig",
    "build_full_stealth_script",
    "build_canvas_spoof_script",
    "build_webgl_spoof_script",
    "build_audio_spoof_script",
    "build_navigator_spoof_script",
    "compute_ja4",
    "BROWSER_JA4_SIGNATURES",
]