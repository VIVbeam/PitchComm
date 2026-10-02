"""Validate the PCM asset set and write a dictionary manifest (stdlib only)."""
import argparse
import struct
from pathlib import Path
from generate_catalog import ROOT, load, clips

def wav_frames(path):
    """Match include/pc/wav.h so ready on this laptop means parsable on a unit."""
    def invalid():
        raise ValueError(f'{path.name}: invalid receiver WAV; requires mono PCM 16-bit 16 kHz, consistent headers and 1..80000 samples')
    with path.open('rb') as source:
        size=path.stat().st_size
        header=source.read(12)
        if size<44 or len(header)!=12 or header[:4]!=b'RIFF' or header[8:]!=b'WAVE': invalid()
        end=8+int.from_bytes(header[4:8],'little')
        if not 44<=end<=size: invalid()
        position=12; seen_format=False; samples=None
        while position+8<=end:
            source.seek(position); chunk=source.read(8)
            if len(chunk)!=8: invalid()
            length=int.from_bytes(chunk[4:],'little'); start=position+8
            if start+length>end: invalid()
            if chunk[:4]==b'fmt ':
                if seen_format or length<16: invalid()
                format_bytes=source.read(16)
                if len(format_bytes)!=16 or struct.unpack('<HHIIHH',format_bytes)!=(1,1,16000,32000,2,16): invalid()
                seen_format=True
            elif chunk[:4]==b'data':
                if samples is not None or not length or length%2 or length>160000: invalid()
                samples=length//2
            position=start+length+(length%2)
            if position>end: invalid()
        if not seen_format or samples is None or position!=end: invalid()
        return samples

def check(write_manifest=False, root=None, quiet=False):
    root=ROOT if root is None else Path(root)
    data, dictionary=load(root)
    total=0
    lengths={}
    for name, _ in clips(data):
        path=root/f'data/audio/{name}'
        frames=wav_frames(path)
        total+=path.stat().st_size
        lengths[name]=frames
    for pitch in data['pitches']:
        for height in range(1,4):
            for side in range(1,4):
                if lengths[f'p{pitch["key"]:02d}.wav']+lengths[f'h{height}.wav']+lengths[f's{side}.wav']>80000:
                    raise ValueError('A complete three-part pitch exceeds five seconds')
    filesystem_bytes=sum(path.stat().st_size for path in (root/'data').rglob('*') if path.is_file())
    if max(total,filesystem_bytes)>1800000:
        raise ValueError('Asset set exceeds the reserved filesystem budget')
    manifest=root/'data/audio/manifest.txt'
    expected=f'{dictionary:08x}\n'
    if write_manifest: manifest.write_text(expected,encoding='ascii')
    elif not manifest.exists() or manifest.read_text(encoding='ascii')!=expected:
        raise ValueError('Manifest does not match the call dictionary; regenerate the audio set')
    if not quiet: print(f'Validated {len(lengths)} clips, {total} bytes, dictionary {dictionary:08x}')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write-manifest',action='store_true')
    check(parser.parse_args().write_manifest)

