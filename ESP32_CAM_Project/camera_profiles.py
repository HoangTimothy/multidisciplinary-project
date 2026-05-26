from __future__ import annotations

from typing import Final


RESOLUTION_SPECS: Final[dict[str, dict[str, str]]] = {
    "QVGA": {"macro": "FRAMESIZE_QVGA", "dimensions": "320x240"},
    "VGA": {"macro": "FRAMESIZE_VGA", "dimensions": "640x480"},
    "SVGA": {"macro": "FRAMESIZE_SVGA", "dimensions": "800x600"},
    "XGA": {"macro": "FRAMESIZE_XGA", "dimensions": "1024x768"},
    "SXGA": {"macro": "FRAMESIZE_SXGA", "dimensions": "1280x1024"},
    "UXGA": {"macro": "FRAMESIZE_UXGA", "dimensions": "1600x1200"},
}

_RESOLUTION_ALIASES: Final[dict[str, str]] = {
    "QVGA": "QVGA",
    "320X240": "QVGA",
    "320X240PX": "QVGA",
    "VGA": "VGA",
    "640X480": "VGA",
    "640X480PX": "VGA",
    "SVGA": "SVGA",
    "800X600": "SVGA",
    "800X600PX": "SVGA",
    "XGA": "XGA",
    "1024X768": "XGA",
    "1024X768PX": "XGA",
    "SXGA": "SXGA",
    "1280X1024": "SXGA",
    "1280X1024PX": "SXGA",
    "UXGA": "UXGA",
    "1600X1200": "UXGA",
    "1600X1200PX": "UXGA",
}


def normalize_frame_size(value: str) -> str:
    normalized = value.strip().upper().replace("FRAMESIZE_", "")
    normalized = normalized.replace(" ", "").replace("-", "").replace("_", "")
    normalized = normalized.replace("×", "X")
    if normalized in _RESOLUTION_ALIASES:
        return _RESOLUTION_ALIASES[normalized]
    if normalized in RESOLUTION_SPECS:
        return normalized
    supported = ", ".join(sorted(RESOLUTION_SPECS))
    raise ValueError(f"Unsupported frame size '{value}'. Supported: {supported} or dimensions like 640x480")


def frame_size_macro(value: str) -> str:
    return RESOLUTION_SPECS[normalize_frame_size(value)]["macro"]


def frame_size_dimensions(value: str) -> str:
    return RESOLUTION_SPECS[normalize_frame_size(value)]["dimensions"]


def frame_size_label(value: str) -> str:
    name = normalize_frame_size(value)
    return f"{name} ({RESOLUTION_SPECS[name]['dimensions']})"


def supported_frame_sizes() -> list[str]:
    return list(RESOLUTION_SPECS.keys())
