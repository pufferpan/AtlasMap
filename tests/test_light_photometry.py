"""光度学换算：UE 的流明/勒克斯 → Blender 的瓦特/辐照度。"""
import importlib.util
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts/official' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


photometry = load('map_light_photometry')


class PhotometryTests(unittest.TestCase):

    def test_lamp_watts_uses_photopic_conversion(self):
        # 1500 lm 的白炽灯 ≈ 2.2 W 辐射通量
        self.assertAlmostEqual(photometry.lamp_watts(1500), 1500 / 683.0, places=6)
        self.assertAlmostEqual(photometry.lamp_watts(0), photometry.MIN_ENERGY)

    def test_sun_strength_is_irradiance_and_clamped(self):
        self.assertAlmostEqual(photometry.sun_strength(6830), 10.0, places=6)
        self.assertEqual(photometry.sun_strength(10 ** 9), photometry.MAX_SUN)

    def test_lamp_watts_is_clamped_for_broken_records(self):
        self.assertEqual(photometry.lamp_watts(-5), photometry.MIN_ENERGY)
        self.assertEqual(photometry.lamp_watts(10 ** 12), photometry.MAX_LAMP)

    def test_sky_strength_stays_readable(self):
        self.assertEqual(photometry.sky_strength(0), photometry.SKY_FLOOR)
        self.assertEqual(photometry.sky_strength(5000), photometry.SKY_CEILING)
        self.assertAlmostEqual(photometry.sky_strength(1.0), 0.25, places=6)
        self.assertAlmostEqual(photometry.sky_strength(700), 700 / 683 * 0.25, places=4)

    def test_cutoff_radius_is_centimetres_to_metres(self):
        self.assertAlmostEqual(photometry.cutoff_meters(828.7), 8.287, places=4)
        self.assertEqual(photometry.cutoff_meters(-1), 0.0)
        self.assertEqual(photometry.cutoff_meters(10 ** 6), 200.0)

    def test_exposure_uses_sun_first_then_sky(self):
        # 白天太阳 1.757 W/m²：-log2(1.757/3) ≈ +0.77 EV
        self.assertAlmostEqual(photometry.exposure_ev(1.757, 0.5), 0.772, places=3)
        # 没太阳、天光 0.5：按 0.6×0.5 当主光，需要提亮
        self.assertEqual(photometry.exposure_ev(0.0, 0.5), 2.0)

    def test_exposure_is_clamped_and_never_nan(self):
        self.assertEqual(photometry.exposure_ev(0.0, 0.0), 2.0)
        self.assertEqual(photometry.exposure_ev(50.0, 1.0), -4.0)
        self.assertTrue(math.isfinite(photometry.exposure_ev(0.001, 0.0)))

    def test_sun_angle_has_a_sane_floor(self):
        self.assertAlmostEqual(photometry.sun_angle_radians(0.53), 0.00925, places=5)
        self.assertGreaterEqual(photometry.sun_angle_radians(0), 0.0045)
        self.assertLessEqual(photometry.sun_angle_radians(90), 0.5)


if __name__ == '__main__':
    unittest.main()
