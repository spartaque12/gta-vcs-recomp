"""Texture baking for tools/weapon_convert.py: a simplified mesh gets a texture atlas of its own and the detailed model's
textures are baked onto it. Standard library only.

The detailed SA weapons are cut into many small texture islands (a third of their edges are texture seams), so a
simplifier that keeps their texture coordinates stops at thousands of triangles. Here the geometry is simplified on
its own (tools/mesh_simplify.py, positions only), cut into charts by facing (the six axis directions: box mapping, no
folds), the charts are packed into one atlas, and every atlas texel takes its colour from the detailed model's surface
under it - a ray along the low mesh's normal from just outside (raised details such as screw heads come along), the
nearest surface point when the ray finds nothing. The result is one texture and one material per weapon, as VCS's own.
"""
import math
from collections import defaultdict

# ---- vectors --------------------------------------------------------------------------------------------------------
def sub(a, b): return (a[0] - b[0], a[1] - b[1], a[2] - b[2])
def add(a, b): return (a[0] + b[0], a[1] + b[1], a[2] + b[2])
def mul(a, s): return (a[0] * s, a[1] * s, a[2] * s)
def dot(a, b): return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]
def cross(a, b): return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])
def unit(a):
    n = math.sqrt(dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0 else (0.0, 0.0, 1.0)

def closest_on_triangle(p, a, b, c):
    """(point, (wa, wb, wc)) - Ericson, Real-Time Collision Detection 5.1.5"""
    ab, ac, ap = sub(b, a), sub(c, a), sub(p, a)
    d1, d2 = dot(ab, ap), dot(ac, ap)
    if d1 <= 0 and d2 <= 0:
        return a, (1.0, 0.0, 0.0)
    bp = sub(p, b)
    d3, d4 = dot(ab, bp), dot(ac, bp)
    if d3 >= 0 and d4 <= d3:
        return b, (0.0, 1.0, 0.0)
    vc = d1 * d4 - d3 * d2
    if vc <= 0 and d1 >= 0 and d3 <= 0:
        v = d1 / (d1 - d3)
        return add(a, mul(ab, v)), (1 - v, v, 0.0)
    cp = sub(p, c)
    d5, d6 = dot(ab, cp), dot(ac, cp)
    if d6 >= 0 and d5 <= d6:
        return c, (0.0, 0.0, 1.0)
    vb = d5 * d2 - d1 * d6
    if vb <= 0 and d2 >= 0 and d6 <= 0:
        w = d2 / (d2 - d6)
        return add(a, mul(ac, w)), (1 - w, 0.0, w)
    va = d3 * d6 - d5 * d4
    if va <= 0 and (d4 - d3) >= 0 and (d5 - d6) >= 0:
        w = (d4 - d3) / ((d4 - d3) + (d5 - d6))
        return add(b, mul(sub(c, b), w)), (0.0, 1 - w, w)
    den = 1.0 / (va + vb + vc)
    v, w = vb * den, vc * den
    return add(a, add(mul(ab, v), mul(ac, w))), (1 - v - w, v, w)

def ray_triangle(o, d, a, b, c):
    """Moeller-Trumbore, both sides: (t, (wa, wb, wc)) or None"""
    e1, e2 = sub(b, a), sub(c, a)
    pv = cross(d, e2)
    det = dot(e1, pv)
    if -1e-14 < det < 1e-14:
        return None
    inv = 1.0 / det
    tv = sub(o, a)
    u = dot(tv, pv) * inv
    if u < -1e-6 or u > 1 + 1e-6:
        return None
    qv = cross(tv, e1)
    v = dot(d, qv) * inv
    if v < -1e-6 or u + v > 1 + 1e-6:
        return None
    return dot(e2, qv) * inv, (1 - u - v, u, v)

class Grid:
    """triangles hashed by their boxes into cubic cells"""
    def __init__(self, tris, cell):
        self.cell = cell
        self.cells = defaultdict(list)
        for i, (a, b, c) in enumerate(tris):
            lo = [int(math.floor(min(a[k], b[k], c[k]) / cell)) for k in range(3)]
            hi = [int(math.floor(max(a[k], b[k], c[k]) / cell)) for k in range(3)]
            for x in range(lo[0], hi[0] + 1):
                for y in range(lo[1], hi[1] + 1):
                    for z in range(lo[2], hi[2] + 1):
                        self.cells[(x, y, z)].append(i)

    def box(self, lo, hi):
        c = self.cell
        out = set()
        for x in range(int(math.floor(lo[0] / c)), int(math.floor(hi[0] / c)) + 1):
            for y in range(int(math.floor(lo[1] / c)), int(math.floor(hi[1] / c)) + 1):
                for z in range(int(math.floor(lo[2] / c)), int(math.floor(hi[2] / c)) + 1):
                    l = self.cells.get((x, y, z))
                    if l:
                        out.update(l)
        return out

# ---- charts and the atlas -------------------------------------------------------------------------------------------
SUBSAMPLES = ((-0.25, -0.25), (0.25, -0.25), (-0.25, 0.25), (0.25, 0.25))

AXES = [((1, 0, 0), (0, 1, 0), (0, 0, 1)), ((-1, 0, 0), (0, -1, 0), (0, 0, 1)),
        ((0, 1, 0), (-1, 0, 0), (0, 0, 1)), ((0, -1, 0), (1, 0, 0), (0, 0, 1)),
        ((0, 0, 1), (1, 0, 0), (0, 1, 0)), ((0, 0, -1), (1, 0, 0), (0, -1, 0))]

def make_charts(P, T):
    """Six views of the whole model (box mapping): every triangle goes to the axis direction it faces most, each
    view's triangles projected along it, the outermost first - where surfaces overlap in a view (a part inside or
    behind another) the outer one gets the texels (bake writes empty texels only) and the hidden one shares them.
    -> [(axis index, triangles outermost first)]"""
    views = defaultdict(list)
    for i, t in enumerate(T):
        n = cross(sub(P[t[1]], P[t[0]]), sub(P[t[2]], P[t[0]]))
        k = max(range(6), key=lambda a: dot(n, AXES[a][0]))
        c = ((P[t[0]][0] + P[t[1]][0] + P[t[2]][0]) / 3, (P[t[0]][1] + P[t[1]][1] + P[t[2]][1]) / 3,
             (P[t[0]][2] + P[t[1]][2] + P[t[2]][2]) / 3)
        views[k].append((-dot(c, AXES[k][0]), i))
    return [(k, [i for _, i in sorted(views[k])]) for k in sorted(views)]

def pack(charts, P, T, aw, ah, pad=2):
    """Place every chart in an aw x ah atlas at one scale (texels per metre), shelf packing; -> (scale, placements)
    placements[c] = (x0, y0, rotated, umin, vmin) in texels"""
    boxes = []
    for label, members in charts:
        _, U, V = AXES[label]
        us = [dot(P[v], U) for i in members for v in T[i]]
        vs = [dot(P[v], V) for i in members for v in T[i]]
        boxes.append((min(us), min(vs), max(us) - min(us), max(vs) - min(vs)))

    def attempt(s):
        items = []
        for c, (u0, v0, w, h) in enumerate(boxes):
            tw, th = int(math.ceil(w * s)) + 2 * pad, int(math.ceil(h * s)) + 2 * pad
            rot = th > tw
            if rot:
                tw, th = th, tw
            if tw > aw:
                return None
            items.append((th, tw, c, rot))
        items.sort(reverse=True)
        place = [None] * len(boxes)
        x = y = shelf = 0
        for th, tw, c, rot in items:
            if x + tw > aw:
                y += shelf
                x = shelf = 0
            if y + th > ah:
                return None
            place[c] = (x + pad, y + pad, rot, boxes[c][0], boxes[c][1])
            x += tw
            shelf = max(shelf, th)
        return place

    lo, hi = 1.0, 1e5
    best = attempt(lo)
    if best is None:
        raise ValueError("charts do not fit in %dx%d" % (aw, ah))
    for _ in range(40):
        mid = math.sqrt(lo * hi)
        p = attempt(mid)
        if p is None:
            hi = mid
        else:
            lo, best = mid, p
        if hi / lo < 1.01:
            break
    return lo, best

def chart_uv(p, label, place, s):
    """a position's atlas texel coordinates in its chart"""
    _, U, V = AXES[label]
    x0, y0, rot, umin, vmin = place
    a, b = (dot(p, U) - umin) * s, (dot(p, V) - vmin) * s
    if rot:
        a, b = b, a
    return x0 + a, y0 + b

# ---- textures of the detailed model -----------------------------------------------------------------------------------
def sample(tex, u, v):
    """bilinear, repeating (as SA's textures address)"""
    w, h, px = tex
    x, y = u * w - 0.5, v * h - 0.5
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = x - x0, y - y0
    out = [0.0, 0.0, 0.0]
    for dy, wy in ((0, 1 - fy), (1, fy)):
        for dx, wx in ((0, 1 - fx), (1, fx)):
            o = (((y0 + dy) % h) * w + (x0 + dx) % w) * 4
            k = wx * wy
            out[0] += px[o] * k; out[1] += px[o + 1] * k; out[2] += px[o + 2] * k
    return out

def bake(P, T, charts, place, s, aw, ah, high, textures, reach, log=print):
    """P, T: the simplified mesh; high: [(texture, (p0, p1, p2), (uv0, uv1, uv2))] the detailed model;
    textures: name -> (w, h, rgba). -> (rgba bytes of aw x ah, filled mask)"""
    hp = [h[1] for h in high]
    ext = max(max(p[k] for t in hp for p in t) - min(p[k] for t in hp for p in t) for k in range(3))
    grid = Grid(hp, max(reach, ext / 96))
    hn = [unit(cross(sub(b, a), sub(c, a))) for a, b, c in hp]
    img = [None] * (aw * ah)
    stats = {"ray": 0, "near": 0, "none": 0}

    def colour(i, w):
        tex, _, uv = high[i]
        u = uv[0][0] * w[0] + uv[1][0] * w[1] + uv[2][0] * w[2]
        v = uv[0][1] * w[0] + uv[1][1] * w[1] + uv[2][1] * w[2]
        t = textures.get(tex)
        return sample(t, u, v) if t else [128.0, 128.0, 128.0]

    def surface_colour(p, n):
        """the detailed surface's colour under p: along -n from `reach` outside (facing surfaces only), else the
        nearest point"""
        o = add(p, mul(n, reach))
        e = sub(p, mul(n, 2 * reach))
        best = None
        d = mul(n, -1.0)
        for i in grid.box([min(o[k], e[k]) for k in range(3)], [max(o[k], e[k]) for k in range(3)]):
            if dot(hn[i], n) <= 0.05:
                continue  # only surfaces facing the same way
            r = ray_triangle(o, d, *hp[i])
            if r and 0 <= r[0] <= 3 * reach and (best is None or r[0] < best[0]):
                best = (r[0], i, r[1])
        if best:
            stats["ray"] += 1
            return colour(best[1], best[2])
        best = None
        for i in grid.box(sub(p, (2 * reach,) * 3), add(p, (2 * reach,) * 3)):
            cp, w = closest_on_triangle(p, *hp[i])
            dd = dot(sub(cp, p), sub(cp, p)) + (0.0 if dot(hn[i], n) > 0 else reach * reach)
            if best is None or dd < best[0]:
                best = (dd, i, w)
        if best:
            stats["near"] += 1
            return colour(best[1], best[2])
        stats["none"] += 1
        return None

    for cid, (label, members) in enumerate(charts):
        for ti in members:
            t = T[ti]
            p3 = [P[v] for v in t]
            n = unit(cross(sub(p3[1], p3[0]), sub(p3[2], p3[0])))
            q = [chart_uv(p, label, place[cid], s) for p in p3]
            x0, x1 = max(0, int(math.floor(min(a[0] for a in q) - 1))), min(aw - 1, int(math.ceil(max(a[0] for a in q) + 1)))
            y0, y1 = max(0, int(math.floor(min(a[1] for a in q) - 1))), min(ah - 1, int(math.ceil(max(a[1] for a in q) + 1)))
            den = (q[1][1] - q[2][1]) * (q[0][0] - q[2][0]) + (q[2][0] - q[1][0]) * (q[0][1] - q[2][1])
            if abs(den) < 1e-12:
                continue
            for y in range(y0, y1 + 1):
                for x in range(x0, x1 + 1):
                    if img[y * aw + x] is not None:
                        continue
                    px, py = x + 0.5, y + 0.5
                    a = ((q[1][1] - q[2][1]) * (px - q[2][0]) + (q[2][0] - q[1][0]) * (py - q[2][1])) / den
                    b = ((q[2][1] - q[0][1]) * (px - q[2][0]) + (q[0][0] - q[2][0]) * (py - q[2][1])) / den
                    c = 1 - a - b
                    # texels whose centre is within ~0.75 texel of the triangle (its edges' texels too)
                    m = 0.75 / max(1e-9, math.sqrt(abs(den)))
                    if a < -m or b < -m or c < -m:
                        continue
                    acc, got = [0.0, 0.0, 0.0], 0
                    for sx, sy in SUBSAMPLES:  # 2 x 2 samples a texel: the detailed textures are much finer
                        qx, qy = px + sx, py + sy
                        a = ((q[1][1] - q[2][1]) * (qx - q[2][0]) + (q[2][0] - q[1][0]) * (qy - q[2][1])) / den
                        b = ((q[2][1] - q[0][1]) * (qx - q[2][0]) + (q[0][0] - q[2][0]) * (qy - q[2][1])) / den
                        a, b = max(0.0, a), max(0.0, b)
                        c = max(0.0, 1 - a - b)
                        sm = a + b + c
                        a, b, c = a / sm, b / sm, c / sm
                        p = (p3[0][0] * a + p3[1][0] * b + p3[2][0] * c, p3[0][1] * a + p3[1][1] * b + p3[2][1] * c,
                             p3[0][2] * a + p3[1][2] * b + p3[2][2] * c)
                        col = surface_colour(p, n)
                        if col is not None:
                            acc[0] += col[0]; acc[1] += col[1]; acc[2] += col[2]
                            got += 1
                    if got:
                        img[y * aw + x] = [acc[0] / got, acc[1] / got, acc[2] / got]
    log("  baked: %d texels by ray, %d by nearest point, %d without a surface" % (stats["ray"], stats["near"], stats["none"]))
    filled = [c is not None for c in img]
    # grow the charts' borders over the empty texels (filtering at the edges)
    for _ in range(4):
        new = list(img)
        for y in range(ah):
            for x in range(aw):
                if img[y * aw + x] is not None:
                    continue
                acc, n = [0.0, 0.0, 0.0], 0
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    xx, yy = x + dx, y + dy
                    if 0 <= xx < aw and 0 <= yy < ah and img[yy * aw + xx] is not None:
                        c = img[yy * aw + xx]
                        acc[0] += c[0]; acc[1] += c[1]; acc[2] += c[2]
                        n += 1
                if n:
                    new[y * aw + x] = [acc[0] / n, acc[1] / n, acc[2] / n]
        img = new
    out = bytearray(aw * ah * 4)
    for i, c in enumerate(img):
        if c is None:
            c = (0, 0, 0)
        out[i * 4:i * 4 + 4] = bytes((min(255, max(0, int(c[0] + 0.5))), min(255, max(0, int(c[1] + 0.5))),
                                      min(255, max(0, int(c[2] + 0.5))), 255))
    return bytes(out), filled
