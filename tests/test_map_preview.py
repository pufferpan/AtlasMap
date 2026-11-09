import io,json,os,tempfile,unittest
from pathlib import Path
import numpy as np
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from PySide6.QtCore import QPoint,Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from fluentpy import widgets as W
from core.map_preview import read_chunk,session,attach
from core.ue_pipeline import Step
from app.map_preview import MapPreview
from app.map_viewport import SoftwareViewport
from scripts.official.map_preview_geometry import simplify,transform_triangles


def triangle():
    return np.array([[0,0,0,0,0,1,.6,.7,.8],[4,0,0,0,0,1,.6,.7,.8],[0,4,1,0,0,1,.6,.7,.8]],np.float32)


class PreviewDataTests(unittest.TestCase):
    def test_saved_snapshot_is_scoped_to_exact_run_and_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            file=Path(folder)/'worker_0.npz'
            meta=dict(schema=1,run_id='run',worker=0)
            np.savez_compressed(file,vertices=triangle(),metadata=np.frombuffer(json.dumps(meta).encode(),np.uint8))
            vertices,result=read_chunk(file,'run',0)
            np.testing.assert_array_equal(vertices,triangle())
            for identity,index in [('old',0),('run',1)]:
                with self.assertRaises(ValueError):read_chunk(file,identity,index)
            np.savez_compressed(file,vertices=triangle()*np.nan,metadata=np.frombuffer(json.dumps(meta).encode(),np.uint8))
            with self.assertRaises(ValueError):read_chunk(file,'run',0)

    def test_worker_environment_preserves_export_settings_and_distinct_indices(self):
        preview=session('C:/Maps/Test','Test',2)
        children=[Step('one',[],env={'ORIGINAL':'one'}),Step('two',[],env={'ORIGINAL':'two'})]
        steps=attach([Step('serial',[]),Step('parallel',[],parallel_factory=lambda:children)],preview)
        workers=steps[1].parallel_factory()
        self.assertEqual(steps[0].env['ATLASMAP_PREVIEW_INDEX'],'0')
        self.assertEqual([s.env['ATLASMAP_PREVIEW_INDEX'] for s in workers],['0','1'])
        self.assertEqual([s.env['ORIGINAL'] for s in workers],['one','two'])
        self.assertTrue(all(s.env['ATLASMAP_PREVIEW_RUN_ID']==preview['run_id'] for s in workers))

    def test_simplification_is_bounded_without_touching_original_geometry(self):
        x,y=np.meshgrid(np.linspace(-4,4,70),np.linspace(-2,2,70))
        vertices=np.column_stack((x.ravel(),y.ravel(),np.sin(x).ravel()))
        grid=np.arange(len(vertices)).reshape(70,70)
        faces=np.column_stack((grid[:-1,:-1].ravel(),grid[1:,:-1].ravel(),grid[:-1,1:].ravel()))
        original=vertices.copy();result=simplify(vertices,faces,64)
        self.assertGreater(len(result),0);self.assertLessEqual(len(result),64)
        np.testing.assert_array_equal(vertices,original)
        self.assertTrue(np.isfinite(result).all())
        with self.assertRaises(ValueError):simplify(vertices*np.nan,faces)

    def test_affine_preview_uses_world_transform_and_recomputes_reflected_normals(self):
        faces=np.array([[[0,0,0],[1,0,0],[0,1,0]]],np.float32)
        matrix=np.diag([-2,3,4,1]);matrix[:3,3]=[10,20,30]
        actual,normals=transform_triangles(faces,matrix)
        np.testing.assert_allclose(actual,[[[10,20,30],[8,20,30],[10,23,30]]])
        np.testing.assert_allclose(normals,[[0,0,-1]])


class PreviewUiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.app=QApplication.instance() or QApplication([])

    def test_rotation_zoom_filter_and_nonmodal_native_controls(self):
        controller=MapPreview(session('C:/Maps/Test','Test',2))
        try:
            controller.data={0:(triangle(),{})};controller.show()
            self.assertIs(type(controller.dialog),W.FramelessDialog)
            self.assertIs(type(controller.selector),W.ComboBox)
            self.assertFalse(controller.dialog.isModal())
            self.assertFalse(controller.dialog.testAttribute(Qt.WA_QuitOnClose))
            canvas=controller.canvas;before=canvas.grab().toImage()
            yaw=canvas.yaw
            QTest.mousePress(canvas,Qt.LeftButton,pos=QPoint(100,100))
            QTest.mouseMove(canvas,QPoint(170,130),10)
            QTest.mouseRelease(canvas,Qt.LeftButton,pos=QPoint(170,130))
            self.assertNotEqual(canvas.yaw,yaw)
            self.assertNotEqual(before,canvas.grab().toImage())
            controller.selector.setCurrentIndex(1);self.assertEqual(canvas.selected,0)
            controller.feed('@ATLASMAP_PARALLEL '+json.dumps(dict(worker=1,stage='Test chunk',event='process')))
            self.assertEqual(controller.states[1],'running')
            controller.finish(-2);self.assertFalse(controller.auto_open)
        finally:controller.close();controller.deleteLater()
