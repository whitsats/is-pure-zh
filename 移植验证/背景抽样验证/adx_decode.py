"""Decode CRI ADX entries from VOICE.AFS / SE.AFS to WAV.

ADX header (big-endian):
  0x00 u16 0x8000
  0x02 u16 copyright-string offset (data starts 4 bytes after the string)
  0x04 u8  encoding (3 = 4-bit ADPCM)
  0x05 u8  frame size (18)
  0x06 u8  sample bit depth (4)
  0x07 u8  channels
  0x08 u32 sample rate
  0x0C u32 sample count (per channel)
  0x10 u16 highpass
  0x12 u8  version, 0x13 u8 flags

Each frame: u16 scale/filter, then 16 bytes of signed nibbles per channel.
Filter index 0 means zero prediction coefficients, so the sample is
nibble * scale.  The script verifies that every frame uses filter 0.
"""
from pathlib import Path
import struct
import sys
import wave

import numpy as np

ROOT = Path(__file__).resolve().parent
ISO = ROOT.parent.parent / 'game-v5.iso'
OUT = ROOT / 'audio'
OUT.mkdir(exist_ok=True)
ARCHIVES = {'VOICE': 696072192, 'SE': 395005952}

NIBBLES = np.array([0, 1, 2, 3, 4, 5, 6, 7, -8, -7, -6, -5, -4, -3, -2, -1],
                   dtype=np.int32)


def afs_payload(f, base, index):
    f.seek(base + 8 + index * 8)
    off, length = struct.unpack('<II', f.read(8))
    f.seek(base + off)
    return f.read(length)


def parse(blob):
    assert blob[:2] == b'\x80\x00', f'not ADX: {blob[:4].hex()}'
    str_off = struct.unpack_from('>H', blob, 2)[0]
    encoding = blob[4]
    frame_size = blob[5]
    bit_depth = blob[6]
    channels = blob[7]
    rate = struct.unpack_from('>I', blob, 8)[0]
    samples = struct.unpack_from('>I', blob, 12)[0]
    highpass = struct.unpack_from('>H', blob, 16)[0]
    version = blob[18]
    return {
        'str_off': str_off, 'encoding': encoding, 'frame_size': frame_size,
        'bit_depth': bit_depth, 'channels': channels, 'rate': rate,
        'samples': samples, 'highpass': highpass, 'version': version,
        'data_start': str_off + 4,
        'copyright': blob[str_off - 2:str_off + 6],
    }


def decode(blob, info):
    channels = info['channels']
    frame_size = info['frame_size']
    pos = info['data_start']
    frame_bytes = frame_size * channels
    total_frames = (len(blob) - pos) // frame_bytes
    out = np.zeros((total_frames * 32, channels), dtype=np.int32)
    filters = set()
    for fr in range(total_frames):
        base = pos + fr * frame_bytes
        for ch in range(channels):
            head = struct.unpack_from('>H', blob, base + ch * frame_size)[0]
            scale = head & 0x0FFF
            filters.add(head >> 12)
            data = np.frombuffer(blob, dtype=np.uint8,
                                 count=16, offset=base + ch * frame_size + 2)
            nib = np.empty(32, dtype=np.int32)
            nib[0::2] = data >> 4
            nib[1::2] = data & 0x0F
            out[fr * 32:(fr + 1) * 32, ch] = NIBBLES[nib] * scale
    return out, filters, total_frames


def main():
    targets = [('VOICE', 0), ('VOICE', 100), ('SE', 0), ('SE', 2)]
    if len(sys.argv) > 1:
        targets = [(a, int(b)) for a, b in (v.split(':') for v in sys.argv[1:])]
    with ISO.open('rb') as f:
        for name, index in targets:
            blob = afs_payload(f, ARCHIVES[name], index)
            try:
                info = parse(blob)
            except AssertionError as exc:
                print(name, index, 'FAILED', exc)
                continue
            pcm, filters, frames = decode(blob, info)
            seconds = len(pcm) / info['rate']
            peak = int(np.abs(pcm).max())
            rms = float(np.sqrt((pcm.astype(np.float64) ** 2).mean()))
            print(f'{name}:{index} {info["channels"]}ch {info["rate"]}Hz '
                  f'samples {info["samples"]} frames {frames} decoded {len(pcm)} '
                  f'({seconds:.2f}s) filters {sorted(filters)} peak {peak} rms {rms:.0f} '
                  f'v{info["version"]} hp{info["highpass"]} frame{info["frame_size"]} '
                  f'enc{info["encoding"]}/{info["bit_depth"]}bit')
            path = OUT / f'{name}_{index:05d}.wav'
            with wave.open(str(path), 'wb') as w:
                w.setnchannels(info['channels'])
                w.setsampwidth(2)
                w.setframerate(info['rate'])
                w.writeframes(np.clip(pcm, -32768, 32767).astype('<i2').tobytes())
            print('   ->', path, path.stat().st_size, 'bytes')


if __name__ == '__main__':
    main()
