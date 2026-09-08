import struct
import zlib
from pathlib import Path
import pytest
from propforge.native_textures import check_dds, check_files


def fixture(tmp_path, fmt=b"DXT1"):
    name="pf_test_d"
    sizes=[128,32,8,8,8] if fmt==b"DXT1" else [256,64,16,16,16]
    dds=bytearray(128+sum(sizes))
    dds[:4]=b"DDS "
    struct.pack_into("<II",dds,12,16,16)
    struct.pack_into("<I",dds,28,5)
    dds[84:88]=fmt
    dds[128:]=bytes((i%251 for i in range(sum(sizes))))
    source=tmp_path/(name+'.dds'); source.write_bytes(dds)
    # One 512-byte system page plus one 512-byte graphics page.
    data=bytearray(1024)
    data[256:256+len(name)+1]=name.encode()+b'\0'
    struct.pack_into('<Q',data,0x28,0x50000100)
    struct.pack_into('<HH',data,0x50,16,16)
    data[0x58:0x5c]=fmt; data[0x5d]=5
    struct.pack_into('<Q',data,0x70,0x60000000)
    data[512:512+sum(sizes)]=dds[128:]
    target=tmp_path/'pack.ytd'
    def write():
        comp=zlib.compressobj(wbits=-15)
        target.write_bytes(b'RSC7'+struct.pack('<III',13,1<<27,1<<27)+comp.compress(data)+comp.flush())
    write()
    return target,source,data,write


@pytest.mark.parametrize('fmt',[b'DXT1',b'DXT5'])
def test_all_mips_including_one_pixel_are_compared(tmp_path,fmt):
    target,source,_,_=fixture(tmp_path,fmt)
    report=check_files(target,{source.stem:source})
    assert report['textures'][0]['levels']==5
    assert report['textures'][0]['all_mip_blocks_identical']


def test_corrupt_last_mip_is_rejected(tmp_path):
    target,source,data,write=fixture(tmp_path)
    data[512+183]^=1
    write()
    with pytest.raises(ValueError,match='Mip-Bloecke'):
        check_files(target,{source.stem:source})


def test_truncated_dds_is_rejected(tmp_path):
    _,source,_,_=fixture(tmp_path)
    with pytest.raises(ValueError,match='Nutzdatenlaenge'):
        check_dds(source.read_bytes()[:-8])


def test_unrecognized_native_header_is_rejected(tmp_path):
    target,source,_,_=fixture(tmp_path)
    target.write_bytes(b'bad file')
    with pytest.raises(ValueError,match='RSC7'):
        check_files(target,{source.stem:source})
