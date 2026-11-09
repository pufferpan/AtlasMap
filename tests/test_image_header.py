import io
import struct
import unittest
from PIL import Image
from scripts.official.map_image_header import image_dimensions


class ImageHeaderTests(unittest.TestCase):
    def test_serialized_png_jpeg_dimensions_match_real_decoder(self):
        for format in ('PNG','JPEG'):
            for size in ((1,1),(19,37),(1024,512)):
                with self.subTest(format=format,size=size):
                    output=io.BytesIO();Image.new('RGB',size).save(output,format=format)
                    blob=output.getvalue()
                    self.assertEqual(image_dimensions(blob),list(size))
                    self.assertEqual(Image.open(io.BytesIO(blob)).size,size)

    def test_large_png_header_does_not_allocate_pixel_storage(self):
        blob=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',32768,16384)
        self.assertEqual(image_dimensions(blob),[32768,16384])

    def test_truncated_invalid_and_zero_size_are_rejected(self):
        valid=b'\x89PNG\r\n\x1a\n'+struct.pack('>I',13)+b'IHDR'+struct.pack('>II',10,20)
        for blob in (b'',valid[:23],valid[:12]+b'bad!'+valid[16:],valid[:16]+bytes(8),b'\xff\xd8\xff\xc0\x00\x08\x08\x00'):
            with self.subTest(blob=blob),self.assertRaises(ValueError):image_dimensions(blob,'fixture')

    def test_jpeg_skips_metadata_before_frame(self):
        blob=b'\xff\xd8\xff\xe1\x00\x06ABCD\xff\xc2\x00\x0b\x08'+struct.pack('>HH',17,25)+b'\x01\x01\x11\x00'
        self.assertEqual(image_dimensions(blob),[25,17])
