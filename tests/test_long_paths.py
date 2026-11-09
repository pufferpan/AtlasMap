"""Exercise the native-writer/Python-reader boundary with real long paths."""
import hashlib
from contextlib import contextmanager
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from core.full_parallel_export import merge_source_states
from core.parallel_export import checked_file, read, write
from scripts.official.map_io import io_path, metadata_path, share_file


@contextmanager
def long_path_directory():
    with tempfile.TemporaryDirectory() as directory:
        root = io_path(directory).resolve()
        try:
            yield Path(directory)
        finally:
            # tempfile's ordinary-path cleanup cannot remove >260-char trees
            # on machines whose Win32 long-path policy is disabled.
            temporary_root = io_path(tempfile.gettempdir()).resolve()
            if root == temporary_root or not root.is_relative_to(temporary_root):
                raise ValueError('Test cleanup escaped the temporary directory')
            shutil.rmtree(root)


class LongPathTests(unittest.TestCase):
    def test_merged_environment_textures_keep_long_path_conflict_checks(self):
        with long_path_directory() as directory:
            roots = [Path(directory)/f'Chunk_{i:03d}' for i in range(2)]
            relative = '/'.join(['textures', 'reflection_' + 'x'*90,
                'sky_' + 'y'*90, 'volume_' + 'z'*40 + '.hdr'])
            for i, root in enumerate(roots):
                folder = root/'source-render'
                target = io_path(folder/relative)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b'original HDR pixels')
                write(folder/'raw.json', [])
                write(folder/'state-index.json', dict(complete=True, schema=1, mapRoot='Test',
                    exporter={'sha256':'same'}, levels=[{'level':str(i),'lights':[]}],
                    packages={str(i):'raw.json'}, preservedAssets=[]))
                write(folder/'environment.json', dict(skies=[dict(source_material='sky',
                    source_texture='sky cube', texture={'RelativePath':relative})]))
                write(folder/'reflection-cubemaps.json', dict(captures=[dict(guid='guid',
                    source='capture', texture=relative)]))
            destination = Path(directory)/'merged'
            result = merge_source_states(roots, destination, 'Test')
            self.assertEqual(len(result['environment']['skies']), 1)
            self.assertEqual(len(result['reflection_cubemaps']['captures']), 1)
            merge_source_states(roots, destination, 'Test')
            published = checked_file(destination/'source-render', relative)
            self.assertEqual(published.read_bytes(), b'original HDR pixels')
            published.unlink()  # Break the hardlink before simulating a conflicting output.
            published.write_bytes(b'conflicting HDR pixels')
            with self.assertRaisesRegex(ValueError, '环境贴图冲突'):
                merge_source_states(roots, destination, 'Test')

    def test_merge_preserves_long_bake_payloads_and_duplicate_hashes(self):
        with long_path_directory() as directory:
            roots = [Path(directory)/f'Chunk_{i:03d}' for i in range(2)]
            # Keep each component below NTFS's limit, but exceed MAX_PATH.
            key = '/'.join(['DeltaForce/Content/Maps/BombDefusal_Watch',
                'ClientConfig/ReflectionCaptureCubes_HD',
                'BombDefusal_Watch_TODLight_110/GlobalReflection_Watch_2',
                'nested_' + 'x'*90, 'Sunny_Time_1209600000_Volume_Default.uasset'])
            payload = b'original cooked reflection payload'
            row = dict(path=key, bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            for i, root in enumerate(roots):
                folder = root/'source-render'
                target = io_path(folder/'assets'/key)
                self.assertGreater(len(str(target)), 260)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(payload)
                write(folder/'raw.json', [])
                write(folder/'state-index.json', dict(complete=True, schema=1, mapRoot='Test',
                    exporter={'sha256':'same'}, levels=[{'level':str(i),'lights':[]}],
                    packages={str(i):'raw.json'}, preservedAssets=[row]))
            destination = Path(directory)/'merged'
            result = merge_source_states(roots, destination, 'Test')
            self.assertTrue(result['complete'])
            self.assertEqual(result['preservedAssets'], [row])
            self.assertEqual(checked_file(destination/'source-render', 'assets/'+key).read_bytes(), payload)
            self.assertEqual(read(destination/'source-render/state-index.json')['preservedAssets'], [row])
            # A resumed merge must also replace existing long destinations.
            merge_source_states(roots, destination, 'Test')
            io_path(roots[1]/'source-render/assets'/key).write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError, '校验失败'):
                merge_source_states(roots, destination, 'Test')

    def test_file_checks_keep_traversal_absolute_and_symlink_escapes_blocked(self):
        with long_path_directory() as directory:
            root = Path(directory)/'root'
            root.mkdir()
            outside = Path(directory)/'outside.bin'
            outside.write_bytes(b'outside')
            for relative in ('../outside.bin', str(outside), str(io_path(outside))):
                with self.subTest(relative=relative), self.assertRaisesRegex(ValueError, '越界'):
                    checked_file(root, relative)
            with self.assertRaisesRegex(ValueError, '缺少文件'):
                checked_file(root, 'missing.bin')
            link = root/'linked.bin'
            try:
                link.symlink_to(outside)
            except OSError:
                return  # Windows accounts without symlink privileges.
            with self.assertRaisesRegex(ValueError, '越界'):
                checked_file(root, 'linked.bin')

    @unittest.skipUnless(os.name == 'nt', 'Win32 path syntax')
    def test_extended_paths_are_idempotent_and_support_unc(self):
        path = io_path(r'C:\exports\chunk\..\asset.bin')
        self.assertEqual(str(path), '\\\\?\\C:\\exports\\asset.bin')
        self.assertEqual(io_path(path), path)
        self.assertEqual(str(io_path(r'\\server\share\asset.bin')), '\\\\?\\UNC\\server\\share\\asset.bin')
        self.assertEqual(metadata_path(path), r'C:\exports\asset.bin')
        self.assertEqual(metadata_path(io_path(r'\\server\share\asset.bin')), r'\\server\share\asset.bin')

    def test_atomic_copy_fallback_can_publish_long_paths(self):
        from unittest.mock import patch
        with long_path_directory() as directory:
            source = Path(directory)/'source.bin'
            source.write_bytes(b'source bytes')
            target = Path(directory)/('x'*90)/('y'*90)/('z'*90)/'destination.bin'
            with patch('scripts.official.map_io.os.link', side_effect=OSError('cross-volume')):
                share_file(source, target)
            self.assertEqual(io_path(target).read_bytes(), b'source bytes')
            self.assertEqual(list(io_path(target.parent).glob('*.partial')), [])


if __name__ == '__main__':
    unittest.main()
