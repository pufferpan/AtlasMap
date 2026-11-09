from __future__ import annotations

from ..theme import ThemeTokens


def qss_color(value: str) -> str:
    return value


def input_stylesheet(tokens: ThemeTokens) -> str:
    bg = (
        "rgba(255, 255, 255, 0.7)"
        if tokens.mode.value == "light"
        else "rgba(255, 255, 255, 0.0605)"
    )
    hover = (
        "rgba(249, 249, 249, 0.5)"
        if tokens.mode.value == "light"
        else "rgba(255, 255, 255, 0.0837)"
    )
    pressed = (
        "rgba(249, 249, 249, 0.3)"
        if tokens.mode.value == "light"
        else "rgba(255, 255, 255, 0.0326)"
    )
    border = (
        "rgba(0, 0, 0, 0.073)" if tokens.mode.value == "light" else "rgba(255, 255, 255, 0.053)"
    )
    lower = "rgba(0, 0, 0, 0.183)" if tokens.mode.value == "light" else "rgba(255, 255, 255, 0.08)"
    return f"""
QLineEdit {{
    background: {bg};
    color: {tokens.text};
    border: 1px solid {border};
    border-bottom: 1px solid {lower};
    border-radius: {tokens.radius}px;
    padding: 7px 10px;
    selection-background-color: {tokens.accent};
    font-size: {tokens.font_size}px;
}}
QLineEdit:hover {{
    background: {hover};
}}
QLineEdit:focus {{
    border: 1px solid {tokens.accent};
    border-bottom: 1px solid {tokens.accent};
    background: {pressed};
}}
QLineEdit:disabled {{
    color: {tokens.disabled};
}}
"""


def slider_stylesheet(tokens: ThemeTokens) -> str:
    groove = "rgba(0, 0, 0, 0.15)" if tokens.mode.value == "light" else "rgba(255, 255, 255, 0.18)"
    return f"""
QSlider::groove:horizontal {{
    height: 4px;
    background: {groove};
    border-radius: 2px;
}}
QSlider::sub-page:horizontal {{
    background: {tokens.accent};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    width: 16px;
    height: 16px;
    margin: -6px 0;
    border-radius: 8px;
    background: {tokens.surface};
    border: 2px solid {tokens.accent};
}}
QSlider::handle:horizontal:hover {{
    background: {tokens.surface_hover};
}}
"""


def progress_stylesheet(tokens: ThemeTokens) -> str:
    track = "rgba(0, 0, 0, 0.12)" if tokens.mode.value == "light" else "rgba(255, 255, 255, 0.18)"
    return f"""
QProgressBar {{
    background: {track};
    border: 0;
    border-radius: 3px;
    height: 6px;
    text-align: center;
    color: transparent;
}}
QProgressBar::chunk {{
    background: {tokens.accent};
    border-radius: 3px;
}}
"""
