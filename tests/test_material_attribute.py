"""材质编译脚本：ShaderNodeAttribute（顶点色/自定义属性）必须能编译，不能整批失败。

Dam_Iris_Long3 的材质里带 Attribute 节点，编译时抛
`Unsupported contributing node ATTRIBUTE`，三个并行 worker 全挂。
"""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "official" / "compile_iceland_ue_materials.py"


def load_generator():
    """脚本是 Blender 里跑的整段程序，只取类定义那一段，别执行前面的 manifest 读取。"""
    text = SCRIPT.read_text(encoding="utf-8")
    head = text[text.index("def number("):text.index("\nvariants=")]
    namespace: dict = {"__name__": "compile_materials_probe"}
    exec(compile(head, str(SCRIPT), "exec"), namespace)      # noqa: S102  仅测试用
    return namespace["Generator"], namespace["Ref"]


class AttributeNodeTest(unittest.TestCase):
    def setUp(self):
        self.Generator, self.Ref = load_generator()

    def _node(self, name: str, attribute_type: str = "GEOMETRY") -> dict:
        return {
            "id": 7,
            "type": "ATTRIBUTE",
            "attribute_name": name,
            "attribute_type": attribute_type,
            "inputs": [],
            "outputs": [{"name": "Color"}, {"name": "Vector"}, {"name": "Fac"}, {"name": "Alpha"}],
        }

    def _generate(self, node: dict, output: int):
        material = {"nodes": [node]}
        generator = self.Generator(material, {}, {})
        self.Ref.kind = 1
        return generator, generator.output(node["id"], output)

    def test_vertex_colour_maps_to_vc(self):
        for name in ("Col", "col", "", "VertexColor", "vc"):
            with self.subTest(name=name):
                generator, ref = self._generate(self._node(name), 0)
                self.assertEqual(ref.code, "VC")
                self.assertIn("VC", generator.globals)

    def test_vector_and_alpha_outputs(self):
        generator, ref = self._generate(self._node("Col"), 1)
        self.assertEqual(ref.kind, 3)
        self.assertIn("VC", ref.code)
        generator, ref = self._generate(self._node("Col"), 2)
        self.assertEqual((ref.kind, ref.code), (1, "VC.a"))
        generator, ref = self._generate(self._node("Col"), 3)
        self.assertEqual((ref.kind, ref.code), (1, "VC.a"))

    def test_unknown_attribute_degrades_to_zero(self):
        generator, ref = self._generate(self._node("BakeMask"), 0)
        self.assertEqual((ref.kind, ref.code), (4, "float4(0,0,0,0)"))
        generator, ref = self._generate(self._node("BakeMask"), 1)
        self.assertEqual((ref.kind, ref.code), (3, "float3(0,0,0)"))
        generator, ref = self._generate(self._node("BakeMask"), 2)
        self.assertEqual((ref.kind, ref.code), (1, "0.0"))

    def test_non_geometry_scope_still_raises(self):
        with self.assertRaises(RuntimeError):
            self._generate(self._node("Foo", attribute_type="VIEW_LAYER"), 0)


if __name__ == "__main__":
    unittest.main()
