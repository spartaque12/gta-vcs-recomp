"""Triangle mesh simplification for tools/weapon_convert.py: quadric error metrics (Garland-Heckbert) with half-edge
collapses, so every kept vertex keeps its own position and texture coordinates. Standard library only.

    mesh = Mesh(positions, wedges, triangles)   # wedges: (position index, u, v, material); triangles: wedge triples
    mesh.simplify(target_triangles)
    positions, wedges, triangles = mesh.compact()

A position may carry several wedges (texture seams, material borders). A collapse moves position a onto position b
along an edge; every wedge of a must map onto a wedge of b through a triangle that holds the edge, so texture seams
and material borders survive (they slide only along themselves). Open borders slide only along themselves too;
non-manifold positions are never moved. Seam and border edges add perpendicular planes to the quadrics, so their
shape is kept. Collapses run in passes over the cheapest edges (as meshoptimizer does), with link-condition and
flip checks at the moment of the collapse. Faces are unweighted (a thin part costs as much to move as a big one) and
the edge length counts a little (no long jumps along creases). free_corners (tools/mesh_bake.py's meshes, only drawn):
corners may move, border positions may move inward, the link condition is off (holes close, surfaces pinch; triangles
left on top of each other are dropped) - messy game meshes stall otherwise."""
import math


def _plane_quadric(n, d, w):
    a, b, c = n
    return [w * a * a, w * a * b, w * a * c, w * a * d, w * b * b, w * b * c, w * b * d, w * c * c, w * c * d, w * d * d]


def _qadd(q, r):
    for i in range(10):
        q[i] += r[i]


def _qeval(q, p):
    x, y, z = p
    return (q[0] * x * x + 2 * q[1] * x * y + 2 * q[2] * x * z + 2 * q[3] * x + q[4] * y * y + 2 * q[5] * y * z
            + 2 * q[6] * y + q[7] * z * z + 2 * q[8] * z + q[9])


def _qsolve(q):
    """the point minimising the quadric, or None when its 3x3 part is (near) singular"""
    a, b, c, d, e, f, g, h, i = q[0], q[1], q[2], q[1], q[4], q[5], q[2], q[5], q[7]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    scale = max(abs(a), abs(e), abs(i)) ** 3
    if scale <= 0 or abs(det) < 1e-9 * scale:
        return None
    r = (-q[3], -q[6], -q[8])
    x = (r[0] * (e * i - f * h) - b * (r[1] * i - f * r[2]) + c * (r[1] * h - e * r[2])) / det
    y = (a * (r[1] * i - f * r[2]) - r[0] * (d * i - f * g) + c * (d * r[2] - r[1] * g)) / det
    z = (a * (e * r[2] - r[1] * h) - b * (d * r[2] - r[1] * g) + r[0] * (d * h - e * g)) / det
    return (x, y, z)


def _sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def _norm(a):
    n = math.sqrt(_dot(a, a))
    return (a[0] / n, a[1] / n, a[2] / n) if n > 0 else (0.0, 0.0, 0.0), n


class Mesh:
    def __init__(self, positions, wedges, triangles, border_weight=4.0, optimal=False, length_weight=0.05,
                 free_corners=False):
        """optimal: a collapse of two free positions puts the survivor where the summed quadric is least (full-edge
        collapse) - for meshes whose texture coordinates do not matter (tools/mesh_bake.py makes new ones)"""
        self.optimal = optimal
        self.length_weight = length_weight
        # free_corners: corners where borders / shared edges meet may move too (at ten times the cost; the planes of
        # their special edges keep the shape) - messy game meshes (open sheets, parts welded at points) stall otherwise
        self.free_corners = free_corners
        self.fails = {}
        self.P = [tuple(p) for p in positions]
        self.wpos = [w[0] for w in wedges]
        self.wattr = [tuple(w[1:]) for w in wedges]
        self.T = [list(t) for t in triangles if len({wedges[t[0]][0], wedges[t[1]][0], wedges[t[2]][0]}) == 3]
        self.alive = [True] * len(self.T)
        self.vt = [set() for _ in self.P]
        for i, t in enumerate(self.T):
            for w in t:
                self.vt[self.wpos[w]].add(i)
        self.dead = [False] * len(self.P)
        self.count = len(self.T)
        self.border_weight = border_weight
        self.Q = [[0.0] * 10 for _ in self.P]
        for t in self.T:
            p = [self.P[self.wpos[w]] for w in t]
            n, l2 = _norm(_cross(_sub(p[1], p[0]), _sub(p[2], p[0])))
            if l2 <= 0:
                continue
            q = _plane_quadric(n, -_dot(n, p[0]), 1.0)  # unweighted: thin parts cost as much to move as big ones
            for w in t:
                _qadd(self.Q[self.wpos[w]], q)
        # seams and borders: planes through the edge, perpendicular to its face
        edges = self._edges()
        for (a, b), ts in edges.items():
            if len(ts) == 2 and not self._seam(a, b, ts):
                continue
            for ti in ts:
                t = self.T[ti]
                p = [self.P[self.wpos[w]] for w in t]
                fn, l2 = _norm(_cross(_sub(p[1], p[0]), _sub(p[2], p[0])))
                if l2 <= 0:
                    continue
                e = _sub(self.P[b], self.P[a])
                cn, el = _norm(_cross(e, fn))
                if el <= 0:
                    continue
                q = _plane_quadric(cn, -_dot(cn, self.P[a]), self.border_weight)
                _qadd(self.Q[a], q)
                _qadd(self.Q[b], q)

    def _pos(self, ti):
        return [self.wpos[w] for w in self.T[ti]]

    def _edges(self):
        edges = {}
        for ti, t in enumerate(self.T):
            if not self.alive[ti]:
                continue
            p = [self.wpos[w] for w in t]
            for k in range(3):
                a, b = p[k], p[(k + 1) % 3]
                key = (a, b) if a < b else (b, a)
                edges.setdefault(key, []).append(ti)
        return edges

    def _wedge_at(self, ti, pid):
        for w in self.T[ti]:
            if self.wpos[w] == pid:
                return w
        return None

    def _seam(self, a, b, ts):
        """an edge whose two triangles disagree on the wedges (texture coordinates / material) at its ends"""
        return (self._wedge_at(ts[0], a) != self._wedge_at(ts[1], a) or
                self._wedge_at(ts[0], b) != self._wedge_at(ts[1], b))

    def _edge_kind(self, a, b, ts):
        """0 an ordinary edge, 1 an open border, 2 a texture seam / material border, 3 shared by more than two faces"""
        if len(ts) == 1:
            return 1
        if len(ts) == 2:
            return 2 if self._seam(a, b, ts) else 0
        return 3

    def _classify(self, edges):
        """per position: 0 free, 1 / 2 / 3 slides along the two special edges of that kind it sits on, -1 fixed
        (corners where special edges meet otherwise)"""
        n = len(self.P)
        special = [[] for _ in range(n)]
        for (a, b), ts in edges.items():
            k = self._edge_kind(a, b, ts)
            if k:
                special[a].append(k)
                special[b].append(k)
        kind = [-1] * n
        for v in range(n):
            if self.dead[v]:
                continue
            s = special[v]
            wedges = len({self._wedge_at(ti, v) for ti in self.vt[v]})
            if not s:
                kind[v] = 0 if wedges == 1 else -1
            elif len(s) == 2 and s[0] == s[1] and wedges == (2 if s[0] == 2 else 1):
                kind[v] = s[0]
        return kind

    def _on_border(self, v):
        """an open edge at v (one of its edges has a single triangle)"""
        count = {}
        for ti in self.vt[v]:
            for x in self._pos(ti):
                if x != v:
                    count[x] = count.get(x, 0) + 1
        return any(n == 1 for n in count.values())

    def _ring(self, v):
        r = set()
        for ti in self.vt[v]:
            r.update(self._pos(ti))
        r.discard(v)
        return r

    def _try_collapse(self, a, b, max_cos=0.5, place=None):
        """move position a onto b (and b to `place` when given); False when the collapse would break topology,
        texture seams or flip a face"""
        shared = [ti for ti in self.vt[a] if ti in self.vt[b]]
        if not shared:
            return False
        mapping = {}
        for ti in shared:
            wa, wb = self._wedge_at(ti, a), self._wedge_at(ti, b)
            if mapping.setdefault(wa, wb) != wb:
                return False
        moved = [ti for ti in self.vt[a] if ti not in self.vt[b]]
        for ti in moved:
            if self._wedge_at(ti, a) not in mapping:
                return False
        # link condition: the common neighbours are exactly the shared triangles' third corners
        third = set()
        for ti in shared:
            third.update(self._pos(ti))
        third.discard(a); third.discard(b)
        if not self.free_corners:  # free_corners (meshes only drawn, unculled): holes may close, surfaces pinch
            if (self._ring(a) & self._ring(b)) != third:
                self.fails["link"] = self.fails.get("link", 0) + 1
                return False
            if len(shared) == 2 and self._on_border(a) and self._on_border(b):
                self.fails["pinch"] = self.fails.get("pinch", 0) + 1
                return False  # an inner edge between two border positions: the collapse would pinch the surface
        pb = place or self.P[b]
        check = moved + ([ti for ti in self.vt[b] if ti not in shared] if place else [])
        for ti in check:
            p = [self.P[x] for x in self._pos(ti)]
            n0 = _cross(_sub(p[1], p[0]), _sub(p[2], p[0]))
            q = [pb if x == a or x == b else self.P[x] for x in self._pos(ti)]
            n1 = _cross(_sub(q[1], q[0]), _sub(q[2], q[0]))
            l0, l1 = math.sqrt(_dot(n0, n0)), math.sqrt(_dot(n1, n1))
            if l1 <= 1e-14 or _dot(n0, n1) < max_cos * l0 * l1:
                self.fails["flip"] = self.fails.get("flip", 0) + 1
                return False
            # no new slivers (needles stick out of the silhouette): area against the squared edges, 1 = equilateral
            e2 = sum(_dot(_sub(q[k], q[(k + 1) % 3]), _sub(q[k], q[(k + 1) % 3])) for k in range(3))
            if 3.4641 * l1 / e2 < min(0.01, 3.4641 * l0 / max(1e-30, sum(
                    _dot(_sub(p[k], p[(k + 1) % 3]), _sub(p[k], p[(k + 1) % 3])) for k in range(3)))):
                self.fails["sliver"] = self.fails.get("sliver", 0) + 1
                return False
        if place:
            self.P[b] = place
        for ti in shared:
            self.alive[ti] = False
            for x in self._pos(ti):
                self.vt[x].discard(ti)
            self.count -= 1
        for ti in moved:
            t = self.T[ti]
            for k in range(3):
                if self.wpos[t[k]] == a:
                    t[k] = mapping[t[k]]
            self.vt[b].add(ti)
        self.vt[a] = set()
        self.dead[a] = True
        _qadd(self.Q[b], self.Q[a])
        if self.free_corners:  # a closed hole leaves triangles over each other: one of each set stays
            seen = set()
            for ti in sorted(self.vt[b]):
                key = frozenset(self._pos(ti))
                if len(key) < 3 or key in seen:
                    self.alive[ti] = False
                    for x in self._pos(ti):
                        self.vt[x].discard(ti)
                    self.count -= 1
                else:
                    seen.add(key)
        return True

    def simplify(self, target, max_passes=100, log=None):
        for npass in range(max_passes):
            if self.count <= target:
                break
            edges = self._edges()
            kind = self._classify(edges)
            cand = []
            for (a, b), ts in edges.items():
                best = None
                ek = None
                for x, y in ((a, b), (b, a)):
                    if kind[x] < 0 and not self.free_corners:
                        continue
                    if kind[x] > 0:
                        if ek is None:
                            ek = self._edge_kind(a, b, ts)
                        # a border / seam / shared-edge position slides along its own kind only (free_corners: a
                        # border position may also move inward, onto a position off every border)
                        if ek != kind[x] and not (self.free_corners and kind[x] == 1 and kind[y] == 0):
                            continue
                    if self.optimal:  # the error of both ends' planes at the new place
                        c = _qeval([self.Q[a][i] + self.Q[b][i] for i in range(10)], self.P[y])
                    else:
                        c = _qeval(self.Q[x], self.P[y])
                    # short edges first where the planes do not mind (a flat or creased stretch): no long jumps along
                    # a crease or across a flat face, which leave spikes and fans over holes
                    d = _sub(self.P[x], self.P[y])
                    c += self.length_weight * _dot(d, d)
                    if kind[x] < 0:
                        c = c * 10 + 1e-9
                    if best is None or c < best[0]:
                        best = (c, x, y, None)
                if best and self.optimal and kind[a] == 0 and kind[b] == 0:
                    q = [self.Q[a][i] + self.Q[b][i] for i in range(10)]
                    v = _qsolve(q)
                    span = max(abs(self.P[a][k] - self.P[b][k]) for k in range(3))
                    if v is not None and max(abs(v[k] - (self.P[a][k] + self.P[b][k]) / 2) for k in range(3)) < 2 * span:
                        c = _qeval(q, v)
                        if c < best[0]:
                            best = (c, best[1], best[2], v)
                if best:
                    cand.append(best)
            if not cand:
                break
            cand.sort(key=lambda e: e[0])
            # this pass: the cheapest collapses, each position touched once
            want = (self.count - target + 1) // 2
            limit = max(1, min(want, len(cand) // 3))
            touched = set()
            done = 0
            for c, x, y, v in cand:
                if done >= limit:
                    break
                if x in touched or y in touched or self.dead[x] or self.dead[y]:
                    continue
                if self._try_collapse(x, y, place=v):
                    touched.add(x); touched.add(y)
                    touched.update(self._ring(y))
                    done += 1
            if log:
                log("  pass %d: %d collapses, %d triangles" % (npass, done, self.count))
            if not done:
                break
        return self.count

    def compact(self):
        """-> (positions, wedges [(position, attr...)], triangles) of what is left, renumbered"""
        wmap, pmap = {}, {}
        P, W, T = [], [], []
        for ti, t in enumerate(self.T):
            if not self.alive[ti]:
                continue
            nt = []
            for w in t:
                if w not in wmap:
                    p = self.wpos[w]
                    if p not in pmap:
                        pmap[p] = len(P)
                        P.append(self.P[p])
                    wmap[w] = len(W)
                    W.append((pmap[p],) + self.wattr[w])
                nt.append(wmap[w])
            T.append(nt)
        return P, W, T
