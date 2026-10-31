// Death ragdolls on Jolt Physics 5.6.0 (third_party/JoltPhysics, MIT): milestone 1 of the port of SA's "[SA] Jolt
// Physics" mod (docs/game-internals.md 12f, 12h; the game side is game/vcs_jolt.cpp).
//
// A ragdoll is built from a ped's 25 bone world matrices as the game keeps them (RslTAnimTree +0x28, VC's skeleton:
// 0 root, 1 pelvis, 2-3 spine, 4 neck, 5-6 head, 7-11 left arm, 12-16 right arm, 17-20 left leg, 21-24 right leg) and
// its velocity: 11 bodies - hips (bone 2), chest (3), head (5), upper arms (8, 13), forearms (9, 14), thighs (17, 21),
// calves (18, 22) - with swing-twist joints at the waist, neck, shoulders and hips and hinges at the elbows and knees,
// in the pose the ped had. Its pose goes back as the 25 matrices: the bodies' bones from the bodies (a SkeletonMapper),
// the others (root, pelvis, neck, clavicles, hands, feet) carried rigidly with their parent as they were at death.
// For now the only thing a ragdoll lands on is a ground plane of its own (milestone 2: the world's collision).
//
// This library is the only code that sees Jolt (its own flags and defines stay here: src/physics/CMakeLists.txt). All
// calls come from the game thread. Jolt runs with round-to-nearest: every call sets it and gives the caller's MXCSR back
// (the VU paths round toward zero).
#pragma once

#include <cstdint>

namespace vcs::physics
{
    constexpr int kPedBones = 25;

    // A bone's world matrix as the game keeps it: rows X, Y, Z, position - 4 floats each, the w lanes left alone.
    struct BoneMatrix
    {
        float m[16];
    };

    struct RagdollDesc
    {
        const BoneMatrix *bones = nullptr; // the ped's 25 world matrices (its last draw)
        const int *parents = nullptr;      // their hierarchy (from the tree's node flags; -1: the root)
        float velocity[3] = {};            // m/s, every part
        float groundZ = 0.0f;              // the plane it lands on (milestone 1)
    };

    struct Stats
    {
        int ragdolls = 0;
        unsigned bodies = 0, activeBodies = 0;
        float stepMs = 0.0f; // the last step
    };

    // The physics system (Jolt's allocator, factory and types on the first call). False: it could not be made.
    bool init();

    // A ragdoll for this pose; 0 when refused (not the ped skeleton this was written for, no room in the system).
    int create(const RagdollDesc &desc);

    // The ragdoll and its ground out of the world.
    void destroy(int id);

    // The ragdoll's parts, for push(): the hips, chest, head, upper arms, forearms, thighs, calves.
    enum Part
    {
        kHips, kChest, kHead, kUpperArmL, kForearmL, kUpperArmR, kForearmR, kThighL, kCalfL, kThighR, kCalfR, kPartTotal
    };

    // A blow on one part (kg m/s, world space): a shot, a hit.
    void push(int id, int part, const float impulse[3]);

    // One part's speed changed by `dv` (m/s, world space), whatever its mass: a vehicle's bumper on the legs.
    void kick(int id, int part, const float dv[3]);

    // A bullet from `from` to `to`: the first ragdoll part on its line takes `push` (kg m/s) along it, at the point the
    // line meets it (it turns the body too). That ragdoll's id; 0 when the line meets none.
    int shoot(const float from[3], const float to[3], float push);

    // A blast at `centre`: each part within `radius` thrown away from it (and up) at up to `speed` m/s, less the farther
    // it is - the parts nearest the blast fastest, so the body tumbles.
    void blast(int id, const float centre[3], float radius, float speed);

    // A moving obstacle the ragdolls hit and are hit by (a vehicle): kinematic - nothing pushes it back -, the box given
    // by its min / max corners in its own frame (`transform`: rows X, Y, Z, position; Y ahead, Z up). car: not one block
    // but a car's - its lower body the box's whole length up to the bonnet, the cabin set back from the front - so a
    // body it runs into folds onto the bonnet. 0 when refused.
    int addObstacle(const BoneMatrix &transform, const float boxMin[3], const float boxMax[3], bool car);

    // Where it is now; the next step takes it there over `seconds` (its speed for the contacts).
    void moveObstacle(int id, const BoneMatrix &transform, float seconds);

    void removeObstacle(int id);

    // One step of `seconds` (collision steps of at most 1/60 s).
    void step(float seconds);

    // The ragdoll's pose as the ped's 25 world matrices (rows X, Y, Z and position; out[i].m's w lanes are 0).
    bool pose(int id, BoneMatrix *out);

    // True while any of its bodies moves (Jolt puts settled ones to sleep).
    bool awake(int id);

    Stats stats();
}
