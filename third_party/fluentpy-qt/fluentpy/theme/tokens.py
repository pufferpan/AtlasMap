from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


@dataclass(frozen=True)
class ThemeTokens:
    mode: ThemeMode
    custom_accent: str | None = None
    radius: int = 5
    spacing: int = 8
    font_size: int = 14
    animation_ms: int = 120

    @property
    def accent(self) -> str:
        if self.custom_accent:
            return self.custom_accent
        return "#009FAA" if self.mode is ThemeMode.LIGHT else "#29F1FF"

    @property
    def background(self) -> str:
        return "#f7f9fc" if self.mode is ThemeMode.LIGHT else "#1f2633"

    @property
    def background_inactive(self) -> str:
        return "#f2f3f6" if self.mode is ThemeMode.LIGHT else "#20242f"

    @property
    def surface(self) -> str:
        return "#ffffff" if self.mode is ThemeMode.LIGHT else "#2f3340"

    @property
    def surface_high(self) -> str:
        return "#f2f3f6" if self.mode is ThemeMode.LIGHT else "#1c202e"

    @property
    def surface_high_rgba(self) -> str:
        return (
            "rgba(242, 243, 246, 178)" if self.mode is ThemeMode.LIGHT else "rgba(28, 32, 46, 196)"
        )

    @property
    def surface_low(self) -> str:
        return "#fbfbfc" if self.mode is ThemeMode.LIGHT else "#303442"

    @property
    def surface_low_rgba(self) -> str:
        return (
            "rgba(251, 251, 252, 205)" if self.mode is ThemeMode.LIGHT else "rgba(48, 52, 66, 205)"
        )

    @property
    def acrylic(self) -> str:
        return (
            "rgba(255, 255, 255, 154)" if self.mode is ThemeMode.LIGHT else "rgba(20, 24, 31, 176)"
        )

    @property
    def acrylic_strong(self) -> str:
        return (
            "rgba(255, 255, 255, 218)" if self.mode is ThemeMode.LIGHT else "rgba(28, 32, 42, 224)"
        )

    @property
    def acrylic_highlight(self) -> str:
        return (
            "rgba(255, 255, 255, 102)"
            if self.mode is ThemeMode.LIGHT
            else "rgba(255, 255, 255, 22)"
        )

    @property
    def acrylic_inactive(self) -> str:
        return (
            "rgba(255, 255, 255, 172)" if self.mode is ThemeMode.LIGHT else "rgba(31, 34, 42, 196)"
        )

    @property
    def acrylic_strong_inactive(self) -> str:
        return (
            "rgba(255, 255, 255, 230)" if self.mode is ThemeMode.LIGHT else "rgba(32, 34, 40, 230)"
        )

    @property
    def acrylic_highlight_inactive(self) -> str:
        return (
            "rgba(255, 255, 255, 76)" if self.mode is ThemeMode.LIGHT else "rgba(255, 255, 255, 12)"
        )

    @property
    def surface_hover(self) -> str:
        return "#ffffff" if self.mode is ThemeMode.LIGHT else "#383d4d"

    @property
    def surface_pressed(self) -> str:
        return "#f1f2f5" if self.mode is ThemeMode.LIGHT else "#272c3b"

    @property
    def text(self) -> str:
        return "#1b1d22" if self.mode is ThemeMode.LIGHT else "#f5f7fb"

    @property
    def text_muted(self) -> str:
        return "#656b75" if self.mode is ThemeMode.LIGHT else "#c7ccd8"

    @property
    def border(self) -> str:
        return "#e3e7ee" if self.mode is ThemeMode.LIGHT else "#3b4154"

    @property
    def border_strong(self) -> str:
        return "#cdd3de" if self.mode is ThemeMode.LIGHT else "#4e566d"

    @property
    def shadow(self) -> str:
        return "#1a000000" if self.mode is ThemeMode.LIGHT else "#66000000"

    @property
    def disabled(self) -> str:
        return "#9a9a9a" if self.mode is ThemeMode.LIGHT else "#777777"


def default_tokens(mode: ThemeMode = ThemeMode.LIGHT) -> ThemeTokens:
    return ThemeTokens(mode=mode)
