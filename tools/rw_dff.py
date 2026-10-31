"""RenderWare (GTA SA PC) DFF reader: frames (names, matrices, parents), atomics, geometries (triangles, positions,
normals, uv, prelit, materials with texture names). Standard library only.  rwdff.py FILE -> summary"""
import struct, sys

def chunks(d, p, end):
    while p + 12 <= end:
        t, s, v = struct.unpack_from("<III", d, p)
        yield t, p + 12, p + 12 + s, v
        p += 12 + s

def find(d, p, end, t):
    return [c for c in chunks(d, p, end) if c[0] == t]

class Geometry:
    pass

def read_string(d, a, b):
    return d[a:b].split(b"\0")[0].decode("latin1")

def rw_version(libid):
    """a chunk's library id stamp -> 0x3VVRB version (0x1803FFFF SA: 0x36003, 0x1003FFFF VC: 0x34003, 0x0C02FFFF: 0x33002)"""
    if libid & 0xFFFF0000:
        return (((libid >> 14) & 0x3FF00) + 0x30000) | ((libid >> 16) & 0x3F)
    return libid << 8

def parse_material(d, a, b):
    m = {"texture": None, "color": (255, 255, 255, 255)}
    for t, ca, cb, v in chunks(d, a, b):
        if t == 1:
            flags, r, g, bl, al, unused, textured = struct.unpack_from("<I4BII", d, ca)
            m["color"] = (r, g, bl, al)
            m["textured"] = textured
        elif t == 6:
            for t2, c2a, c2b, _ in chunks(d, ca, cb):
                if t2 == 1:
                    m["filter"] = struct.unpack_from("<I", d, c2a)[0]
                if t2 == 2 and m["texture"] is None:
                    m["texture"] = read_string(d, c2a, c2b)
    return m

def parse_geometry(d, a, b):
    g = Geometry()
    st = find(d, a, b, 1)[0]
    p = st[1]
    flags, ntri, nv, nmorph = struct.unpack_from("<IIII", d, p)
    p += 16
    ver = st[3]
    native = flags & 0x01000000
    ntex = (flags >> 16) & 0xFF or (2 if flags & 0x80 else 1 if flags & 0x04 else 0)
    if rw_version(ver) < 0x34000:  # before 3.4: ambient / specular / diffuse after the header
        p += 12
    g.flags, g.prelit, g.uv, g.tris = flags, None, None, []
    if native:
        raise ValueError("native geometry")
    if flags & 0x08:
        g.prelit = [struct.unpack_from("<4B", d, p + 4 * i) for i in range(nv)]
        p += 4 * nv
    uvs = []
    for k in range(ntex):
        uvs.append([struct.unpack_from("<2f", d, p + 8 * i) for i in range(nv)])
        p += 8 * nv
    g.uv = uvs[0] if uvs else None
    for i in range(ntri):
        a1, a0, mat, a2 = struct.unpack_from("<4H", d, p + 8 * i)
        g.tris.append((a0, a1, a2, mat))
    p += 8 * ntri
    sphere = struct.unpack_from("<4f", d, p); p += 16
    hasv, hasn = struct.unpack_from("<II", d, p); p += 8
    g.pos = [struct.unpack_from("<3f", d, p + 12 * i) for i in range(nv)] if hasv else None
    p += 12 * nv if hasv else 0
    g.nrm = [struct.unpack_from("<3f", d, p + 12 * i) for i in range(nv)] if hasn else None
    g.materials = []
    binmesh = None
    for t, ca, cb, v in chunks(d, st[2], b):
        if t == 8:
            ml = find(d, ca, cb, 1)[0]
            n = struct.unpack_from("<I", d, ml[1])[0]
            idx = struct.unpack_from("<%di" % n, d, ml[1] + 4)
            mats = [parse_material(d, x[1], x[2]) for x in find(d, ca, cb, 7)]
            it = iter(mats)
            for i in idx:
                g.materials.append(next(it) if i < 0 else g.materials[i])
        elif t == 3:
            for t2, c2a, c2b, _ in chunks(d, ca, cb):
                if t2 == 0x50E:
                    binmesh = parse_binmesh(d, c2a)
    # Some exporters leave every triangle's material id at 0 and split the materials only in the BinMesh PLG (which
    # the PC games draw from): then the triangles come from it
    if binmesh and len(g.materials) > 1 and len({t[3] for t in g.tris}) == 1:
        g.tris = binmesh
    return g

def parse_binmesh(d, p):
    """the BinMesh PLG's triangles (v0, v1, v2, material): trilists, or strips with alternating winding"""
    flags, nmesh, _ = struct.unpack_from("<III", d, p)
    p += 12
    tris = []
    for _ in range(nmesh):
        n, mat = struct.unpack_from("<II", d, p)
        idx = struct.unpack_from("<%dI" % n, d, p + 8)
        p += 8 + 4 * n
        if flags & 1:
            for k in range(n - 2):
                a, b, c = idx[k], idx[k + 1], idx[k + 2]
                if a != b and b != c and a != c:
                    tris.append((b, a, c, mat) if k & 1 else (a, b, c, mat))
        else:
            tris += [(idx[k], idx[k + 1], idx[k + 2], mat) for k in range(0, n - 2, 3)]
    return tris

def parse_dff(path):
    d = open(path, "rb").read()
    clump = find(d, 0, len(d), 0x10)[0]
    a, b = clump[1], clump[2]
    frames = []
    fl = find(d, a, b, 0x0E)[0]
    st = find(d, fl[1], fl[2], 1)[0]
    n = struct.unpack_from("<I", d, st[1])[0]
    for i in range(n):
        v = struct.unpack_from("<12fiI", d, st[1] + 4 + 56 * i)
        frames.append({"rot": v[0:9], "pos": v[9:12], "parent": v[12], "name": ""})
    exts = find(d, st[2], fl[2], 3)
    for i, e in enumerate(exts[:n]):
        for t, ca, cb, _ in chunks(d, e[1], e[2]):
            if t == 0x253F2FE:
                frames[i]["name"] = d[ca:cb].decode("latin1")
    gl = find(d, a, b, 0x1A)[0]
    geoms = [parse_geometry(d, x[1], x[2]) for x in find(d, gl[1], gl[2], 0x0F)]
    atomics = []
    for t, ca, cb, _ in find(d, a, b, 0x14):
        s = find(d, ca, cb, 1)[0]
        fi, gi, fla = struct.unpack_from("<III", d, s[1])[:3]
        atomics.append({"frame": fi, "geometry": gi, "flags": fla})
    return frames, geoms, atomics

def ltm(frames, i):
    """frame i's matrix relative to the root (3x3 rows right, up, at + position), RW row-vector convention"""
    f = frames[i]
    r = f["rot"]; m = [list(r[0:3]), list(r[3:6]), list(r[6:9]), list(f["pos"])]
    while f["parent"] >= 0:
        pf = frames[f["parent"]]
        pr = pf["rot"]; pm = [pr[0:3], pr[3:6], pr[6:9], pf["pos"]]
        m = [[sum(m[k][j] * pm[j][c] for j in range(3)) for c in range(3)] for k in range(3)] + \
            [[sum(m[3][j] * pm[j][c] for j in range(3)) + pm[3][c] for c in range(3)]]
        f = pf
    return m

if __name__ == "__main__":
    frames, geoms, atomics = parse_dff(sys.argv[1])
    for i, f in enumerate(frames):
        print("frame %2d parent %2d %-22s pos %s" % (i, f["parent"], f["name"], " ".join("%.3f" % x for x in f["pos"])))
    for a in atomics:
        g = geoms[a["geometry"]]
        print("atomic frame %d (%s) geom %d flags %#x: %d verts %d tris, flags %#x, mats %s" % (
            a["frame"], frames[a["frame"]]["name"], a["geometry"], a["flags"], len(g.pos), len(g.tris), g.flags,
            sorted(set((m["texture"], m["color"]) for m in g.materials))))
