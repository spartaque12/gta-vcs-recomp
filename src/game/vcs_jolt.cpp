// See vcs_jolt.h and docs/game-internals.md 12h.
#include "game/vcs_jolt.h"

#include "physics/ragdoll.h"
#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"
#include "runtime/ps2_control.h"
#include "settings/settings.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <iterator>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace vcs::jolt
{
    namespace
    {
        constexpr uint32_t kRamMask = 0x01FFFFFFu;
        constexpr uint32_t kSetDie = 0x0020A3B8u;         // CPed::SetDie(ped a0, ...): ped state 0x39
        constexpr uint32_t kApplyMoveSpeed = 0x00348098u; // CPhysical::ApplyMoveSpeed(entity a0): position += speed x step
        constexpr uint32_t kAfterWorld = 0x00408C30u;     // called only at 0x3BABDC, right after CWorld::Process
        constexpr uint32_t kTreeUpdate = 0x0024E8D0u;     // an anim tree's bone matrices (tree a0)
        constexpr uint32_t kTreeUpdateInPedRender = 0x003C3280u; // its return address in FUN_003c3250 (s0 = the ped)
        constexpr uint32_t kAfterBones = 0x0020C310u;            // CPed::IsPlayer, called by the ped's render next
        constexpr uint32_t kAfterBonesInPedRender = 0x00200740u; // its return address there (a0 = the ped)
        // CPed::InflictDamage(ped a0, attacker a1, weapon a2, damage f12, piece a3, direction t0); it calls SetDie
        constexpr uint32_t kInflictDamage = 0x001D7940u;
        constexpr int kBlastDamage = 0x31; // its weapon for a blast (CWorld::TriggerExplosion's)
        // CWeapon::ProcessLineOfSight(start* a0, end* a1, colpoint* a2, entity** a3, weapon t0, shooter t1, ...): every
        // bullet's line - FireInstantHit's, each shotgun pellet's, drive-bys' (free aim's hook, installed after, wraps
        // this one with its line put in)
        constexpr uint32_t kLineOfSight = 0x002D0870u;
        constexpr int kT0 = 8;
        // CWorld::TriggerExplosion(position* a0, culprit a1, ..., radius f12, power f13): a blast's push and damage
        constexpr uint32_t kTriggerExplosion = 0x00192760u;
        constexpr uint32_t kPedPool = 0x00487A94u, kPedSize = 0xD20u; // CPool: +0 entries, +4 flag bytes, +8 size
        constexpr uint32_t kVehiclePool = 0x00487A98u, kVehicleSize = 0x8C0u;
        constexpr uint32_t kModelInfos = 0x00486518u; // CModelInfo::ms_modelInfoPtrs
        // a model info's CColModel; its bounding box's min / max (16-byte vectors) in the model's frame
        constexpr uint32_t kModelColModel = 0x14u, kColBoxMin = 0x10u, kColBoxMax = 0x20u;
        constexpr uint32_t kVehicleMoveSpeed = 0x140u; // x 50 = m/s
        constexpr uint32_t kVehicleType = 0x354u;      // 0 car, 1 boat, 2 jetski, 4 heli, 5 plane, 6 bike, 8 BMX, 9 quad
        constexpr uint32_t kPedPosition = 0x30u, kPedMoveSpeed = 0x140u, kPedVehicle = 0x480u, kPedState = 0x8C4u;
        constexpr uint32_t kPedModel = 0x56u;
        constexpr uint32_t kStateDying = 0x39u, kStateDead = 0x3Au;
        constexpr uint32_t kTimeStep = 0x004CD110u;     // CTimer::ms_fTimeStep (1.0 = 1/50 s)
        constexpr uint32_t kFrameCounter = 0x004CD124u; // CTimer::m_FrameCounter
        // RslTAnimTree: +0x04 node count, +0x28 the bones' world matrices (0x40 each), +0x30 node info (8 bytes each:
        // id, index, flags - 2 push, 1 pop the parent, as RenderWare's HAnim - and a pad byte; then the node's frame)
        constexpr uint32_t kTreeNodes = 0x04u, kTreeMatrices = 0x28u, kTreeNodeInfo = 0x30u;
        constexpr uint32_t kNodePush = 2u, kNodePop = 1u;
        constexpr int kA0 = 4, kA1 = 5, kA2 = 6, kA3 = 7, kS0 = 16, kRa = 31;
        constexpr int kBones = physics::kPedBones;
        constexpr size_t kMaxDolls = 24;        // more: the oldest is frozen in its last pose
        constexpr float kSoles = 1.0f;          // a standing ped's position is 1 m over its soles
        constexpr uint32_t kSeedFrames = 15;    // a death noted longer ago than this (off screen) starts still
        constexpr uint32_t kPendingFrames = 3000; // ... and is forgotten after this, never drawn
        constexpr float kGameMoved = 2.0f;      // the game moved the ped by more than this: a teleport, a respawn
        constexpr uint32_t kHitFrames = 10;     // a blow this recent is the one that killed
        constexpr float kVehicleReach = 15.0f;  // vehicles this near a ragdoll's hips are obstacles in the physics
        constexpr float kVehicleClearance = 0.25f; // ... their box raised off the ground: lying bodies go under, as wheels

        // The push of a killing blow (kg m/s) by weapon type (game-internals.md 12d), after SA's Jolt Physics mod's
        // DeathPush column: blunt weapons a shove, blades little, guns by calibre, shotguns the most; thrown weapons and
        // rockets none (their explosion moves the ped itself).
        constexpr float kKillPush[40] = {
            25, 25, 10, 30, 25, 10, 40, 30, 15, 15, 15, 10, // 0 unarmed .. 11 chainsaw
            0, 0, 0, 0, 0, 0, 0,                            // 12 grenade .. 18 rocket
            70, 105, 125, 125, 115,                         // 19 Colt45, 20 Python, 21 Shotgun, 22 Spas12, 23 Stubby
            60, 60, 55, 65, 70, 85,                         // 24 Tec9, 25 Uzi, 26 SilencedIngram, 27 Mp5, 28 m4, 29 Ruger
            100, 100, 0, 0, 100, 100, 0, 120, 0, 0};        // 30, 31 sniper rifles, 34 M60, 35 Minigun, 37 HeliCannon
        constexpr int kShotguns[] = {21, 22, 23};

        // A bullet on a body already down (kg m/s; a shotgun's per pellet), after SA's mod's PhysicsForce x its
        // CorpseBulletReactionIntensity (2).
        constexpr float kCorpsePush[40] = {
            0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, // melee
            0, 0, 0, 0, 0, 0, 0,                // thrown, rocket
            50, 90, 45, 45, 45,                 // Colt45, Python, the shotguns (a pellet)
            40, 40, 35, 45, 60, 70,             // Tec9, Uzi, SilencedIngram, Mp5, m4, Ruger
            120, 120, 0, 0, 90, 90, 0, 150, 0, 0};
        constexpr float kBlastSpeed = 12.0f; // m/s at a power-300 blast's centre (a grenade, a rocket, a car), down to 0 at its edge

        struct Death
        {
            int generation = 0;
            float velocity[3] = {}; // m/s at SetDie
            uint32_t frame = 0;
        };

        // The last blow a ped took (InflictDamage's arguments): what pushes its ragdoll when it was the one that killed.
        struct Hit
        {
            uint32_t attacker = 0;
            int weapon = -1, piece = 0; // piece: VC's 0 torso, 1 mid, 2 left arm, 3 right arm, 4 left leg, 5 right leg, 6 head
            uint32_t frame = 0;
            bool vehicle = false;       // the attacker is a vehicle: its speed then (m/s; the hit slows it)
            float speed[3] = {};
            float pedSpeed[3] = {};     // the ped's own before the blow (the game knocks it back after)
        };

        // A recent blast: it throws the ragdolls there, and those its damage makes in the next frames.
        struct Blast
        {
            float centre[3] = {}, radius = 0.0f, speed = 0.0f;
            uint32_t frame = 0;
        };

        struct Obstacle
        {
            int id = 0;          // physics'
            int generation = 0, model = -1;
            uint32_t seen = 0;   // the frame it was last near a ragdoll
        };

        struct Doll
        {
            int id = 0;              // physics' (0: frozen - its last pose is kept)
            int generation = 0;      // its pool slot's, at death
            uint32_t frame = 0;      // made
            physics::BoneMatrix bones[kBones];
            float followX = 0.0f, followY = 0.0f; // the ped's position as last written
        };

        std::atomic<bool> g_enabled{false};
        std::atomic<int> g_force{100}; // Hit force, percent
        PS2Runtime::RecompiledFunction g_origSetDie = nullptr, g_origMove = nullptr, g_origAfterWorld = nullptr,
                                       g_origTree = nullptr, g_origAfterBones = nullptr, g_origInflict = nullptr,
                                       g_origLineOfSight = nullptr, g_origExplosion = nullptr;

        // game thread
        std::unordered_map<uint32_t, Death> g_pending; // ped -> its death, until its next draw
        std::unordered_map<uint32_t, Doll> g_dolls;    // ped -> its ragdoll
        std::unordered_map<uint32_t, uint32_t> g_trees; // ped -> its anim tree (noted / ragdolled peds), last draw
        std::unordered_map<uint32_t, Hit> g_hits;       // ped -> the last blow it took
        std::unordered_map<uint32_t, Obstacle> g_obstacles; // vehicle -> its box in the physics, while near a ragdoll
        std::vector<Blast> g_blasts;                        // the last few blasts
        unsigned g_steps = 0, g_created = 0, g_removed = 0, g_corpseHits = 0, g_blasted = 0;
        uint32_t g_newest = 0;   // the last ped given a ragdoll

        // for the control channel's "jolt" (another thread)
        struct Status
        {
            int dolls = 0, frozen = 0, pending = 0, obstacles = 0;
            unsigned steps = 0, created = 0, removed = 0, corpseHits = 0, blasted = 0;
            uint32_t ped = 0, tree = 0;
            bool awake = false;
            float pelvis[16] = {}; // the newest ragdoll's pelvis bone (1) as written
            physics::Stats physics;
        };
        std::mutex g_statusMutex;
        Status g_status;

        uint32_t rd32(const uint8_t *ram, uint32_t a)
        {
            uint32_t v;
            std::memcpy(&v, ram + (a & kRamMask), 4);
            return v;
        }
        float rdf(const uint8_t *ram, uint32_t a)
        {
            float v;
            std::memcpy(&v, ram + (a & kRamMask), 4);
            return v;
        }
        void wrf(uint8_t *ram, uint32_t a, float v) { std::memcpy(ram + (a & kRamMask), &v, 4); }

        // The ped's pool slot generation (the flag byte's low 7 bits; 0x80 = free), or -1 when it is not a used slot.
        int generation(const uint8_t *ram, uint32_t ped)
        {
            const uint32_t pool = rd32(ram, kPedPool);
            if (!pool)
                return -1;
            const uint32_t base = rd32(ram, pool), flags = rd32(ram, pool + 4), size = rd32(ram, pool + 8);
            if (ped < base || (ped - base) % kPedSize || (ped - base) / kPedSize >= size)
                return -1;
            const uint8_t f = ram[(flags + (ped - base) / kPedSize) & kRamMask];
            return f & 0x80 ? -1 : f & 0x7F;
        }

        // A used vehicle pool slot's entity.
        bool isVehicle(const uint8_t *ram, uint32_t e)
        {
            const uint32_t pool = rd32(ram, kVehiclePool);
            if (!pool || !e)
                return false;
            const uint32_t base = rd32(ram, pool), flags = rd32(ram, pool + 4), size = rd32(ram, pool + 8);
            if (e < base || (e - base) % kVehicleSize || (e - base) / kVehicleSize >= size)
                return false;
            return !(ram[(flags + (e - base) / kVehicleSize) & kRamMask] & 0x80);
        }

        float length(const float *v) { return std::sqrt(v[0] * v[0] + v[1] * v[1] + v[2] * v[2]); }

        // Still the ped that died: its slot not freed or reused, dying or dead.
        bool stillDead(const uint8_t *ram, uint32_t ped, int gen)
        {
            if (generation(ram, ped) != gen)
                return false;
            const uint32_t state = rd32(ram, ped + kPedState);
            return state == kStateDying || state == kStateDead;
        }

        // The tree's hierarchy from its node flags: -1 for the root.
        void hierarchy(const uint8_t *ram, uint32_t info, int *parents)
        {
            int stack[kBones], depth = 0, parent = -1;
            for (int i = 0; i < kBones; ++i)
            {
                const uint32_t flags = (rd32(ram, info + i * 8u) >> 16) & 0xFFu;
                parents[i] = parent;
                if ((flags & kNodePush) && depth < kBones)
                    stack[depth++] = parent;
                parent = (flags & kNodePop) ? (depth ? stack[--depth] : -1) : i;
            }
        }

        // The ragdoll's pose into the tree's matrices (rows X, Y, Z and position; their w lanes are the game's).
        void write(uint8_t *ram, uint32_t tree, const physics::BoneMatrix *bones)
        {
            const uint32_t matrices = rd32(ram, tree + kTreeMatrices);
            if (!matrices || rd32(ram, tree + kTreeNodes) != uint32_t(kBones))
                return;
            for (int i = 0; i < kBones; ++i)
                for (uint32_t r = 0; r < 4; ++r)
                    std::memcpy(ram + ((matrices + i * 0x40u + r * 0x10u) & kRamMask), bones[i].m + r * 4, 12);
        }

        void publish()
        {
            Status st;
            for (const auto &[ped, doll] : g_dolls)
                ++(doll.id ? st.dolls : st.frozen);
            st.pending = int(g_pending.size());
            st.obstacles = int(g_obstacles.size());
            st.corpseHits = g_corpseHits;
            st.blasted = g_blasted;
            st.steps = g_steps;
            st.created = g_created;
            st.removed = g_removed;
            if (const auto it = g_dolls.find(g_newest); it != g_dolls.end())
            {
                st.ped = g_newest;
                const auto tree = g_trees.find(g_newest);
                st.tree = tree != g_trees.end() ? tree->second : 0;
                st.awake = it->second.id && physics::awake(it->second.id);
                std::copy(it->second.bones[1].m, it->second.bones[1].m + 16, st.pelvis);
            }
            st.physics = physics::stats();
            std::lock_guard<std::mutex> lock(g_statusMutex);
            g_status = st;
        }

        void remove(std::unordered_map<uint32_t, Doll>::iterator it, const char *why)
        {
            if (it->second.id)
                physics::destroy(it->second.id);
            std::fprintf(stderr, "[jolt] ped %08X: ragdoll removed (%s)\n", it->first, why);
            g_trees.erase(it->first);
            g_dolls.erase(it);
            ++g_removed;
        }

        // A killing shot or blow from a ped: a push from the attacker's side on the part hit, the trunk taking the rest
        // (shotguns: the whole trunk, harder close up), level and a little up. The push's size, 0 when none.
        float blow(const uint8_t *ram, int id, const Hit &hit, const physics::BoneMatrix *bones, float force)
        {
            if (hit.weapon < 0 || hit.weapon >= int(std::size(kKillPush)) || kKillPush[hit.weapon] <= 0.0f ||
                generation(ram, hit.attacker) < 0)
                return 0.0f;
            struct Piece
            {
                int part, rest;
                float share; // the part's; the rest's is 1 - share
            };
            static constexpr Piece kPieces[7] = {
                {physics::kChest, physics::kHips, 0.7f},     {physics::kHips, physics::kChest, 0.7f},
                {physics::kUpperArmL, physics::kChest, 0.3f}, {physics::kUpperArmR, physics::kChest, 0.3f},
                {physics::kThighL, physics::kHips, 0.5f},    {physics::kThighR, physics::kHips, 0.5f},
                {physics::kHead, physics::kChest, 0.25f}};
            const bool shotgun = std::find(std::begin(kShotguns), std::end(kShotguns), hit.weapon) != std::end(kShotguns);
            const Piece &piece = kPieces[shotgun || hit.piece < 0 || hit.piece > 6 ? 0 : hit.piece];
            const float *chest = bones[3].m + 12; // spine1
            float d[3] = {chest[0] - rdf(ram, hit.attacker + kPedPosition), chest[1] - rdf(ram, hit.attacker + kPedPosition + 4),
                          0.0f};
            const float distance = std::sqrt(d[0] * d[0] + d[1] * d[1]);
            if (distance < 0.05f)
                return 0.0f;
            d[0] /= distance;
            d[1] /= distance;
            d[2] = shotgun ? 0.25f : 0.15f;
            float push = kKillPush[hit.weapon] * force;
            if (shotgun)
                push *= std::clamp(1.6f - 0.06f * distance, 1.0f, 1.6f);
            float a[3], b[3];
            for (int k = 0; k < 3; ++k)
            {
                a[k] = d[k] * push * piece.share;
                b[k] = d[k] * push * (1.0f - piece.share);
            }
            physics::push(id, piece.part, a);
            physics::push(id, piece.rest, b);
            return push;
        }

        // Run down by a vehicle: the bumper takes the legs at its speed and lifts them, the trunk and head follow less,
        // so the body folds back onto the bonnet; the vehicle's box in the physics carries and throws it from there.
        void runDown(int id, const Hit &hit, float force)
        {
            //                                                hips  chest  head   arms ...................  legs .....................
            static constexpr float kShare[physics::kPartTotal] = {0.6f, 0.25f, 0.15f, 0.3f, 0.3f, 0.3f, 0.3f, 0.9f, 1.0f, 0.9f, 1.0f};
            static constexpr float kLift[physics::kPartTotal] = {0.15f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.0f, 0.25f, 0.3f, 0.25f, 0.3f};
            const float speed = length(hit.speed);
            for (int p = 0; p < physics::kPartTotal; ++p)
            {
                const float dv[3] = {hit.speed[0] * kShare[p] * force, hit.speed[1] * kShare[p] * force,
                                     (hit.speed[2] * kShare[p] + speed * kLift[p]) * force};
                physics::kick(id, p, dv);
            }
        }

        // A ped noted at its death, drawn: its ragdoll from the bones its render just built.
        void build(uint8_t *ram, uint32_t ped, uint32_t tree, const Death &death)
        {
            auto refuse = [ped](const char *why) { std::fprintf(stderr, "[jolt] ped %08X: no ragdoll (%s)\n", ped, why); };
            if (!stillDead(ram, ped, death.generation) || rd32(ram, ped + kPedVehicle))
                return refuse("not dying any more, or in a vehicle");
            const uint32_t matrices = rd32(ram, tree + kTreeMatrices), info = rd32(ram, tree + kTreeNodeInfo);
            if (rd32(ram, tree + kTreeNodes) != uint32_t(kBones) || !matrices || !info)
                return refuse("not a 25-bone tree");
            physics::BoneMatrix bones[kBones];
            for (int i = 0; i < kBones; ++i)
                std::memcpy(bones[i].m, ram + ((matrices + i * 0x40u) & kRamMask), 64);
            const float px = rdf(ram, ped + kPedPosition), py = rdf(ram, ped + kPedPosition + 4),
                        pz = rdf(ram, ped + kPedPosition + 8);
            const float dx = bones[0].m[12] - px, dy = bones[0].m[13] - py, dz = bones[0].m[14] - pz;
            if (dx * dx + dy * dy + dz * dz > 4.0f)
                return refuse("its bones are not where it is");
            int parents[kBones];
            hierarchy(ram, info, parents);
            physics::RagdollDesc desc;
            desc.bones = bones;
            desc.parents = parents;
            // the blow that killed it (InflictDamage calls SetDie), if one did
            const uint32_t now = rd32(ram, kFrameCounter);
            const bool fresh = now - death.frame <= kSeedFrames;
            const auto hitIt = g_hits.find(ped);
            const Hit hit = fresh && hitIt != g_hits.end() && now - hitIt->second.frame <= kHitFrames + kSeedFrames
                                ? hitIt->second
                                : Hit{};
            const bool pushed = !hit.vehicle && hit.weapon >= 0 && hit.weapon < int(std::size(kKillPush)) &&
                                kKillPush[hit.weapon] > 0.0f && generation(ram, hit.attacker) >= 0;
            // its speed: when the blow is ours to give (blow), its own walking or running (2 m/s at most): the game
            // knocks it back before InflictDamage - a shotgun 5.6 m/s -, and both would throw it metres; run down, none
            // (runDown gives its parts the vehicle's speed in shares); else the faster of SetDie's and the one the game
            // gave it since (a blast's)
            float later[3], own[3];
            for (uint32_t k = 0; k < 3; ++k)
                later[k] = rdf(ram, ped + kPedMoveSpeed + 4 * k) * 50.0f;
            const float ownScale = std::min(1.0f, 2.0f / std::max(length(hit.pedSpeed), 1e-3f));
            for (int k = 0; k < 3; ++k)
                own[k] = hit.pedSpeed[k] * ownScale;
            // a blast's victim: none either - the game threw it as one block before the damage; the blast's own throw
            // part by part replaces that (below). Any recent blast that reaches it counts: its damage comes as the
            // blast's weapon (a grenade's 12, a car's 49)
            const float *hips = bones[2].m + 12;
            auto reaches = [&](const Blast &b) {
                const float d[3] = {hips[0] - b.centre[0], hips[1] - b.centre[1], hips[2] - b.centre[2]};
                return now - b.frame <= kHitFrames + kSeedFrames && length(d) < b.radius;
            };
            const bool blasted = fresh && (hit.weapon == kBlastDamage || std::any_of(g_blasts.begin(), g_blasts.end(), reaches));
            const float *speed = pushed ? own : length(later) > length(death.velocity) ? later : death.velocity;
            for (int k = 0; k < 3; ++k)
                desc.velocity[k] = fresh && !hit.vehicle && !blasted ? speed[k] : 0.0f;
            const float force = static_cast<float>(g_force.load(std::memory_order_relaxed)) / 100.0f;
            // the ground: under the soles of a ped standing at its position (or its lowest bone, if that is lower)
            float lowest = pz;
            for (const physics::BoneMatrix &b : bones)
                lowest = std::min(lowest, b.m[14]);
            desc.groundZ = std::min(pz - kSoles, lowest - 0.02f);
            const int id = physics::create(desc);
            if (!id)
                return refuse("the physics refused it - its reason above");
            Doll &doll = g_dolls[ped];
            doll.id = id;
            doll.generation = death.generation;
            doll.frame = rd32(ram, kFrameCounter);
            doll.followX = px;
            doll.followY = py;
            physics::pose(id, doll.bones);
            write(ram, tree, doll.bones);
            const float push = pushed && !blasted ? blow(ram, id, hit, bones, force) : 0.0f;
            if (hit.vehicle)
                runDown(id, hit, force);
            // the blasts of the last frames that reach it (the one that killed it, most likely)
            unsigned blasts = 0;
            for (const Blast &b : g_blasts)
                if (fresh && reaches(b))
                {
                    physics::blast(id, b.centre, b.radius, b.speed);
                    ++blasts;
                }
            g_hits.erase(ped);
            g_newest = ped;
            ++g_created;
            std::fprintf(stderr,
                         "[jolt] ped %08X (model %d): ragdoll %d at (%.2f, %.2f, %.2f), %.2f m/s (SetDie %.2f, since %.2f), "
                         "ground %.2f; killed by %08X (%s, weapon %d, piece %d), push %.0f, vehicle %.1f m/s, blasts %u\n",
                         ped, int(int16_t(rd32(ram, ped + kPedModel) & 0xFFFFu)), id, px, py, pz, length(desc.velocity),
                         length(death.velocity), length(later), desc.groundZ, hit.attacker,
                         hit.vehicle ? "a vehicle" : hit.attacker ? "a ped" : "nobody", hit.weapon, hit.piece, push,
                         length(hit.speed), blasts);
            // too many: the oldest still simulated keeps its last pose
            size_t live = 0;
            for (const auto &[p, d] : g_dolls)
                live += d.id != 0;
            if (live > kMaxDolls)
            {
                auto oldest = g_dolls.end();
                for (auto it = g_dolls.begin(); it != g_dolls.end(); ++it)
                    if (it->second.id && (oldest == g_dolls.end() || it->second.frame < oldest->second.frame))
                        oldest = it;
                physics::destroy(oldest->second.id);
                oldest->second.id = 0;
            }
        }

        // The ped's position follows its body's root bone (culling and the world's lists go where the body lies);
        // false when the game moved it itself (a teleport, the player's respawn): the ragdoll is left then.
        bool follow(uint8_t *ram, uint32_t ped, Doll &doll)
        {
            const float px = rdf(ram, ped + kPedPosition), py = rdf(ram, ped + kPedPosition + 4);
            if (std::fabs(px - doll.followX) > kGameMoved || std::fabs(py - doll.followY) > kGameMoved)
                return false;
            doll.followX = doll.bones[0].m[12];
            doll.followY = doll.bones[0].m[13];
            wrf(ram, ped + kPedPosition, doll.followX);
            wrf(ram, ped + kPedPosition + 4, doll.followY);
            return true;
        }

        // Vehicles near a simulated ragdoll are boxes in the physics - their col model's bounding box, raised off the
        // ground - moved with them every step: a car throws a body it runs into and rolls over one lying under it. The
        // others are taken out (all of them when no ragdoll is simulated).
        void vehicles(const uint8_t *ram, float seconds)
        {
            const uint32_t now = rd32(ram, kFrameCounter);
            float hips[kMaxDolls + 1][3];
            size_t dolls = 0;
            for (const auto &[ped, doll] : g_dolls)
                if (doll.id && dolls <= kMaxDolls)
                    std::copy(doll.bones[2].m + 12, doll.bones[2].m + 15, hips[dolls++]);
            const uint32_t pool = dolls ? rd32(ram, kVehiclePool) : 0;
            const uint32_t base = pool ? rd32(ram, pool) : 0, flags = pool ? rd32(ram, pool + 4) : 0,
                           size = pool ? rd32(ram, pool + 8) : 0;
            const uint32_t infos = rd32(ram, kModelInfos);
            for (uint32_t i = 0; i < size; ++i)
            {
                const uint8_t flag = ram[(flags + i) & kRamMask];
                const uint32_t v = base + i * kVehicleSize;
                if (flag & 0x80)
                    continue;
                const float x = rdf(ram, v + kPedPosition), y = rdf(ram, v + kPedPosition + 4), z = rdf(ram, v + kPedPosition + 8);
                bool near = false;
                for (size_t d = 0; d < dolls && !near; ++d)
                    near = (x - hips[d][0]) * (x - hips[d][0]) + (y - hips[d][1]) * (y - hips[d][1]) +
                               (z - hips[d][2]) * (z - hips[d][2]) < kVehicleReach * kVehicleReach;
                if (!near)
                    continue;
                const int model = int(int16_t(rd32(ram, v + kPedModel) & 0xFFFFu)), gen = flag & 0x7F;
                physics::BoneMatrix m;
                std::memcpy(m.m, ram + (v & kRamMask), 64); // right, forward, up, position
                auto it = g_obstacles.find(v);
                if (it != g_obstacles.end() && (it->second.generation != gen || it->second.model != model))
                {
                    physics::removeObstacle(it->second.id);
                    g_obstacles.erase(it);
                    it = g_obstacles.end();
                }
                if (it == g_obstacles.end())
                {
                    const uint32_t col = model >= 0 && infos ? rd32(ram, rd32(ram, infos + uint32_t(model) * 4) + kModelColModel) : 0;
                    if (!col)
                        continue;
                    float lo[3], hi[3];
                    for (uint32_t k = 0; k < 3; ++k)
                    {
                        lo[k] = rdf(ram, col + kColBoxMin + 4 * k);
                        hi[k] = rdf(ram, col + kColBoxMax + 4 * k);
                    }
                    lo[2] = std::min(lo[2] + kVehicleClearance, hi[2] - 0.3f);
                    const int id = physics::addObstacle(m, lo, hi, rd32(ram, v + kVehicleType) == 0); // 0: a car
                    if (!id)
                        continue;
                    it = g_obstacles.emplace(v, Obstacle{id, gen, model, now}).first;
                }
                else
                    physics::moveObstacle(it->second.id, m, seconds);
                it->second.seen = now;
            }
            for (auto it = g_obstacles.begin(); it != g_obstacles.end();)
                if (it->second.seen != now)
                {
                    physics::removeObstacle(it->second.id);
                    it = g_obstacles.erase(it);
                }
                else
                    ++it;
        }

        // Once a game frame, after the world's update: stale ragdolls go, the physics steps, the poses are taken.
        void frame(uint8_t *ram)
        {
            const bool on = g_enabled.load(std::memory_order_relaxed);
            for (auto it = g_dolls.begin(); it != g_dolls.end();)
            {
                auto next = std::next(it);
                if (!on)
                    remove(it, "switched off");
                else if (!stillDead(ram, it->first, it->second.generation))
                    remove(it, "the ped is gone or up");
                it = next;
            }
            const uint32_t now = rd32(ram, kFrameCounter);
            for (auto it = g_pending.begin(); it != g_pending.end();)
                if (!on || !stillDead(ram, it->first, it->second.generation) || now - it->second.frame > kPendingFrames)
                {
                    if (!g_dolls.count(it->first))
                        g_trees.erase(it->first);
                    it = g_pending.erase(it);
                }
                else
                    ++it;
            for (auto it = g_hits.begin(); it != g_hits.end();)
                it = now - it->second.frame > kHitFrames + kSeedFrames ? g_hits.erase(it) : std::next(it);
            g_blasts.erase(std::remove_if(g_blasts.begin(), g_blasts.end(),
                                          [now](const Blast &b) { return now - b.frame > kHitFrames + kSeedFrames; }),
                           g_blasts.end());
            const float step = rdf(ram, kTimeStep);
            vehicles(ram, step > 0.0f ? step / 50.0f : 0.0f);
            if (!g_dolls.empty() && step > 0.0f)
            {
                physics::step(step / 50.0f);
                ++g_steps;
            }
            for (auto it = g_dolls.begin(); it != g_dolls.end();)
            {
                auto next = std::next(it);
                Doll &doll = it->second;
                if (doll.id)
                {
                    physics::pose(doll.id, doll.bones);
                    if (!follow(ram, it->first, doll))
                        remove(it, "moved by the game");
                }
                it = next;
            }
            publish();
        }

        // CPed::SetDie(ped a0): the ped and its velocity, for its next draw.
        PS2_GUEST_CC void setDie(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            const uint32_t ped = GPR_U32(ctx, kA0);
            if (g_enabled.load(std::memory_order_relaxed) && ped && !g_dolls.count(ped))
            {
                const uint32_t state = rd32(rdram, ped + kPedState);
                const int gen = generation(rdram, ped);
                if (gen >= 0 && state != kStateDying && state != kStateDead && !rd32(rdram, ped + kPedVehicle))
                {
                    Death &death = g_pending[ped];
                    death.generation = gen;
                    for (uint32_t k = 0; k < 3; ++k)
                        death.velocity[k] = rdf(rdram, ped + kPedMoveSpeed + 4 * k) * 50.0f;
                    death.frame = rd32(rdram, kFrameCounter);
                }
            }
            return g_origSetDie(rdram, ctx, runtime);
        }

        // CPed::InflictDamage(ped a0, attacker a1, weapon a2, damage f12, piece a3, direction t0): who hit the ped, with
        // what, where - its ragdoll's push when this blow kills it (the original calls SetDie then).
        PS2_GUEST_CC void inflictDamage(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            const uint32_t now = rd32(rdram, kFrameCounter);
            const auto same = g_hits.find(GPR_U32(ctx, kA0));
            // a shotgun's pellets, a car's contacts: the burst's first blow is the one taken (the game knocks the ped
            // back between them)
            if (g_enabled.load(std::memory_order_relaxed) && GPR_U32(ctx, kA0) &&
                (same == g_hits.end() || same->second.frame != now || same->second.attacker != GPR_U32(ctx, kA1)))
            {
                Hit &hit = g_hits[GPR_U32(ctx, kA0)];
                hit.attacker = GPR_U32(ctx, kA1);
                hit.weapon = int(GPR_U32(ctx, kA2));
                hit.piece = int(GPR_U32(ctx, kA3));
                hit.frame = now;
                hit.vehicle = isVehicle(rdram, hit.attacker);
                for (uint32_t k = 0; k < 3; ++k)
                {
                    hit.speed[k] = hit.vehicle ? rdf(rdram, hit.attacker + kVehicleMoveSpeed + 4 * k) * 50.0f : 0.0f;
                    hit.pedSpeed[k] = rdf(rdram, GPR_U32(ctx, kA0) + kPedMoveSpeed + 4 * k) * 50.0f;
                }
            }
            return g_origInflict(rdram, ctx, runtime);
        }

        // CWeapon::ProcessLineOfSight(start* a0, end* a1, ..., weapon t0, shooter t1): a bullet whose line meets a ragdolled
        // body moves it, at the point it meets it - cast against the ragdolls themselves: the game's own collision for a
        // dead ped is not where its ragdoll lies (pistol shots at a body's hips hit the road under them).
        PS2_GUEST_CC void lineOfSight(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            const int weapon = int(GPR_U32(ctx, kT0));
            if (!g_dolls.empty() && GPR_U32(ctx, kA0) && GPR_U32(ctx, kA1) && weapon >= 0 &&
                weapon < int(std::size(kCorpsePush)) && kCorpsePush[weapon] > 0.0f)
            {
                float from[3], to[3];
                for (uint32_t k = 0; k < 3; ++k)
                {
                    from[k] = rdf(rdram, GPR_U32(ctx, kA0) + 4 * k);
                    to[k] = rdf(rdram, GPR_U32(ctx, kA1) + 4 * k);
                }
                const float push = kCorpsePush[weapon] * static_cast<float>(g_force.load(std::memory_order_relaxed)) / 100.0f;
                if (physics::shoot(from, to, push))
                    ++g_corpseHits;
            }
            return g_origLineOfSight(rdram, ctx, runtime);
        }

        // CWorld::TriggerExplosion(position* a0, ..., radius f12, power f13): the ragdolls within its radius are thrown,
        // and those its damage is about to make (build) will be.
        PS2_GUEST_CC void triggerExplosion(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            const float radius = ctx->f[12], power = ctx->f[13];
            if (g_enabled.load(std::memory_order_relaxed) && GPR_U32(ctx, kA0) && radius > 0.0f && radius < 100.0f &&
                power > 0.0f)
            {
                Blast b;
                for (uint32_t k = 0; k < 3; ++k)
                    b.centre[k] = rdf(rdram, GPR_U32(ctx, kA0) + 4 * k);
                b.radius = radius;
                b.speed = kBlastSpeed * std::min(power, 1000.0f) / 300.0f *
                          static_cast<float>(g_force.load(std::memory_order_relaxed)) / 100.0f;
                b.frame = rd32(rdram, kFrameCounter);
                if (g_blasts.size() >= 8)
                    g_blasts.erase(g_blasts.begin());
                g_blasts.push_back(b);
                unsigned thrown = 0;
                for (const auto &[ped, doll] : g_dolls)
                {
                    const float *hips = doll.bones[2].m + 12;
                    const float d[3] = {hips[0] - b.centre[0], hips[1] - b.centre[1], hips[2] - b.centre[2]};
                    if (doll.id && length(d) < b.radius + 1.0f)
                    {
                        physics::blast(doll.id, b.centre, b.radius, b.speed);
                        ++thrown;
                    }
                }
                g_blasted += thrown;
                std::fprintf(stderr, "[jolt] blast at (%.1f, %.1f, %.1f), radius %.1f, power %.0f: %u ragdolls thrown\n",
                             b.centre[0], b.centre[1], b.centre[2], radius, power, thrown);
            }
            return g_origExplosion(rdram, ctx, runtime);
        }

        // CPhysical::ApplyMoveSpeed(entity a0): a ragdolled ped is where its body is.
        PS2_GUEST_CC void applyMoveSpeed(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            if (!g_dolls.empty() && g_dolls.count(GPR_U32(ctx, kA0)))
            {
                ctx->pc = GPR_U32(ctx, kRa);
                return;
            }
            return g_origMove(rdram, ctx, runtime);
        }

        // FUN_00408c30, right after CWorld::Process (SetDie has run for this frame's deaths).
        PS2_GUEST_CC void afterWorld(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            if (!g_dolls.empty() || !g_pending.empty())
                frame(rdram);
            return g_origAfterWorld(rdram, ctx, runtime);
        }

        // An anim tree's bones built in a ped's render (FUN_003c3250, s0 = the ped): the tree of a noted / ragdolled ped.
        PS2_GUEST_CC void treeUpdate(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            if ((!g_pending.empty() || !g_dolls.empty()) && GPR_U32(ctx, kRa) == kTreeUpdateInPedRender)
            {
                const uint32_t ped = GPR_U32(ctx, kS0);
                if (g_pending.count(ped) || g_dolls.count(ped))
                    g_trees[ped] = GPR_U32(ctx, kA0);
            }
            return g_origTree(rdram, ctx, runtime);
        }

        // The ped's render, its bones built, before the skinned draw: a noted ped gets its ragdoll, a ragdolled one its
        // pose.
        PS2_GUEST_CC void afterBones(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            if ((!g_pending.empty() || !g_dolls.empty()) && GPR_U32(ctx, kRa) == kAfterBonesInPedRender)
            {
                const uint32_t ped = GPR_U32(ctx, kA0);
                const auto tree = g_trees.find(ped);
                if (tree != g_trees.end())
                {
                    if (const auto doll = g_dolls.find(ped); doll != g_dolls.end())
                    {
                        if (stillDead(rdram, ped, doll->second.generation))
                            write(rdram, tree->second, doll->second.bones);
                    }
                    else if (const auto death = g_pending.find(ped); death != g_pending.end())
                    {
                        const Death d = death->second;
                        g_pending.erase(death);
                        build(rdram, ped, tree->second, d);
                        if (!g_dolls.count(ped))
                            g_trees.erase(ped);
                    }
                }
            }
            return g_origAfterBones(rdram, ctx, runtime);
        }
    }

    void registerSettings()
    {
        using namespace settings;
        Spec s;
        s.key = "physics.ragdolls";
        s.page = "Game";
        s.section = "Physics";
        s.label = "Ragdolls (Jolt Physics)";
        s.help = "Peds go limp when they die, as with San Andreas' Jolt Physics mod: the body falls with the speed it had "
                 "instead of playing a death animation. For now it lands on flat ground at the ped's feet - walls, stairs "
                 "and cars don't stop it yet.";
        s.type = Type::Toggle;
        s.defaultValue = 0;
        s.env = "VCS_JOLT";
        s.onChange = [](int v) { g_enabled = v != 0; };
        add(s);

        s = {};
        s.key = "physics.ragdoll_force";
        s.page = "Game";
        s.section = "Physics";
        s.label = "Hit force";
        s.help = "How hard the shot, blow or vehicle that kills a ped throws its body (shotguns hardest, close up). 0: it "
                 "only falls.";
        s.type = Type::Integer;
        s.min = 0;
        s.max = 300;
        s.format = "%d %%";
        s.defaultValue = 100;
        s.onChange = [](int v) { g_force = v; };
        add(s);
    }

    void install(PS2Runtime &runtime)
    {
        if (const char *e = std::getenv("VCS_JOLT_HOOKS"); e && e[0] == '0')
            return;
        g_origSetDie = runtime.lookupFunction(kSetDie);
        g_origMove = runtime.lookupFunction(kApplyMoveSpeed);
        g_origAfterWorld = runtime.lookupFunction(kAfterWorld);
        g_origTree = runtime.lookupFunction(kTreeUpdate);       // first person's, when it is installed
        g_origAfterBones = runtime.lookupFunction(kAfterBones); // first person's, when it is installed
        g_origInflict = runtime.lookupFunction(kInflictDamage);
        g_origLineOfSight = runtime.lookupFunction(kLineOfSight); // the original: free aim installs after, around this
        g_origExplosion = runtime.lookupFunction(kTriggerExplosion);
        if (!g_origSetDie || !g_origMove || !g_origAfterWorld || !g_origTree || !g_origAfterBones || !g_origInflict ||
            !g_origLineOfSight || !g_origExplosion)
            return;
        runtime.replaceFunction(kSetDie, &setDie);
        runtime.replaceFunction(kApplyMoveSpeed, &applyMoveSpeed);
        runtime.replaceFunction(kAfterWorld, &afterWorld);
        runtime.replaceFunction(kTreeUpdate, &treeUpdate);
        runtime.replaceFunction(kAfterBones, &afterBones);
        runtime.replaceFunction(kInflictDamage, &inflictDamage);
        runtime.replaceFunction(kLineOfSight, &lineOfSight);
        runtime.replaceFunction(kTriggerExplosion, &triggerExplosion);
        // jolt -> ok enabled= dolls= ... ped= tree= awake= pelvis=<16 floats> (tests: tools/ragdoll_check.py)
        ps2control::addCommand("jolt", [](const std::string &, ps2control::Reply reply) {
            Status st;
            {
                std::lock_guard<std::mutex> lock(g_statusMutex);
                st = g_status;
            }
            char text[640];
            int n = std::snprintf(text, sizeof(text),
                                  "ok enabled=%d dolls=%d frozen=%d pending=%d steps=%u created=%u removed=%u bodies=%u "
                                  "active=%u obstacles=%d corpsehits=%u blasted=%u stepms=%.3f ped=%08x tree=%08x awake=%d "
                                  "pelvis=",
                                  g_enabled ? 1 : 0, st.dolls, st.frozen, st.pending, st.steps, st.created, st.removed,
                                  st.physics.bodies, st.physics.activeBodies, st.obstacles, st.corpseHits, st.blasted,
                                  st.physics.stepMs, st.ped, st.tree, st.awake ? 1 : 0);
            for (int i = 0; i < 16 && n > 0 && n < int(sizeof(text)); ++i)
                n += std::snprintf(text + n, sizeof(text) - n, i ? ",%.4f" : "%.4f", st.pelvis[i]);
            reply(text);
        });
    }
}
