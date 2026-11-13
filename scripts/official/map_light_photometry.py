"""UE 光照强度 → Blender 辐射度。

UE 的光源强度是光度量：平行光是勒克斯（lux，照度），点光/聚光/矩形光是流明（lm，光通量）。
Blender 要的是辐射度量：SUN 的 strength 是辐照度 W/m²，其余灯具的 Power 是辐射通量 W。
两者的换算系数是 683 lm/W（555 nm 的光视效能），以前乘 0.01 是凭感觉拍的，
结果室内灯亮到发白、顶光又偏暗。
"""
from __future__ import annotations

import math

LUMENS_PER_WATT = 683.0
MIN_ENERGY = 0.002
MAX_SUN = 120.0
MAX_LAMP = 300.0
SKY_FLOOR = 0.08
SKY_CEILING = 1.5
SKY_SCALE = 0.25


def lamp_watts(intensity: float) -> float:
    """点光 / 聚光 / 矩形光：流明 → 辐射通量 W。"""
    return min(MAX_LAMP, max(MIN_ENERGY, max(0.0, float(intensity)) / LUMENS_PER_WATT))


def sun_strength(intensity: float) -> float:
    """平行光：勒克斯 → 辐照度 W/m²。"""
    return min(MAX_SUN, max(MIN_ENERGY, max(0.0, float(intensity)) / LUMENS_PER_WATT))


def sky_strength(intensity: float) -> float:
    """天光：UE 的 SkyLight 强度 → 世界背景辐亮度系数。

    ≤50 视为无单位倍率（UE 默认 1.0），再乘 0.25——实测 0.5 倍率直接当 0.5 会把整张图
    冲成灰白、阴影也糊掉；>50 视为 cd/m²，除 683 后再折算。最后钳在 0.08–1.5。
    """
    value = max(0.0, float(intensity))
    if value > 50.0:
        value = value / LUMENS_PER_WATT
    value *= SKY_SCALE
    return min(SKY_CEILING, max(SKY_FLOOR, value))


def cutoff_meters(radius_cm: float, *, ceiling: float = 200.0) -> float:
    """UE 的衰减半径（厘米）→ Blender 自定义距离（米）。"""
    return min(ceiling, max(0.0, float(radius_cm)) / 100.0)


def sun_angle_radians(source_angle_deg: float = 0.53) -> float:
    """太阳视直径，默认 0.53°；角度太小阴影会硬得像刀切。"""
    return max(0.0045, min(0.5, float(source_angle_deg) * 3.141592653589793 / 180.0))


def exposure_ev(sun: float, sky: float, *, floor: float = -4.0, ceiling: float = 2.0) -> float:
    """按主光强度算曝光补偿：3 W/m² 上下当作 0 EV。

    以前只看太阳，夜里没太阳的地图会被硬拉到 +2 EV 把场景烧白；现在天光也算进主光，
    有太阳仍以太阳为主（天光只按 0.6 计），两者都暗时才往上提。
    """
    key = max(float(sun), 0.6 * float(sky), 0.02)
    return min(ceiling, max(floor, -math.log2(key / 3.0)))
