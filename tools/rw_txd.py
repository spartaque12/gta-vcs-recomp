"""RenderWare TXD (GTA SA PC, D3D8/D3D9 native textures) reader: name -> (width, height, RGBA bytes) of the mip level
nearest to a wanted size. DXT1/3/5, 8888/888, 565, 1555, 4444, PAL8. Standard library only."""
import struct

def _chunks(d, p, end):
    while p + 12 <= end:
        t, s, v = struct.unpack_from("<III", d, p)
        yield t, p + 12, p + 12 + s
        p += 12 + s

def _565(c):
    r, g, b = (c >> 11) & 31, (c >> 5) & 63, c & 31
    return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)

def _dxt(data, w, h, kind):
    out = bytearray(w * h * 4)
    bs = 8 if kind == 1 else 16
    p = 0
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            blk = data[p:p + bs]; p += bs
            if kind == 1:
                cb, alpha = blk, None
            else:
                cb = blk[8:16]
                if kind == 3:
                    a64 = int.from_bytes(blk[0:8], "little")
                    alpha = [((a64 >> (4 * i)) & 15) * 17 for i in range(16)]
                else:
                    a0, a1 = blk[0], blk[1]
                    if a0 > a1:
                        pal = [a0, a1] + [((6 - i) * a0 + (i + 1) * a1) // 7 for i in range(6)]
                    else:
                        pal = [a0, a1] + [((4 - i) * a0 + (i + 1) * a1) // 5 for i in range(4)] + [0, 255]
                    bits = int.from_bytes(blk[2:8], "little")
                    alpha = [pal[(bits >> (3 * i)) & 7] for i in range(16)]
            c0, c1, idx = struct.unpack_from("<HHI", cb)
            r0, r1 = _565(c0), _565(c1)
            if kind != 1 or c0 > c1:
                cols = [r0 + (255,), r1 + (255,), tuple((2 * a + b) // 3 for a, b in zip(r0, r1)) + (255,),
                        tuple((a + 2 * b) // 3 for a, b in zip(r0, r1)) + (255,)]
            else:
                cols = [r0 + (255,), r1 + (255,), tuple((a + b) // 2 for a, b in zip(r0, r1)) + (255,), (0, 0, 0, 0)]
            for i in range(16):
                x, y = bx + (i & 3), by + (i >> 2)
                if x < w and y < h:
                    c = cols[(idx >> (2 * i)) & 3]
                    o = (y * w + x) * 4
                    out[o:o + 3] = bytes(c[:3])
                    out[o + 3] = c[3] if alpha is None else alpha[i]
    return bytes(out)

def _decode(fmt, rfmt, data, w, h, pal):
    if fmt in (b"DXT1", b"DXT3", b"DXT5"):
        return _dxt(data, w, h, int(fmt[3:4]))
    out = bytearray(w * h * 4)
    if pal is not None:
        for i in range(w * h):
            out[i * 4:i * 4 + 4] = pal[data[i] * 4:data[i] * 4 + 4]
        return bytes(out)
    base = rfmt & 0xF00
    if base in (0x500, 0x600):  # 8888 / 888: B G R A in memory
        for i in range(w * h):
            b, g, r, a = data[i * 4:i * 4 + 4]
            out[i * 4:i * 4 + 4] = bytes((r, g, b, a if base == 0x500 else 255))
        return bytes(out)
    for i in range(w * h):
        c = data[i * 2] | data[i * 2 + 1] << 8
        if base == 0x200:
            px = (((c >> 10) & 31) * 255 // 31, ((c >> 5) & 31) * 255 // 31, (c & 31) * 255 // 31, 255 if c & 0x8000 else 0)
        elif base == 0x300:
            px = (((c >> 8) & 15) * 17, ((c >> 4) & 15) * 17, (c & 15) * 17, (c >> 12) * 17)
        else:
            px = _565(c) + (255,)
        out[i * 4:i * 4 + 4] = bytes(px)
    return bytes(out)

def read_txd(path, want=256, only=None):
    """{name: (w, h, rgba)}: the largest mip level not above `want` (the base level when all are larger). only: a set of
    lower-case names to decode (the rest skipped)."""
    d = open(path, "rb").read()
    res = {}
    for t, a, b in _chunks(d, 0, len(d)):
        if t != 0x16:
            continue
        for t2, a2, b2 in _chunks(d, a, b):
            if t2 != 0x15:
                continue
            st = next(c for c in _chunks(d, a2, b2) if c[0] == 1)
            p = st[1]
            plat, filt = struct.unpack_from("<II", d, p)
            name = d[p + 8:p + 40].split(b"\0")[0].decode("latin1")
            if only is not None and name.lower() not in only:
                continue
            rfmt, d3d = struct.unpack_from("<II", d, p + 72)
            w, h, depth, levels, rtype, flags = struct.unpack_from("<HHBBBB", d, p + 80)
            q = p + 88
            # D3D9 (SA): the D3DFORMAT; D3D8 (VC, III): the last byte is the DXT compression (1, 3, 5; 0 none)
            fmt = struct.pack("<I", d3d) if plat == 9 else (b"DXT%d" % flags if flags in (1, 3, 5) else b"")
            pal = None
            if rfmt & 0x2000:
                pal = d[q:q + 1024]; q += 1024
            elif rfmt & 0x4000:
                pal = d[q:q + 64] + bytes(1024 - 64); q += 64 if plat == 9 else 128
            pick = None
            lw, lh = w, h
            for lv in range(levels):
                size = struct.unpack_from("<I", d, q)[0]; q += 4
                if pick is None and (max(lw, lh) <= want or lv == levels - 1) or lv == 0 and levels == 1:
                    pick = (lw, lh, d[q:q + size])
                q += size
                lw, lh = max(1, lw // 2), max(1, lh // 2)
                if pick:
                    break
            if pick is None:
                continue
            lw, lh, data = pick
            res[name.lower()] = (lw, lh, _decode(fmt, rfmt, data, lw, lh, pal))
    return res

if __name__ == "__main__":
    import sys
    d = open(sys.argv[1], "rb").read()
    for t, a, b in _chunks(d, 0, len(d)):
        for t2, a2, b2 in _chunks(d, a, b):
            if t2 == 0x15:
                st = next(c for c in _chunks(d, a2, b2) if c[0] == 1)
                p = st[1]
                plat = struct.unpack_from("<I", d, p)[0]
                name = d[p + 8:p + 40].split(b"\0")[0].decode("latin1")
                rfmt, d3d = struct.unpack_from("<II", d, p + 72)
                w, h, depth, levels, rtype, flags = struct.unpack_from("<HHBBBB", d, p + 80)
                print("%-24s plat %d rfmt %#x fmt %r %dx%d depth %d levels %d flags %#x" % (
                    name, plat, rfmt, struct.pack("<I", d3d), w, h, depth, levels, flags))
