"""Read serialized texture dimensions without allocating a decoded image."""
import struct


def image_dimensions(blob, name='image'):
    data=memoryview(blob)
    if len(data)>=24 and data[:8]==b'\x89PNG\r\n\x1a\n':
        if data[8:16]!=b'\x00\x00\x00\rIHDR':
            raise ValueError('Invalid PNG header: '+name)
        width,height=struct.unpack_from('>II',data,16)
    elif len(data)>=4 and data[:2]==b'\xff\xd8':
        offset=2
        while offset<len(data):
            if data[offset]!=255:raise ValueError('Invalid JPEG marker: '+name)
            while offset<len(data) and data[offset]==255:offset+=1
            if offset>=len(data):break
            marker=data[offset];offset+=1
            if marker in (0xd9,0xda):break
            if marker==1 or 0xd0<=marker<=0xd7:continue
            if offset+2>len(data):break
            size=struct.unpack_from('>H',data,offset)[0]
            if size<2 or offset+size>len(data):break
            if marker in (0xc0,0xc1,0xc2,0xc3,0xc5,0xc6,0xc7,0xc9,0xca,0xcb,0xcd,0xce,0xcf):
                if size<8:break
                height,width=struct.unpack_from('>HH',data,offset+3)
                break
            offset+=size
        else:raise ValueError('JPEG has no frame header: '+name)
        if 'width' not in locals():raise ValueError('Truncated JPEG frame header: '+name)
    else:
        raise ValueError('Unsupported or truncated serialized texture (expected PNG/JPEG): '+name)
    if not width or not height:raise ValueError('Empty serialized texture: '+name)
    return [width,height]
