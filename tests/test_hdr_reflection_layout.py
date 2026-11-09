import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest

BASE=Path(__file__).resolve().parents[1]
HELPER=BASE/'tools/scene_state/bin/Release/net10.0/scene-state.exe'


@unittest.skipUnless(HELPER.is_file(),'Build the net10 source helper before native layout tests')
class HdrLayoutTests(unittest.TestCase):
    def fixture(self):
        header=struct.pack('<3I2BI',7,0,0,1,0,1)
        record=struct.pack('<5I2fI',1,2,3,4,4,0,1,1)+bytes(144+20)
        return header+record+struct.pack('<I',288)+bytes(288)+struct.pack('<I',144)+bytes(144)+struct.pack('<I',0x9e2a83c1)

    def run_fixture(self,root,data):
        file=root/'assets/FixtureReflection.uexp';file.parent.mkdir(exist_ok=True)
        file.write_bytes(data)
        sentinel=root/'state-index.json';sentinel.write_text('{"complete":true,"sentinel":"existing"}')
        original=sentinel.read_bytes()
        result=subprocess.run([str(HELPER),'--reflection-only',str(BASE/'runtime'),'unused.json',str(root),str(root)],
            capture_output=True,text=True,encoding='utf-8',timeout=30,creationflags=0x08000000)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(sentinel.read_bytes(),original,'Diagnostic decoder must not overwrite a source index')
        return json.loads((root/'reflection-cubemaps.json').read_text())

    def test_valid_bound_record_exports_six_float16_faces(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);document=self.run_fixture(root,self.fixture())
            self.assertEqual(document['failures'],[])
            self.assertEqual(len(document['captures']),1)
            row=document['captures'][0]
            self.assertEqual(row['guid'],'00000001000000020000000300000004')
            data=(root/row['texture']).read_bytes()
            self.assertEqual(data[:4],b'DDS ')
            self.assertEqual(struct.unpack_from('<I',data,128)[0],10) # RGBA16_FLOAT
            self.assertEqual(struct.unpack_from('<I',data,28)[0],3)
            self.assertEqual(len(data),148+6*(4*4+2*2+1)*8)

    def test_truncated_wrong_mip_size_and_unknown_versions_are_not_importable(self):
        data=self.fixture()
        variants=[data[:-7],data[:12]+b'\x02'+data[13:],data[:214]+struct.pack('<I',123)+data[218:]]
        for bad in variants:
            with self.subTest(length=len(bad)),tempfile.TemporaryDirectory() as folder:
                result=self.run_fixture(Path(folder),bad)
                self.assertEqual(result['captures'],[])
                self.assertTrue(result['failures'])
