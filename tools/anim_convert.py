"""GTA SA weapon animations (IFP, ANP3) -> VCS animation blocks ('mina' chunks), written as streamed-file overrides
(src/game/vcs_stream_override.h: <mods>/stream/<id>.anim).

    python tools/anim_convert.py --pack "<...>/modloader/Immersive Weapons Pack" [--only colt45,python] [--mods DIR]
    python tools/anim_convert.py --block colt45 --ifp colt45.ifp --map colt45_fire=colt45_fire_2hands,...
    python tools/anim_convert.py --dump 8408            (the block's anims, tracks and keys, from the disc)

A VCS animation block (docs/game-internals.md 12i) holds the hierarchies of one animation group: at 0x20 an array of
pointers to them, then the key data, the hierarchies (0x28 bytes: tracks, name[24], track count, duration, a size)
and the tracks (12 bytes: flags 0x9 rotation / 0xb rotation + translation, key count, keys, bone id, the bone's
hash). Keys are half floats: a quaternion (x, y, z, w), the time since the previous key, for 0xb tracks a translation.
The game copies hierarchy i to its animation slot (the block's first + i) when the block loads, so a block keeps its
anims' count, order and names; their keys are replaced.

Retargeting: SA's and VCS's ped skeletons are the same Biped layout with the same bone ids (0 root .. 5 head, 21-25
right arm, 31-35 left arm, 41-43 / 51-53 legs; SA adds finger01 26 / 36, toes 44 / 54 and face bones, which have no
VCS bone and are left out). Keys are absolute local rotations, so the skeletons' rest poses do not enter, only the
bones' frames: compared on the anims both games share (the same first frames to within a few degrees where the pack
kept the original; no bone with a constant offset across anims) they agree, so the correction per bone is the
identity (REST_CORRECTION, quaternions applied as parent^-1 * q * own) and the root translation keeps its scale
(crouching: SA -0.58 m, VCS -0.59 .. -0.63). SA's translations of other bones (the pack's arms carry SA's bone
lengths) are dropped - VCS's skeleton gives its own. SA's fire anims count on SA's aiming IK (a bent elbow, the spine
tipping the gun up): a standing fire anim keeps only the arms, both clavicles turned so the gun hand matches VCS's own
anim at the weapon's fire point (aim_alignment). Keys are thinned where a slerp between their neighbours stays
within 0.4 degrees (SA's are per frame)."""
import argparse, math, os, struct, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def u32(d, o): return struct.unpack_from("<I", d, o)[0]

# VCS's weapon animation blocks: name -> (CStreaming id, GTA3PS2.IMG sector, sectors), read in the game (2026-10-31)
BLOCKS = {
    "buddy": (8404, 0x2df3, 8), "colt45": (8408, 0x2dc3, 4), "python": (8459, 0x2dcd, 6), "RIFLE": (8464, 0x2dd9, 10),
    "shotgun": (8467, 0x2de9, 5), "sniper": (8469, 0x2e29, 3), "TEC": (8474, 0x5cbd, 9), "UZI": (8480, 0x2e0a, 9),
}
# The Immersive Weapons Pack's animations for them: block -> (IFP, {VCS anim: pack anim}); anims not listed keep
# VCS's keys (colt45_cop: the police stance). The pistols fire two-handed (the pack's default "Hold Pistols with Two
# Hands"); the shotgun takes the pack's chromegun set (newshot), the sniper rifle its bolt-action set (boltsnp).
_P = "VI - Animations/anims/"
PACK = {
    # the Colt45 aims with the arm (its CWeaponInfo flag 0x80: VCS's IK turns the right upper arm alone, which points
    # the gun only along a straight arm - SA's two-handed and bent-elbow fire anims came out 30 degrees off the aim and
    # the IK gave up, game-internals.md 12i): its fire anims stay VCS's, the reloads are the pack's
    "colt45": (_P + "colt45.ifp", {"colt45_crouchreload": "colt45_crouchreload", "colt45_reload": "colt45_reload"}),
    "python": (_P + "python.ifp", {"python_crouchfire": "python_crouchfire", "python_crouchreload": "python_crouchreload",
                                    "python_fire": "python_fire", "python_reload": "python_reload"}),
    "shotgun": (_P + "newshot.ifp", {"shotgun_crouchfire": "newshot_crouchfire", "shotgun_fire": "newshot_fire"}),
    "buddy": (_P + "buddy.ifp", {"buddy_crouchfire": "buddy_crouchfire", "buddy_fire": "buddy_fire",
                                  "buddy_reload": "buddy_reload"}),
    "UZI": (_P + "uzi.ifp", {"UZI_crouchfire": "UZI_crouchfire", "UZI_crouchreload": "UZI_crouchreload",
                              "UZI_fire": "UZI_fire", "UZI_reload": "UZI_reload"}),
    "TEC": (_P + "tecani.ifp", {"TEC_crouchfire": "tecani_crouchfire", "TEC_crouchreload": "tecani_crouchreload",
                                 "TEC_fire": "tecani_fire_2hands", "TEC_reload": "tecani_reload"}),
    "RIFLE": (_P + "rifle.ifp", {"RIFLE_crouchfire": "RIFLE_crouchfire", "RIFLE_crouchload": "RIFLE_crouchload",
                                  "RIFLE_fire": "RIFLE_fire", "RIFLE_load": "Rifle_load"}),
    "sniper": (_P + "boltsnp.ifp", {"sniper_fire": "BOLTSNP_fire", "sniper_reload": "BOLTSNP_load"}),
}
# VCS's animated bones in its tracks' order, each with the hash its tracks carry (read from VCS's own blocks)
VCS_BONES = [(0, 0xdf9e), (1, 0xb88a), (2, 0x9a64), (3, 0xbcfc), (4, 0xe97b), (5, 0x6e99),
             (31, 0xb052), (32, 0x2830), (33, 0x1e52), (34, 0xc7d5), (35, 0xa1c5),
             (21, 0x8935), (22, 0x1157), (23, 0x7a50), (24, 0xfe09), (25, 0xc8f4),
             (41, 0xcdd3), (42, 0xccec), (43, 0x2938), (51, 0xfa32), (52, 0xf530), (53, 0x10e4)]
PARENT = {1: 0, 2: 1, 3: 2, 4: 3, 5: 4, 31: 4, 32: 31, 33: 32, 34: 33, 35: 34, 21: 4, 22: 21, 23: 22, 24: 23, 25: 24,
          41: 2, 42: 41, 43: 42, 51: 2, 52: 51, 53: 52}
# when VCS's weapons fire, as their CWeaponInfo +0x44.. gives it (fire / crouched fire point, s; game-internals.md 12d)
FIRE_POINT = {"colt45_fire": 0.47, "colt45_crouchfire": 0.40, "python_fire": 0.47, "python_crouchfire": 0.53,
              "shotgun_fire": 0.50, "shotgun_crouchfire": 0.43, "buddy_fire": 0.50, "buddy_crouchfire": 0.43,
              "UZI_fire": 0.43, "UZI_crouchfire": 0.43, "TEC_fire": 0.47, "TEC_crouchfire": 0.40, "RIFLE_fire": 0.43,
              "RIFLE_crouchfire": 0.43, "sniper_fire": 0.43}
REST_CORRECTION = {}   # bone id -> quaternion (x, y, z, w) from SA's bone frame to VCS's; none needed (see above)
ROOT_SCALE = 1.0

# ---- quaternions ----------------------------------------------------------------------------------------------------
def qmul(a, b):
    ax, ay, az, aw = a; bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)

def qinv(a): return (-a[0], -a[1], -a[2], a[3])

def qnorm(q):
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return tuple(x / n for x in q)

def slerp(a, b, t):
    d = sum(x * y for x, y in zip(a, b))
    if d < 0:
        b, d = tuple(-x for x in b), -d
    if d > 0.9995:
        return qnorm(tuple(x + (y - x) * t for x, y in zip(a, b)))
    th = math.acos(min(1.0, d))
    s = math.sin(th)
    wa, wb = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return tuple(wa * x + wb * y for x, y in zip(a, b))

def angle(a, b):
    d = abs(sum(x * y for x, y in zip(a, b)))
    return math.degrees(2 * math.acos(min(1.0, d)))

# ---- SA IFP -----------------------------------------------------------------------------------------------------------
def read_ifp(path):
    """ANP3: {anim name (lower case): (name, [{name, bone, keys: [(t s, quat, trans or None)]}])}"""
    d = open(path, "rb").read()
    if d[:4] != b"ANP3":
        raise ValueError("%s: not an ANP3 IFP" % path)
    p, anims = 36, {}
    for _ in range(u32(d, 32)):
        name = d[p:p + 24].split(b"\0")[0].decode("latin1")
        nn, fsz, comp = struct.unpack_from("<III", d, p + 24)
        p += 36
        nodes = []
        for _ in range(nn):
            bn = d[p:p + 24].split(b"\0")[0].decode("latin1")
            ft, nf, bid = struct.unpack_from("<III", d, p + 24)
            p += 36
            rot_only = ft in (1, 3)
            keys = []
            for _ in range(nf):
                if comp:
                    if rot_only:
                        qx, qy, qz, qw, t = struct.unpack_from("<5h", d, p); p += 10; tr = None
                    else:
                        qx, qy, qz, qw, t, tx, ty, tz = struct.unpack_from("<8h", d, p); p += 16
                        tr = (tx / 1024.0, ty / 1024.0, tz / 1024.0)
                    keys.append((t / 60.0, (qx / 4096.0, qy / 4096.0, qz / 4096.0, qw / 4096.0), tr))
                else:
                    if rot_only:
                        v = struct.unpack_from("<5f", d, p); p += 20; tr = None
                    else:
                        v = struct.unpack_from("<8f", d, p); p += 32
                        tr = tuple(v[5:8])
                    keys.append((v[4], tuple(v[0:4]), tr))
            nodes.append({"name": bn, "bone": bid, "keys": keys})
        anims[name.lower()] = (name, nodes)
    return anims

# ---- VCS animation blocks -----------------------------------------------------------------------------------------
def half(h): return struct.unpack("<e", struct.pack("<H", h))[0]

def parse_block(d):
    """-> [{name, dur, size, tracks: [{flags, bone, hash, keys: [(dt, q, p or None)]}]}]"""
    reloc, nrel = u32(d, 0x10), u32(d, 0x14)
    places = set(struct.unpack_from("<%dI" % nrel, d, reloc))
    count = 0
    while 0x20 + 4 * count in places:  # the pointer array: relocated words from 0x20 on
        count += 1
    out = []
    for i in range(count):
        a = u32(d, 0x20 + 4 * i)
        tp = u32(d, a)
        name = d[a + 4:a + 28].split(b"\0")[0].decode("latin1")
        ntr, dur, size = struct.unpack_from("<IfI", d, a + 28)
        tracks = []
        for k in range(ntr):
            flags, nk, kp, bone, hsh = struct.unpack_from("<HHIHH", d, tp + 12 * k)
            stride = 16 if flags & 2 else 10
            keys = []
            for j in range(nk):
                h = [half(x) for x in struct.unpack_from("<%dH" % (stride // 2), d, kp + stride * j)]
                keys.append((h[4], tuple(h[0:4]), tuple(h[5:8]) if stride == 16 else None))
            tracks.append({"flags": flags, "bone": bone, "hash": hsh, "keys": keys})
        out.append({"name": name, "dur": dur, "size": size, "tracks": tracks})
    return out

def build_block(anims):
    """anims as parse_block gives them -> the 'mina' chunk"""
    b = bytearray(0x20)
    relocs = []
    ptr_array = len(b)
    b += bytes(4 * len(anims))
    key_at = []  # per anim, per track: the key data's offset
    for an in anims:
        offs = []
        for tr in an["tracks"]:
            while len(b) % 4:  # each track's keys start on a word, as in the game's blocks
                b.append(0)
            offs.append(len(b))
            for dt, q, p in tr["keys"]:
                v = list(q) + [dt] + (list(p) if tr["flags"] & 2 else [])
                b += struct.pack("<%de" % len(v), *v)
        key_at.append(offs)
    while len(b) % 4:
        b.append(0)
    hier_at = []
    for an in anims:
        hier_at.append(len(b))
        b += bytes(0x28)
    for i, an in enumerate(anims):
        tracks_at = len(b)
        for k, tr in enumerate(an["tracks"]):
            b += struct.pack("<HHIHH", tr["flags"], len(tr["keys"]), key_at[i][k], tr["bone"], tr["hash"])
            relocs.append(tracks_at + 12 * k + 4)
        h = hier_at[i]
        struct.pack_into("<I", b, h, tracks_at)
        relocs.append(h)
        nm = an["name"].encode("latin1")[:23]
        b[h + 4:h + 4 + len(nm)] = nm
        struct.pack_into("<IfI", b, h + 28, len(an["tracks"]), an["dur"], an["size"])
        struct.pack_into("<I", b, ptr_array + 4 * i, h)
        relocs.append(ptr_array + 4 * i)
    data_end = len(b)
    for r in relocs:
        b += struct.pack("<I", r)
    struct.pack_into("<4sIIIIIIHH", b, 0, b"mina", 0, len(b), data_end, data_end, len(relocs), 0, 0, 0)
    return bytes(b)

def read_img(iso, pos, sectors):
    import weapon_convert
    return weapon_convert.read_img(iso, pos, sectors)

def block_from_disc(iso, name):
    sid, pos, sectors = BLOCKS[name]
    d = read_img(iso, pos, sectors)
    return d[:u32(d, 8)]

# ---- retargeting ----------------------------------------------------------------------------------------------------
def thin(keys, tol=0.4):
    """keys [(t, q, p)] -> fewer keys: drop those a slerp / lerp of their kept neighbours reproduces within tol degrees
    (and 2 mm for translations)"""
    if len(keys) <= 2:
        return keys
    kept = [0]
    i = 0
    while i < len(keys) - 1:
        j = i + 2
        # extend the span while every key inside is reproduced
        while j < len(keys):
            ok = True
            t0, q0, p0 = keys[i]
            t1, q1, p1 = keys[j]
            for k in range(i + 1, j):
                tk, qk, pk = keys[k]
                f = (tk - t0) / (t1 - t0) if t1 > t0 else 0.0
                if angle(slerp(q0, q1, f), qk) > tol:
                    ok = False
                    break
                if pk is not None and math.dist([a + (b - a) * f for a, b in zip(p0, p1)], pk) > 0.002:
                    ok = False
                    break
            if not ok:
                break
            j += 1
        kept.append(j - 1)
        i = j - 1
    return [keys[k] for k in kept]

def sample(keys, t):
    """rotation of [(t, q, ...)] at time t (slerp)"""
    for i in range(len(keys) - 1):
        if keys[i][0] <= t <= keys[i + 1][0]:
            span = keys[i + 1][0] - keys[i][0]
            return slerp(keys[i][1], keys[i + 1][1], (t - keys[i][0]) / span if span > 0 else 0.0)
    return keys[-1][1] if t > keys[0][0] else keys[0][1]

def arm_rotation(keys_by_bone, t):
    """the gun hand's orientation in the neck's frame: clavicle * upper arm * forearm * hand (21-24) at t"""
    q = (0.0, 0.0, 0.0, 1.0)
    for b in (21, 22, 23, 24):
        q = qmul(q, sample(keys_by_bone[b], t))
    return q

def vcs_keys(anim):
    """a parsed VCS hierarchy's tracks as {bone: [(t, q, p)]} with absolute times"""
    out = {}
    for tr in anim["tracks"]:
        t, ks = 0.0, []
        for dt, q, p in tr["keys"]:
            t += dt
            ks.append((t, q, p))
        out[tr["bone"]] = ks
    return out

def aim_alignment(nodes, ref, t):
    """SA's fire anims leave the arm bent for SA's aiming IK to straighten; VCS's IK does less, and its anims hold the
    gun out themselves. The rotation (in the neck's frame) that turns SA's gun hand at the fire point onto VCS's own
    anim's there; applied to both clavicles it points the gun as VCS does, keeps SA's motion, and the other hand of a
    two-handed hold moves with it. None when either lacks the arm."""
    sa = {n["bone"]: [(k[0], qnorm(k[1])) for k in n["keys"]] for n in nodes if n["keys"]}
    if not all(b in sa and b in ref for b in (21, 22, 23, 24)):
        return None
    return qnorm(qmul(arm_rotation(ref, t), qinv(arm_rotation(sa, t))))

ARMS = (21, 22, 23, 24, 25, 31, 32, 33, 34, 35)

def body_track(own, dur):
    """one of VCS's own tracks (parsed, delta times) cut or held to `dur` s: [(t, q, p)] absolute times"""
    t, ks = 0.0, []
    for dt, q, p in own["keys"]:
        t += dt
        ks.append((t, q, p))
    if ks[-1][0] > dur:
        q = sample(ks, dur)
        prev = [k for k in ks if k[0] < dur]
        nxt = next(k for k in ks if k[0] >= dur)
        p = None
        if nxt[2] is not None:
            a = prev[-1] if prev else nxt
            f = (dur - a[0]) / (nxt[0] - a[0]) if nxt[0] > a[0] else 0.0
            p = tuple(x + (y - x) * f for x, y in zip(a[2], nxt[2]))
        ks = prev + [(dur, q, p)]
    return ks

def retarget(name, sa_name, nodes, size_hint=0, log=print, align=None, own=None):
    """SA nodes -> a VCS hierarchy {name, dur, size, tracks}; align: (VCS's own anim as vcs_keys, time) to point the
    gun as it does; own: VCS's own anim (parsed) - a fire anim takes its body from it"""
    by_bone = {}
    for n in nodes:
        if n["bone"] in PARENT or n["bone"] == 0:
            by_bone.setdefault(n["bone"], n)
    g = aim_alignment(nodes, *align) if align else None
    body = {}
    if align:
        # a fire anim: SA's arms on VCS's own body. SA's root / spine / neck keys (the arms' parents) assume SA's aiming
        # IK and tip the gun upward, and VCS's IK turns the torso of VCS's own pose (its fire anims turn the shoulders
        # for a rifle), so the body is VCS's anim's (or, where that has only the arms, the ped's other anims, as VCS's)
        # and the arms are aligned in the neck's frame (game-internals.md 12i)
        by_bone = {b: n for b, n in by_bone.items() if b in ARMS}
        if own:
            body = {tr["bone"]: tr for tr in own["tracks"] if tr["bone"] not in ARMS}
    dur = max(n["keys"][-1][0] for n in nodes if n["keys"])
    tracks, nkeys = [], 0
    order = list(VCS_BONES)
    for b, tr in body.items():  # bones VCS's anim has that the list lacks (UZI_fire's 6) after the head
        if b not in dict(VCS_BONES):
            order.insert(6, (b, tr["hash"]))
    for bone, hsh in order:
        if bone in body:
            ks = body_track(body[bone], dur)
            last, deltas = 0.0, []
            for t, q, p in ks:
                deltas.append((t - last, q, p))
                last = t
            tracks.append({"flags": body[bone]["flags"], "bone": bone, "hash": body[bone]["hash"], "keys": deltas})
            nkeys += len(deltas)
            continue
        n = by_bone.get(bone)
        if not n or not n["keys"]:
            continue
        keys = []
        prev = None
        for t, q, p in n["keys"]:
            q = qnorm(q)
            if g is not None and bone in (21, 31):
                q = qmul(g, q)
            if bone in REST_CORRECTION or PARENT.get(bone) in REST_CORRECTION:
                q = qmul(qmul(qinv(REST_CORRECTION.get(PARENT.get(bone), (0, 0, 0, 1))), q),
                         REST_CORRECTION.get(bone, (0, 0, 0, 1)))
            if prev is not None and sum(x * y for x, y in zip(prev, q)) < 0:
                q = tuple(-x for x in q)  # the short way round, for interpolation
            prev = q
            keys.append((t, q, tuple(x * ROOT_SCALE for x in p) if (bone == 0 and p) else None))
        if keys[0][0] > 0:
            keys.insert(0, (0.0,) + keys[0][1:])
        if keys[-1][0] < dur:
            keys.append((dur,) + keys[-1][1:])
        keys = thin(keys)
        root_t = bone == 0 and keys[0][2] is not None
        deltas = []
        last = 0.0
        for t, q, p in keys:
            deltas.append((t - last, q, p if root_t else None))
            last = t
        tracks.append({"flags": 0xB if root_t else 0x9, "bone": bone, "hash": hsh, "keys": deltas})
        nkeys += len(deltas)
    data = sum(len(t["keys"]) * (16 if t["flags"] & 2 else 10) for t in tracks)
    size = max(size_hint, 0x28 + 12 * len(tracks) + data)
    log("    %-20s <- %-22s %.3f s, %2d tracks, %4d keys (SA's %d)" % (name, sa_name, dur, len(tracks), nkeys,
                                                                       sum(len(n["keys"]) for n in nodes)))
    return {"name": name, "dur": dur, "size": size, "tracks": tracks}

def convert_block(block, iso, ifp_path, mapping, out_path, log=print):
    vcs = parse_block(block_from_disc(iso, block))
    sa = read_ifp(ifp_path)
    out = []
    for an in vcs:
        src = mapping.get(an["name"])
        if not src:
            log("    %-20s    VCS's own" % an["name"])
            out.append(an)
            continue
        if src.lower() not in sa:
            raise ValueError("%s has no %s" % (ifp_path, src))
        sname, nodes = sa[src.lower()]
        align = None
        if "fire" in an["name"].lower():
            ref = vcs_keys(an)
            t = FIRE_POINT.get(an["name"], an["dur"] / 2)
            if all(b in ref for b in (21, 22, 23, 24)):
                align = (ref, t)
        h = retarget(an["name"], sname, nodes, an["size"], log=log, align=align, own=an if align else None)
        if align:
            log("      gun hand aligned to VCS's at %.2f s" % align[1])
        out.append(h)
    d = build_block(out)
    # self-check: what we wrote parses back to the same anims
    back = parse_block(d)
    assert [a["name"] for a in back] == [a["name"] for a in out]
    with open(out_path, "wb") as f:
        f.write(d)
    log("  -> %s: %d bytes (%d sectors; VCS's %d)" % (out_path, len(d), (len(d) + 2047) // 2048, BLOCKS[block][2]))
    return d

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pack", help="the Immersive Weapons Pack's modloader folder: every block in PACK")
    ap.add_argument("--only", help="with --pack: these blocks (comma-separated)")
    ap.add_argument("--block", help="one VCS block (BLOCKS) with --ifp and --map")
    ap.add_argument("--ifp"); ap.add_argument("--map", help="vcs_anim=sa_anim,...")
    ap.add_argument("--dump", help="print a block (name or streaming id) from the disc")
    ap.add_argument("--iso"); ap.add_argument("--mods", default=os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "build", "mods"))
    a = ap.parse_args()
    import toolchain
    iso = a.iso or toolchain.find_iso()
    if a.dump:
        name = next((k for k, v in BLOCKS.items() if a.dump in (k, str(v[0]))), None)
        for an in parse_block(block_from_disc(iso, name)):
            print("%-22s %.3f s size %d" % (an["name"], an["dur"], an["size"]))
            for tr in an["tracks"]:
                print("    bone %2d flags %#x hash %04x keys %d" % (tr["bone"], tr["flags"], tr["hash"], len(tr["keys"])))
        return
    jobs = []
    if a.pack:
        only = set(a.only.split(",")) if a.only else None
        for name, (ifp, mapping) in PACK.items():
            if not only or name in only:
                jobs.append((name, os.path.join(a.pack, ifp), mapping))
    elif a.block and a.ifp and a.map:
        jobs.append((a.block, a.ifp, dict(kv.split("=") for kv in a.map.split(","))))
    else:
        ap.error("--pack, or --block with --ifp and --map, or --dump")
    os.makedirs(os.path.join(a.mods, "stream"), exist_ok=True)
    for name, ifp, mapping in jobs:
        print("%s (block %d) <- %s" % (name, BLOCKS[name][0], os.path.basename(ifp)), flush=True)
        convert_block(name, iso, ifp, mapping, os.path.join(a.mods, "stream", "%d.anim" % BLOCKS[name][0]))

if __name__ == "__main__":
    main()
