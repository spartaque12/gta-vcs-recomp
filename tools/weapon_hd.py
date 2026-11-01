"""The converted weapons' full-detail side, for tools/weapon_convert.py (docs/game-internals.md 12g, WeaponHD.asi):

- project_bake: the atlas painted straight from the pack's full mesh - every triangle projected along its box view
  (the six axis directions, the two sides sharing texels) into a z-buffer, the outermost surface of a view keeping the
  texel, coloured from the pack's own texture. The game's small mesh and the full mesh both take their texture
  coordinates from the same views, so either draws with the same atlas (and its full-resolution PNG).
- write_hd: the pack's full mesh in the game's small model's batches: each batch of the small model (one VU1 MSCAL,
  <= 70 strip vertices; identified in the game by a hash of its positions) gets the full-detail triangles nearest to it,
  as a strip, for WeaponHD.asi to draw in its place through the mod API's lit refiner.
Standard library only."""
import math
import struct
from collections import defaultdict

import mesh_bake

MIRROR = {2: 3}  # the left side's view (+y) painted with the right side's (-y) texels


def view_of(n):
    k = max(range(6), key=lambda a: n[0] * mesh_bake.AXES[a][0][0] + n[1] * mesh_bake.AXES[a][0][1] + n[2] * mesh_bake.AXES[a][0][2])
    return MIRROR.get(k, k)


def tri_normal(ps):
    a, b, c = ps
    e1 = (b[0] - a[0], b[1] - a[1], b[2] - a[2])
    e2 = (c[0] - a[0], c[1] - a[1], c[2] - a[2])
    n = (e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0])
    l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2])
    return (n[0] / l, n[1] / l, n[2] / l) if l > 0 else None


def high_charts(parts):
    """the full mesh's triangles by view: (positions, triangles, [(view, triangle indices)], view per triangle)"""
    P, T, views = [], [], []
    by = defaultdict(list)
    for i, (tex, ps, uvs) in enumerate(parts):
        n = tri_normal(ps)
        k = view_of(n) if n else 3
        P += list(ps)
        T.append((3 * i, 3 * i + 1, 3 * i + 2))
        views.append(k)
        by[k].append(i)
    return P, T, sorted(by.items()), views


def project_bake(parts, views, place_of, s, w, h, textures, grow):
    """the atlas (w x h texels at s texels per metre) from the full mesh: per view a z-buffer (outermost wins)"""
    img = [None] * (w * h)
    depth = [1e30] * (w * h)
    for i, (tex, ps, uvs) in enumerate(parts):
        k = views[i]
        pl = place_of.get(k)
        if pl is None:
            continue
        A = mesh_bake.AXES[k][0]
        q = [mesh_bake.chart_uv(p, k, pl, s) for p in ps]
        dz = [-(p[0] * A[0] + p[1] * A[1] + p[2] * A[2]) for p in ps]
        den = (q[1][1] - q[2][1]) * (q[0][0] - q[2][0]) + (q[2][0] - q[1][0]) * (q[0][1] - q[2][1])
        if abs(den) < 1e-12:
            continue
        x0, x1 = max(0, int(math.floor(min(a[0] for a in q)))), min(w - 1, int(math.ceil(max(a[0] for a in q))))
        y0, y1 = max(0, int(math.floor(min(a[1] for a in q)))), min(h - 1, int(math.ceil(max(a[1] for a in q))))
        t = textures.get(tex)
        m = 0.5 / max(1e-9, math.sqrt(abs(den)))  # texels touched by the triangle's edge too (thin parts)
        for y in range(y0, y1 + 1):
            py = y + 0.5
            for x in range(x0, x1 + 1):
                px = x + 0.5
                a = ((q[1][1] - q[2][1]) * (px - q[2][0]) + (q[2][0] - q[1][0]) * (py - q[2][1])) / den
                b = ((q[2][1] - q[0][1]) * (px - q[2][0]) + (q[0][0] - q[2][0]) * (py - q[2][1])) / den
                c = 1 - a - b
                if a < -m or b < -m or c < -m:
                    continue
                a, b, c = max(0.0, a), max(0.0, b), max(0.0, c)
                sm = a + b + c
                a, b, c = a / sm, b / sm, c / sm
                z = dz[0] * a + dz[1] * b + dz[2] * c
                o = y * w + x
                if z >= depth[o]:
                    continue
                depth[o] = z
                if t:
                    u = uvs[0][0] * a + uvs[1][0] * b + uvs[2][0] * c
                    v = uvs[0][1] * a + uvs[1][1] * b + uvs[2][1] * c
                    img[o] = mesh_bake.sample(t, u, v)
                else:
                    img[o] = [128.0, 128.0, 128.0]
    painted = sum(1 for c in img if c is not None)

    def around(i):
        x, y = i % w, i // w
        if x > 0: yield i - 1
        if x < w - 1: yield i + 1
        if y > 0: yield i - w
        if y < h - 1: yield i + w
    front = {j for i, c in enumerate(img) if c is not None for j in around(i) if img[j] is None}
    for _ in range(grow):
        new = {}
        for i in front:
            cs = [img[j] for j in around(i) if img[j] is not None]
            if cs:
                new[i] = [sum(c[0] for c in cs) / len(cs), sum(c[1] for c in cs) / len(cs), sum(c[2] for c in cs) / len(cs)]
        for i, c in new.items():
            img[i] = c
        front = {j for i in new for j in around(i) if img[j] is None}
    out = bytearray(w * h * 4)
    for i, c in enumerate(img):
        c = c or (0, 0, 0)
        out[i * 4:i * 4 + 4] = bytes((min(255, max(0, int(c[0] + 0.5))), min(255, max(0, int(c[1] + 0.5))),
                                      min(255, max(0, int(c[2] + 0.5))), 255))
    return bytes(out), painted


def batch_hash(qpos):
    """FNV-1a 64 over the batch's vertex count and its positions as the VU holds them (int32 x, y, z each) - the same
    in WeaponHD.asi"""
    h = 0xCBF29CE484222325
    for b in struct.pack("<I", len(qpos)) + b"".join(struct.pack("<3i", *p) for p in qpos):
        h = ((h ^ b) * 0x100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


def strip_of(tris):
    """triangles -> one strip (runs joined by repeated vertices, every triangle its own run's winding kept loosely:
    weapons are drawn without culling)"""
    import weapon_convert
    seq, _ = weapon_convert.stripify2(tris)
    return seq


def write_hd(path, model_id, batches, parts, views, place_of, s, aw, ah, prm, crease=50.0, quant=None):
    """batches: [(the batch's int positions as the VU gets them, its real-space positions)] in draw order.
    The full mesh's triangles go to the batch with the nearest vertex; positions in the batch's units (the small model's
    int16 positions: (p - centre) / scale * 32768, quant = (centre, scale); its geometry header, not the batch's pos
    scale, which is 1 / 32768), normals unit, uv in the game's V2-8 units."""
    import weapon_convert
    # weld the full mesh's positions (smooth normals across its triangles)
    pidx, P, T, U = {}, [], [], []
    for i, (tex, ps, uvs) in enumerate(parts):
        t = []
        for p in ps:
            key = (round(p[0] * 1e5), round(p[1] * 1e5), round(p[2] * 1e5))
            if key not in pidx:
                pidx[key] = len(P)
                P.append(p)
            t.append(pidx[key])
        T.append(t)
    ok = [len(set(t)) == 3 for t in T]
    N = weapon_convert.grouped_normals(P, [t if o else [t[0], t[0], t[0]] for t, o in zip(T, ok)], crease)
    ku, kv = prm[2], prm[3]
    # nearest batch by vertex: a grid of the small model's vertices
    cell = 0.02
    grid = defaultdict(list)
    for bi, (_, real) in enumerate(batches):
        for p in real:
            grid[(int(math.floor(p[0] / cell)), int(math.floor(p[1] / cell)), int(math.floor(p[2] / cell)))].append((p, bi))

    def nearest(c):
        gx, gy, gz = (int(math.floor(c[k] / cell)) for k in range(3))
        for r in range(0, 40):
            best = None
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in range(-r, r + 1):
                        if max(abs(dx), abs(dy), abs(dz)) != r:
                            continue
                        for p, bi in grid.get((gx + dx, gy + dy, gz + dz), ()):
                            d = (p[0] - c[0]) ** 2 + (p[1] - c[1]) ** 2 + (p[2] - c[2]) ** 2
                            if best is None or d < best[0]:
                                best = (d, bi)
            if best:
                return best[1]
        return 0
    per = defaultdict(list)
    for i, (tex, ps, uvs) in enumerate(parts):
        if not ok[i]:
            continue
        c = [sum(p[k] for p in ps) / 3 for k in range(3)]
        per[nearest(c)].append(i)
    out = bytearray(struct.pack("<4sII", b"WHD1", model_id, len(batches)))
    total_v = total_i = 0
    for bi, (qpos, _) in enumerate(batches):
        ids = per.get(bi, [])
        vmap, vp, vn, vu, tl = {}, [], [], [], []
        for i in ids:
            k = views[i]
            pl = place_of[k]
            t = []
            for j, v in enumerate(T[i]):
                p = P[v]
                x, y = mesh_bake.chart_uv(p, k, pl, s)
                uvi = (x / aw / ku * 127.5, y / ah / kv * 127.5)
                key = (v, N[i][j], k)
                if key not in vmap:
                    vmap[key] = len(vp)
                    vp.append(p)
                    n = N[i][j]
                    l = math.sqrt(n[0] * n[0] + n[1] * n[1] + n[2] * n[2]) or 1.0
                    vn.append((n[0] / l, n[1] / l, n[2] / l))
                    vu.append(uvi)
                t.append(vmap[key])
            tl.append(tuple(t))
        seq = strip_of(tl) if tl else []
        if len(vp) > 65535:
            raise ValueError("batch %d: %d vertices" % (bi, len(vp)))
        out += struct.pack("<QII", batch_hash(qpos), len(vp), len(seq))
        qc, qsc = quant
        for p in vp:
            out += struct.pack("<3f", *((p[k] - qc[k]) / qsc[k] * 32768.0 for k in range(3)))
        for n in vn:
            out += struct.pack("<3f", *n)
        for u in vu:
            out += struct.pack("<2f", *u)
        out += struct.pack("<%dH" % len(seq), *seq)
        out += bytes(-len(out) & 3)
        total_v += len(vp)
        total_i += len(seq)
    with open(path, "wb") as f:
        f.write(out)
    return {"batches": len(batches), "triangles": sum(ok), "vertices": total_v, "indices": total_i, "bytes": len(out)}


def clean_parts(parts, log=print):
    """the full mesh without the back layers of double-sided surfaces (the same vertices wound the other way, or a
    layer lying on the front: weapon_convert.drop_back_faces) - both would fight in depth with different texels"""
    import weapon_convert
    pidx, P, T, src, seen = {}, [], [], [], set()
    for i, (tex, ps, uvs) in enumerate(parts):
        t = []
        for p in ps:
            k = (round(p[0] * 1e5), round(p[1] * 1e5), round(p[2] * 1e5))
            if k not in pidx:
                pidx[k] = len(P)
                P.append(p)
            t.append(pidx[k])
        if len(set(t)) < 3:
            continue
        key = frozenset(t)
        if key in seen:
            continue
        seen.add(key)
        T.append(t)
        src.append(i)
    keep_t, dropped = weapon_convert.drop_back_faces(P, T)
    kept = {tuple(t) for t in keep_t}
    out = [parts[src[j]] for j, t in enumerate(T) if tuple(t) in kept]
    log("  full mesh: %d triangles (%d back layers left out)" % (len(out), len(parts) - len(out)))
    return out
