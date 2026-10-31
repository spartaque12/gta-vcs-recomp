"""GTA VC / SA vegetation (DFF + TXD: the 80's VC True Vegetation pack or BSOR Vegetation) -> VCS PS2 map object models ('ldm' Rsl chunk, prelit) + their texture dictionaries
('xet' chunk), written as streamed-file overrides (src/game/vcs_stream_override.h: <mods>/stream/<id>.ldm / .xet).

    python tools/veg_convert.py --pack "<...>/modloader/BSOR_Vegetation" (SA)  or  "<...>/80's vc True vegetation.zip" (VC)
                                [--only veg_palm01,veg_tree3]
                                [--tris 600] [--tex 256] [--mods build/mods] [--iso ISO] [--hd [--hd-dump DIR]]
    python tools/veg_convert.py --remove [--mods DIR]          the overrides this tool wrote, deleted again

VCS keeps VC's model names for its vegetation (game-internals.md 12i): each VC palm and leaf tree of the pack replaces the VCS model
of the same name and that model's own texture dictionary (no other model uses them). VCS's palms are VC's designs drawn
taller, so each pack model is scaled to the VCS model's height (its footprint then matches too) and its trunk's foot
put where the VCS model's stands (trunk_foot). Map objects are prelit:
per material a mesh whose DMA packet (RET) holds batches of <= 70 strip vertices - V3-16 positions at 1, V2-8 uv at
0x48, V4-5 colours (RGBA 5551) at 0x8F, MSCAL 6, geometry flags 0xD - as the game's own palms. The colour is the VCS
palms' own grey (0xAD6B) times the pack's material colour. The pack's palms are 4.9k - 10.5k triangles, and every 68
strip vertices are a VU1 batch - a draw. Their leaves are double-sided cards (each face twice, reversed, for PC's
culling); VCS draws both sides of a triangle, so one face of each pair is kept. The cards themselves stay as made:
simplified (tools/mesh_simplify.py) or thinned they turned to confetti in the game. Only the opaque parts - trunks,
stems - are simplified, to --tris - and drawn first; materials with fully transparent textures are left out. Their
textures become 4-bit as most of the game's own (8-bit below 32 x 16; raster), 32 - 256 px by how much of the model
each covers, cut-out ones at least 128: colour averaged by alpha, alpha scaled to keep the full-size share of solid texels (foliage_downscale),
then made 0 or 255 (binary_alpha: the game writes depth for every texel past alpha 8 of 128). Nothing of the game is
written into this repository: the user converts their copy of the pack against their disc.
--hd adds the pack's full-size textures as a texture pack (docs/TEXTURE_PACKS.md, as the HD HUD): a hidden run with
VCS_TEXTURE_DUMP gives each converted texture its PCSX2 name, and the full-size image is written under it; those names
also go into <mods>/wind.txt, the textures Graphics > Vegetation wind sways (game/vcs_wind.h, wind_quantizer)."""
import argparse, math, os, shutil, struct, sys, tempfile, time, zipfile, zlib
from collections import Counter, defaultdict
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rw_dff as rwdff, rw_txd as rwtxd, mesh_simplify
import toolchain as tc
import weapon_convert as wc

# VCS's vegetation models (read in the game, 2026-10-31; docs/game-internals.md 12i): name -> (model id, its position
# and size in GTA3PS2.IMG sectors, texture dictionary id, its position and size). Ids are CStreaming ids; each
# dictionary belongs to its model alone. veg_palwee03 and the veg_palmkb set are names without data in VCS.
PALMS = {
    "veg_palm01": (578, 0x3152, 2, 7919, 0x314c, 6),
    "veg_palm02": (546, 0x312c, 1, 7914, 0x3126, 6),
    "veg_palm03": (547, 0x3133, 1, 7915, 0x312d, 6),
    "veg_palm04": (545, 0x3122, 4, 7913, 0x311b, 7),
    "veg_palmbig14": (574, 0x3149, 3, 7918, 0x3142, 7),
    "veg_palwee01": (548, 0x313a, 1, 7916, 0x3134, 6),
    "veg_palwee02": (549, 0x3141, 1, 7917, 0x313b, 6),
}
TREES = {
    "veg_tree3": (540, 0x3101, 2, 7909, 0x30fb, 6),
    "veg_treea1": (541, 0x3109, 2, 7910, 0x3103, 6),
    "veg_treea3": (543, 0x3119, 2, 7912, 0x3113, 6),
    "veg_treeb1": (542, 0x3111, 2, 7911, 0x310b, 6),
}
VCS_GREY = 0xAD6B  # the game's palms' vertex colour: 88, 88, 88 (128 = 1.0), opaque
PACK_DIR = "80's vc True vegetation/original game Installation/"  # the pack's VC 1.0 install (not Vice Cry's)


def batch_packet_prelit(verts):
    """VIF data of one batch as VCS's map objects: header, positions, uv, RGBA 5551 colours, MSCAL 6"""
    n = len(verts)
    out = bytearray()
    out += struct.pack("<I4I", 0x6C018000, 0, 0, n, n | 0x8000)
    out += struct.pack("<II", 0x20000000, 0x40404040)
    out += struct.pack("<I4I", 0x30000000, 0, 0, 0, 0)
    out += struct.pack("<I", 0x79008001 | n << 16)
    pos = b"".join(struct.pack("<3h", *v[0]) for v in verts)
    out += pos + bytes(-len(pos) & 3)
    out += struct.pack("<II", 0x20000000, 0x50505050)
    out += struct.pack("<I4I", 0x30000000, 0, 0, 0xFF, 0)
    out += struct.pack("<I", 0x7600C048 | n << 16)
    uv = b"".join(struct.pack("<2B", *v[1]) for v in verts)
    out += uv + bytes(-len(uv) & 3)
    out += struct.pack("<I", 0x6F00808F | n << 16)
    col = b"".join(struct.pack("<H", v[2]) for v in verts)
    out += col + bytes(-len(col) & 3)
    out += struct.pack("<I", 0x14000006)
    return out


def tinted(colour):
    """VCS's grey times a material colour (r, g, b, a 0..255), as RGBA 5551"""
    c5 = [max(0, min(31, round((VCS_GREY >> (5 * i) & 31) * colour[i] / 255))) for i in range(3)]
    return c5[0] | c5[1] << 5 | c5[2] << 10 | 0x8000


def cut_out(texture):
    """a texture whose alpha cuts shapes out (leaves): more than 5% of its texels not opaque"""
    if not texture:
        return False
    w, h, rgba = texture
    return sum(1 for a in rgba[3::4] if a < 250) > 0.05 * w * h


def bleed(w, h, rgba, passes=6):
    """Transparent texels take the colour of their solid neighbours (textures wrap): the GS filters colour and alpha
    apart, so the light colour such texels often hold (white in the pack) fringed the leaves' edges, a pale veil"""
    px = bytearray(rgba)
    solid = [px[i * 4 + 3] >= 128 for i in range(w * h)]
    if all(solid) or not any(solid):
        return bytes(px)
    for _ in range(passes):
        grown = []
        for y in range(h):
            for x in range(w):
                i = y * w + x
                if solid[i]:
                    continue
                r = g = b = n = 0
                for dy in (-1, 0, 1):
                    row = ((y + dy) % h) * w
                    for dx in (-1, 0, 1):
                        j = row + (x + dx) % w
                        if solid[j]:
                            r += px[j * 4]; g += px[j * 4 + 1]; b += px[j * 4 + 2]; n += 1
                if n:
                    grown.append((i, r // n, g // n, b // n))
        if not grown:
            break
        for i, r, g, b in grown:
            px[i * 4:i * 4 + 3] = bytes((r, g, b))
            solid[i] = True
    rest = [i for i in range(w * h) if not solid[i]]
    if rest:  # far from any leaf: the texture's average solid colour
        sel = [i for i in range(w * h) if solid[i]]
        avg = bytes(sum(px[i * 4 + c] for i in sel) // len(sel) for c in range(3))
        for i in rest:
            px[i * 4:i * 4 + 3] = avg
    return bytes(px)


def foliage_downscale(w, h, rgba, size):
    """A box filter to at most size x size for cut-out textures: colour averaged by alpha (transparent texels' colour,
    often black, never darkens the leaves' edges) and alpha scaled up until as many texels are at least half opaque as
    at full size - averaged, thin leaflets turn half transparent and the fronds a grey veil. -> (w, h, rgba, gain)"""
    w2, h2 = w, h
    while max(w2, h2) > size:
        w2, h2 = max(1, w2 // 2), max(1, h2 // 2)
    if (w2, h2) == (w, h):
        return w, h, rgba, 1.0
    fx, fy = w // w2, h // h2
    n = fx * fy
    out = bytearray(w2 * h2 * 4)
    for y in range(h2):
        for x in range(w2):
            sa = sr = sg = sb = pr = pg = pb = 0
            for j in range(fy):
                o = ((y * fy + j) * w + x * fx) * 4
                for i in range(fx):
                    r, g, b, a = rgba[o:o + 4]
                    sa += a; sr += r * a; sg += g * a; sb += b * a; pr += r; pg += g; pb += b
                    o += 4
            o = (y * w2 + x) * 4
            out[o:o + 4] = bytes((sr // sa, sg // sa, sb // sa, sa // n) if sa else (pr // n, pg // n, pb // n, 0))
    want = sum(1 for a in rgba[3::4] if a >= 128) / (w * h)
    alphas = out[3::4]
    covered = lambda k: sum(1 for a in alphas if a * k >= 128) / len(alphas)
    gain = 1.0
    if covered(1.0) < want:
        lo, hi = 1.0, 8.0
        for _ in range(16):
            mid = (lo + hi) / 2
            lo, hi = (lo, mid) if covered(mid) >= want else (mid, hi)
        gain = hi
        for o in range(3, len(out), 4):
            out[o] = min(255, round(out[o] * gain))
    return w2, h2, bytes(out), gain


def binary_alpha(rgba):
    """Alpha made 0 or 255 (at 128). The game alpha-tests world draws GREATER 8 (of 128) and writes depth wherever a
    texel passes: half-transparent texels let the sky through and hid the parts of the tree drawn after them - pale
    patches where downscaled fibres and leaflets had blurred half transparent. The GS's bilinear filter rounds the edges"""
    px = bytearray(rgba)
    for o in range(3, len(px), 4):
        px[o] = 255 if px[o] >= 128 else 0
    return bytes(px)


def raster(w, h, rgba):
    """4-bit (T4: a CLUT of 16, linear, low nibble first, 0x0045 | w / 2) as two thirds of the game's own textures - half
    T8's streaming memory, of which the converted palms take several times the game's own - for the sizes the game
    itself has in 4-bit (32 x 16 up); 8-bit below. Cut-out textures (alpha 0 or 255: binary_alpha) keep 15 colours for
    their solid texels and one entry for the transparent ones, the solid texels' average colour (filtered edges mix it in)"""
    if w < 32 or h < 16:
        return wc.t8_raster(w, h, rgba)
    n = w * h
    alphas = rgba[3::4]
    if 0 in alphas and all(a in (0, 255) for a in alphas):
        solid = [i for i in range(n) if alphas[i]]
        pal, sub = wc.quantize(b"".join(rgba[i * 4:i * 4 + 4] for i in solid), 15)
        pal = pal[:15] + [tuple(sum(rgba[i * 4 + c] for i in solid) // len(solid) for c in range(3)) + (0,)]
        idx = bytearray([15]) * n
        for j, i in enumerate(solid):
            idx[i] = sub[j]
    else:
        pal, idx = wc.quantize(rgba, 16)
    clut = b"".join(bytes((r, g, b, (a * 128 + 127) // 255)) for r, g, b, a in pal[:16])
    pixels = bytes(idx[i] | idx[i + 1] << 4 for i in range(0, n, 2))
    flags = int(math.log2(w)) | int(math.log2(h)) << 6 | 4 << 12 | 1 << 20
    return {"w4": 0x00450000 | w // 2, "flags": flags, "data": pixels + clut}


def load_tris(dff):
    """the model's triangles in its root frame: [(texture, (p0, p1, p2), (uv0, uv1, uv2), material colour)]"""
    frames, geoms, atomics = rwdff.parse_dff(dff)
    out = []
    for at in atomics:
        g = geoms[at["geometry"]]
        m = rwdff.ltm(frames, at["frame"])
        for (v0, v1, v2, mi) in g.tris:
            if v0 == v1 or v1 == v2 or v0 == v2:
                continue
            mat = g.materials[mi]
            ps, uvs = [], []
            for v in (v0, v1, v2):
                p = g.pos[v]
                ps.append(tuple(p[0] * m[0][c] + p[1] * m[1][c] + p[2] * m[2][c] + m[3][c] for c in range(3)))
                uvs.append(tuple(g.uv[v]) if g.uv else (0.0, 0.0))
            out.append(((mat["texture"] or "none").lower(), tuple(ps), tuple(uvs), mat["color"]))
    return out


def decoded(w, h, r):
    """the texture as the GS samples it (RGBA, alpha 128 = opaque): what VCS_TEXTURE_DUMP writes for it"""
    four = r["flags"] >> 12 & 0x3F == 4
    pix = r["data"][:w * h // 2] if four else r["data"][:w * h]
    clut = r["data"][len(pix):]
    out = bytearray(w * h * 4)
    for i in range(w * h):
        k = (pix[i >> 1] >> (4 * (i & 1)) & 15) if four else wc.csm1(pix[i])
        out[i * 4:i * 4 + 4] = clut[k * 4:k * 4 + 4]
    return bytes(out)


def read_png(path):
    """(w, h, RGBA) of an 8-bit RGBA PNG (the renderer's dumps: unfiltered rows)"""
    d = open(path, "rb").read()
    p, idat, w = 8, b"", 0
    while p < len(d):
        n, kind = struct.unpack_from(">I4s", d, p)
        if kind == b"IHDR":
            w, h, depth, colour = struct.unpack_from(">IIBB", d, p + 8)
            if (depth, colour) != (8, 6):
                return None
        elif kind == b"IDAT":
            idat += d[p + 8:p + 8 + n]
        p += 12 + n
    raw = zlib.decompress(idat)
    stride = w * 4 + 1
    if any(raw[y * stride] for y in range(h)):
        return None
    return w, h, b"".join(raw[y * stride + 1:(y + 1) * stride] for y in range(h))


def write_png(path, w, h, rgba):
    rows = b"".join(b"\0" + rgba[y * w * 4:(y + 1) * w * 4] for y in range(h))
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)) +
                chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b""))


# Where each placed model stands (CWorld's sectors in a RAM dump, 2026-10-31): the HD capture looks around there.
# veg_treea3 and veg_treeb1 are placed nowhere on the map.
HD_SPOTS = {
    "veg_tree3": (10, -229, 14), "veg_treea1": (222, 137, 8), "veg_palm04": (-1829, -303, 12),
    "veg_palm02": (-1299, -434, 10), "veg_palm03": (-1014, -526, 10), "veg_palwee01": (-1112, -459, 10),
    "veg_palwee02": (-1303, -437, 9), "veg_palmbig14": (-1155, -363, 10), "veg_palm01": (-1463, -298, 14),
}


def hd_capture(models, mods, dump, port, save):
    """A hidden run with VCS_TEXTURE_DUMP: the camera turned around at each model's spot"""
    import rig
    env = {"VCS_MODS_DIR": os.path.abspath(mods), "VCS_TEXTURE_DUMP": os.path.abspath(dump)}
    g = rig.Game.start(save=save, name="veg_hd", env=env, port=port)
    try:
        g.wait_ingame()
        g.invincible()
        g.set_time(13)
        for name in models:
            if name not in HD_SPOTS:
                continue
            x, y, z = HD_SPOTS[name]
            print("  looking around %s at (%d, %d, %d)" % (name, x, y, z))
            g.teleport(x + 15, y, z + 2)  # the free camera stays where it was turned on: off while moving
            time.sleep(4.0)
            g.cmd("trainer toggle freecam 1")
            time.sleep(1.0)
            for _ in range(8):
                g.cmd("mouse 200 0")
                time.sleep(1.0)
            g.cmd("trainer toggle freecam 0")
    finally:
        g.quit()


def hd_textures(hd, dump, out, wind=None, log=print):
    """Each converted texture found among the dumped ones (same size, same texels) gets the pack's full-size image
    under the dump's name: the renderer's texture replacements (docs/TEXTURE_PACKS.md) draw it in its place. wind: the
    wind list to write (the names of the textures of models in the wind convention)"""
    dumps = defaultdict(list)
    for f in sorted(os.listdir(dump)):
        if f.endswith(".png"):
            img = read_png(os.path.join(dump, f))
            if img:
                dumps[img[:2]].append((f, img[2]))
    os.makedirs(out, exist_ok=True)
    done, written, sway = 0, set(), set()
    for tex, w, h, want, (sw, sh, src), sways in hd:
        name = next((f for f, px in dumps.get((w, h), ()) if px == want), None)
        if not name:
            log("  %-26s %dx%d: not seen in the capture" % (tex, w, h))
            continue
        if sways:
            sway.add(name[:-4])
        if name in written:  # the same texture in another model's dictionary
            continue
        written.add(name)
        rgba = bleed(sw, sh, src) if cut_out((sw, sh, src)) else src
        rgba = bytes(v if i & 3 != 3 else (v * 128 + 127) // 255 for i, v in enumerate(rgba))  # GS alpha
        write_png(os.path.join(out, name), sw, sh, rgba)
        done += 1
        log("  %-26s %dx%d -> %dx%d  %s" % (tex, w, h, sw, sh, name))
    if wind:
        with open(wind, "w") as f:
            f.write("# vegetation wind sway (tools/veg_convert.py --hd; game/vcs_wind.h): name, metres per unit x y z, "
                    "0, reach\n")
            f.writelines(wind_line(n) for n in sorted(sway))
        log("wind list: %d textures -> %s" % (len(sway), wind))
    return done


def vcs_verts(vd):
    """The VCS model's vertex positions: every V3-16 UNPACK to address 1 (positions) in its batches, through the
    geometry header's scale and offset (wc.vcs_box)"""
    el = wc.u32(vd, 0x20)
    g = wc.u32(vd, el + 0x14) + 0x20
    sc = struct.unpack_from("<3f", vd, g + 0x28)
    po = struct.unpack_from("<3f", vd, g + 0x34)
    out = []
    for o in range(0, len(vd) - 4, 4):
        w = wc.u32(vd, o)
        n = w >> 16 & 0xFF
        if w >> 24 == 0x79 and w & 0xFFFF == 0x8001 and 1 <= n <= 80 and o + 4 + 6 * n <= len(vd):
            out += [tuple(po[k] + sc[k] * v[k] / 32768 for k in range(3))
                    for v in struct.iter_unpack("<3h", vd[o + 4:o + 4 + 6 * n])]
    return out


def trunk_foot(ps, band=0.5):
    """(x, y, z) of a tree's foot: the lowest point's z, x / y the middle of what lies within `band` of it (the trunk's
    bottom ring in every model of the pack and of VCS)"""
    z = min(p[2] for p in ps)
    low = [p for p in ps if p[2] <= z + band]
    return ((min(p[0] for p in low) + max(p[0] for p in low)) / 2, (min(p[1] for p in low) + max(p[1] for p in low)) / 2, z)


# Wind sway (game/vcs_wind.h, gs_draw.hlsl vs_world): only the leaves (cut-out textures) sway, by their distance from
# the crown - the top of the trunk, where they meet the bark -, so the bark stays still and the leaves stay on it. The
# converted models' positions are in one convention - 2 mm per unit on every axis, the crown at 0 -, so a texture
# several models share sways the same in each and the wind list (mods/wind.txt) needs no per-model numbers. 64 m of
# room around the crown: larger models keep the usual quantizer, still.
WIND_SCALE = 64.0       # metres for 32768 units
WIND_REACH = 6.0        # metres from the crown where the sway is full (the square of the distance up to it, then linear)


def crown(P, W, T, cut):
    """the top of the trunk: the middle of the opaque parts' highest metre (the box's top middle without them)"""
    bark = [P[W[w][0]] for t in T if W[t[0]][3] not in cut for w in t] or P
    z = max(p[2] for p in bark)
    top = [p for p in bark if p[2] >= z - 1.0]
    return ((min(p[0] for p in top) + max(p[0] for p in top)) / 2, (min(p[1] for p in top) + max(p[1] for p in top)) / 2, z)


def wind_quantizer(centre):
    """weapon_convert.quantizer in the wind convention around `centre` (the crown): a function of the points giving
    (centre, scale, q), or None when they do not fit"""
    def quantizer(allp):
        if any(abs(p[i] - centre[i]) > WIND_SCALE * 0.999 for p in allp for i in range(3)):
            return None
        scale = [WIND_SCALE] * 3
        def q(p):
            return tuple(max(-32768, min(32767, round((p[i] - centre[i]) / scale[i] * 32768))) for i in range(3))
        return list(centre), scale, q
    return quantizer


def wind_line(name):
    """a wind list line (render/texture_replacements.h): metres per unit x y z, 0 (unused), the reach (units)"""
    k = WIND_SCALE / 32768
    return "%s %.9g %.9g %.9g 0 %d\n" % (name, k, k, k, round(WIND_REACH / k))


def convert(name, dff, textures, vd, model_id, out_mdl, out_xet, tris=600, tex_max=256, log=print, hd=None):
    raw = load_tris(dff)
    hidden = {tex for tex, _, _, _ in raw if textures.get(tex) and not any(textures[tex][2][3::4])}
    if hidden:  # fully transparent textures: alpha-tested away on PC too
        log("  %d triangles of %s (fully transparent, never seen) left out" % (
            sum(1 for t in raw if t[0] in hidden), ", ".join(sorted(hidden))))
        raw = [t for t in raw if t[0] not in hidden]
    tint = {}
    for tex, _, _, col in raw:
        tint.setdefault(tex, tinted(col))
    allp = [p for _, ps, _, _ in raw for p in ps]
    lo = [min(p[i] for p in allp) for i in range(3)]
    hi = [max(p[i] for p in allp) for i in range(3)]
    vlo, vhi = wc.vcs_box(vd)
    # Scaled to the VCS model's full height and stood where its trunk stands: the models' origins are not at the trunk's
    # foot (VCS's sit 0.8 m below to 0.1 m above it, the pack's 0.7 m below to at it - game-internals.md 12j); scaled
    # about the origin alone, veg_palmbig14 stood 0.8 m above its lawn and veg_palm02 1 m into it
    s = (vhi[2] - vlo[2]) / (hi[2] - lo[2]) if hi[2] > lo[2] else 1.0
    vb, pb = trunk_foot(vcs_verts(vd)), trunk_foot(allp, 0.5 / s)
    off = (vb[0] - pb[0] * s, vb[1] - pb[1] * s, vb[2] - pb[2] * s)
    log("  %d tris, height %.1f m -> %.1f m (VCS's): scale %.2f; trunk foot (%.2f %.2f %.2f) -> VCS's (%.2f %.2f %.2f)" % (
        len(raw), hi[2] - lo[2], vhi[2] - vlo[2], s, pb[0] * s, pb[1] * s, pb[2] * s, *vb))
    parts = [(tex, tuple(tuple(p[c] * s + off[c] for c in range(3)) for p in ps), uvs) for tex, ps, uvs, _ in raw]
    P, W, T = wc.weld(parts)
    # The fronds are double-sided cards (each face twice, reversed: PC culls back faces); VCS's prelit pipeline draws
    # both sides of a triangle, so one of each pair is enough
    seen, single = set(), []
    for t in T:
        key = (frozenset(W[w][0] for w in t), W[t[0]][3])
        if key not in seen:
            seen.add(key)
            single.append(t)
    log("  %d triangles, %d of them the back of a double-sided face: left out" % (len(T), len(T) - len(single)))
    T = single
    # Only the opaque parts (trunks, stems) are simplified, to about `tris`: the leaf cards each map their own patch of
    # the texture, and collapses inside them smear it into confetti, so they stay as made
    cut = {tex for tex in {W[t[0]][3] for t in T} if cut_out(textures.get(tex))}
    leaves = [t for t in T if W[t[0]][3] in cut]
    solid = [t for t in T if W[t[0]][3] not in cut]
    if tris and len(solid) > tris:
        m = mesh_simplify.Mesh(P, W, solid)
        m.simplify(tris)
        P2, W2, T2 = m.compact()
        if {W2[t[0]][3] for t in T2} == {W[t[0]][3] for t in solid}:
            base = len(P2)
            P = P2 + P  # the leaves keep their own wedges, after the simplified ones
            W = W2 + [(p + base, u, v, tex) for p, u, v, tex in W]
            T = T2 + [[w + len(W2) for w in t] for t in leaves]
            log("  opaque parts %d -> %d triangles; %d leaf triangles as made" % (len(solid), len(T2), len(leaves)))
        else:
            log("  opaque parts left as made: simplified, a material would vanish")
    top = crown(P, W, T, cut)
    wind = wind_quantizer(top) if wind_quantizer(top)(P) else None
    _, _, q = (wind or wc.quantizer)(P)
    if wind:
        log("  crown (wind sway around it) at (%.2f %.2f %.2f)" % top)
    else:
        log("  reaches further than %.0f m from its crown: no wind sway" % WIND_SCALE)
    bytex = defaultdict(list)
    area = Counter()
    for i, t in enumerate(T):
        tex = W[t[0]][3]
        bytex[tex].append(i)
        area[tex] += wc.tri_area(*(P[W[w][0]] for w in t))
    groups, total_tris = [], 0
    # opaque materials first: drawn after the leaves, a trunk was hidden behind their texels' depth wherever those let
    # anything through (filtered edges)
    for tex in sorted(bytex, key=lambda t: (t in cut, t)):
        ids = bytex[tex]
        prm = wc.uv_params([(W[w][1], W[w][2]) for i in ids for w in T[i]])
        weldv, rep, tl = {}, [], []
        for i in ids:
            t = []
            for w in T[i]:
                p, uv = P[W[w][0]], (W[w][1], W[w][2])
                key = (q(p), wc.uv8(uv, prm))
                if key not in weldv:
                    weldv[key] = len(rep)
                    rep.append((p, uv, tint[tex]))
                t.append(weldv[key])
            if len(set(t)) == 3:
                tl.append(tuple(t))
        seq_idx, nstrips = wc.stripify(tl)
        groups.append((tex[:31], [rep[i] for i in seq_idx], prm))
        total_tris += len(tl)
        log("  %-26s %5d tris -> %4d strips, %5d strip verts%s" % (
            tex, len(tl), nstrips, len(seq_idx), "  (uv repeats)" if prm[0] or prm[1] else ""))
    el = wc.u32(vd, 0x20); geo = wc.u32(vd, el + 0x14); mat0 = wc.u32(vd, wc.u32(vd, geo + 0x0C))
    usual = wc.quantizer
    if wind:  # build_mdl quantizes through its module's quantizer
        wc.quantizer = wind
    try:
        mdl, total, _ = wc.build_mdl(groups, model_id, wc.u32(vd, mat0 + 4), wc.u32(vd, geo + 0x20 + 0x40 + 0x18),
                                     packet=batch_packet_prelit, geo_flags=0xD)
    finally:
        wc.quantizer = usual
    with open(out_mdl, "wb") as f:
        f.write(mdl)
    # the dictionary: only the new textures (it is this model's alone), alpha kept (the fronds are cut out by it)
    texs, whole = [], sum(area.values()) or 1.0
    for tex in sorted(bytex):
        if tex not in textures:
            log("  texture %s missing in the pack" % tex)
            continue
        size = max(32, min(tex_max, 1 << max(5, math.ceil(math.log2(max(1e-9, math.sqrt(area[tex] / whole)) * 256)))))
        sw, sh, src = textures[tex]
        if cut_out(textures[tex]):
            size = max(size, min(tex_max, 128))  # leaflets need texels: smaller, they blur into a veil
        w, h, rgba, gain = foliage_downscale(sw, sh, src, size)
        if cut_out(textures[tex]):
            rgba = bleed(w, h, binary_alpha(rgba))
        r = raster(w, h, rgba)
        texs.append((tex[:31].encode("latin1"), r["w4"], r["flags"], r["data"]))
        if hd is not None:
            hd.append((tex, w, h, decoded(w, h, r), textures[tex], bool(wind) and tex in cut))
        log("  texture %-26s %3dx%-3d %d-bit (%2.0f%% of the area)%s" % (
            tex, w, h, r["flags"] >> 12 & 0x3F, 100 * area[tex] / whole, "  alpha x%.2f" % gain if gain != 1 else ""))
    xet = wc.build_xet(texs)
    with open(out_xet, "wb") as f:
        f.write(xet)
    log("  model: %d tris, %d strip verts, %d bytes (%d sectors, VCS's %d); textures: %d bytes (%d sectors)" % (
        total_tris, total, len(mdl), (len(mdl) + 2047) // 2048, (len(vd) + 2047) // 2048, len(xet), (len(xet) + 2047) // 2048))
    return {"tris": total_tris, "mdl": len(mdl), "xet": len(xet)}


class Pack:
    """The pack's files from its zip or an unpacked folder, found by name under its VC 1.0 install"""
    kind = "80's VC True Vegetation (VC PC)"

    def __init__(self, path):
        self.path = path
        self.zip = zipfile.ZipFile(path) if zipfile.is_zipfile(path) else None
        self.tmp = tempfile.mkdtemp(prefix="veg_")

    def dff(self, name):
        return self.file("Replace and import gta3.img/%s.dff" % name)

    def has(self, name):
        if self.zip:
            want = (PACK_DIR + "Replace and import gta3.img/%s.dff" % name).lower()
            return any(n.replace("\\", "/").lower() == want for n in self.zip.namelist())
        return any(os.path.isfile(os.path.join(b, "Replace and import gta3.img", name + ".dff"))
                   for b in (os.path.join(self.path, PACK_DIR), self.path))

    def txds(self):
        """the texture dictionaries to look the models' textures up in, in order"""
        return [self.file("models/generic.txd"), self.file("Replace and import gta3.img/gtatrees.txd")]

    def file(self, rel):
        """a local path of the pack's file (extracted to a temporary folder from a zip)"""
        if self.zip:
            name = next((n for n in self.zip.namelist() if n.replace("\\", "/").lower() == (PACK_DIR + rel).lower()), None)
            if name is None:
                tc.fail("%s not in %s" % (PACK_DIR + rel, self.path))
            out = os.path.join(self.tmp, os.path.basename(rel))
            with open(out, "wb") as f:
                f.write(self.zip.read(name))
            return out
        for base in (os.path.join(self.path, PACK_DIR), self.path):
            p = os.path.join(base, rel)
            if os.path.isfile(p):
                return p
        tc.fail("%s not found under %s" % (rel, self.path))

    def close(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class BsorPack:
    """BSOR Vegetation (GTA SA, a modloader folder): 'files dff/<name>.dff'; the textures in the dictionaries
    thetxdp.ide names as the parents of SA's vegetation dictionaries (one, bsor5s_txdp.txd, in 'files txd') - every
    dictionary in 'files txd' when none is named. SA PC files: RW 3.6 (0x1803FFFF); their night vertex colours
    (0x253F2F9), empty 2dfx (0x253F2FD) and day prelighting are not used (VCS's palms are a flat grey)"""
    kind = "BSOR Vegetation (SA PC)"

    @staticmethod
    def detect(path):
        return os.path.isdir(os.path.join(path, "files dff"))

    def __init__(self, path):
        self.path = path

    def dff(self, name):
        p = os.path.join(self.path, "files dff", name + ".dff")
        if not os.path.isfile(p):
            tc.fail("%s not found in %s" % (name + ".dff", os.path.join(self.path, "files dff")))
        return p

    def has(self, name):
        return os.path.isfile(os.path.join(self.path, "files dff", name + ".dff"))

    def txds(self):
        folder = os.path.join(self.path, "files txd")
        files = {f.lower(): os.path.join(folder, f) for f in os.listdir(folder) if f.lower().endswith(".txd")}
        parents = []
        ide = os.path.join(self.path, "thetxdp.ide")
        if os.path.isfile(ide):
            section = None
            for line in open(ide, encoding="latin1"):
                line = line.split("#")[0].strip()
                if not line:
                    continue
                if line.lower() in ("txdp", "end"):
                    section = line.lower() if line.lower() == "txdp" else None
                    continue
                if section == "txdp" and "," in line:
                    parent = line.split(",")[1].strip().lower() + ".txd"
                    if parent in files and files[parent] not in parents:
                        parents.append(files[parent])
        return parents or sorted(files.values())

    def close(self):
        pass


def open_pack(path):
    return BsorPack(path) if BsorPack.detect(path) else Pack(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", help="the 80's VC True Vegetation zip (or its unpacked folder), or BSOR Vegetation's "
                    "modloader folder (SA; found by its 'files dff' folder)")
    ap.add_argument("--only", help="comma-separated model names")
    ap.add_argument("--tris", type=int, default=600, help="the opaque parts' (trunks') triangle budget per model; the leaf cards stay as made")
    ap.add_argument("--tex", type=int, default=256, help="largest texture side")
    ap.add_argument("--mods", default=os.path.join(tc.BUILD, "mods"))
    ap.add_argument("--iso")
    ap.add_argument("--remove", action="store_true", help="delete the overrides this tool writes")
    ap.add_argument("--hd", action="store_true", help="also the pack's full-size textures as texture replacements: a "
                    "hidden run names the converted ones (VCS_TEXTURE_DUMP), each gets its full-size image under that name")
    ap.add_argument("--hd-dump", help="an existing dump folder instead of the hidden run")
    ap.add_argument("--hd-out", default=os.path.join(tc.BUILD, "textures", "SLUS-21590", "replacements", "vegetation"))
    ap.add_argument("--port", type=int, default=7791, help="the hidden run's control port")
    ap.add_argument("--save", default=os.path.join(tc.BUILD, "rig", "saves", "user"), help="card copy the hidden run starts from")
    a = ap.parse_args()
    models = dict(PALMS, **TREES)
    if a.only:
        models = {k: v for k, v in models.items() if k in a.only.split(",")}
    stream = os.path.join(a.mods, "stream")
    if a.remove:
        for name, (mid, _, _, tid, _, _) in models.items():
            for f in ("%d.ldm" % mid, "%d.xet" % tid):
                if os.path.isfile(os.path.join(stream, f)):
                    os.remove(os.path.join(stream, f))
                    print("removed", os.path.join(stream, f))
        return
    if not a.pack:
        tc.fail("--pack <80's vc True vegetation.zip> is needed")
    iso = tc.find_iso(a.iso)
    os.makedirs(stream, exist_ok=True)
    pack = open_pack(a.pack)
    print("pack:", pack.kind)
    try:
        missing = [name for name in models if not pack.has(name)]
        if missing:
            print("not in the pack (the game's own stay): " + ", ".join(missing))
            models = {k: v for k, v in models.items() if k not in missing}
        dffs = {name: pack.dff(name) for name in models}
        wanted = {(m["texture"] or "").lower() for path in dffs.values() for g in rwdff.parse_dff(path)[1] for m in g.materials}
        txds = pack.txds()
        print("reading %d textures from the pack (%s)" % (len(wanted), ", ".join(os.path.basename(t) for t in txds)))
        textures = {}
        for t in txds:  # full size: foliage_downscale
            textures.update({k: v for k, v in rwtxd.read_txd(t, 4096, wanted).items() if k not in textures})
        hd = [] if a.hd else None
        for name, (mid, mpos, msz, tid, tpos, tsz) in models.items():
            print("%s -> model %d, textures %d" % (name, mid, tid))
            vd = wc.read_img(iso, mpos, msz)
            if vd[:4] != b"ldm\0":
                tc.fail("%s: no 'ldm' at sector 0x%x of GTA3PS2.IMG - another disc?" % (name, mpos))
            convert(name, dffs[name], textures, vd, mid, os.path.join(stream, "%d.ldm" % mid),
                    os.path.join(stream, "%d.xet" % tid), a.tris, a.tex, hd=hd)
        print("written to", stream)
        if a.hd:
            dump = a.hd_dump
            if not dump:
                dump = os.path.join(tc.BUILD, "veg_hd", "dump")
                shutil.rmtree(dump, ignore_errors=True)
                print("naming the textures: a hidden run looks at each model (port %d)" % a.port)
                hd_capture(models, a.mods, dump, a.port, a.save)
            n = hd_textures(hd, dump, a.hd_out, os.path.join(a.mods, "wind.txt"))
            print("%d full-size textures written to %s (F2 > Graphics > Texture replacements)" % (n, a.hd_out))
    finally:
        pack.close()


if __name__ == "__main__":
    main()
