// Death ragdolls (Game > Physics > Ragdolls): milestone 1 of the port of San Andreas' "[SA] Jolt Physics" mod
// (docs/game-internals.md 12f, 12h). A ped that dies goes limp - a Jolt Physics ragdoll (physics/ragdoll.h) made from
// the pose and velocity it had - instead of playing its death animation, and lands on a ground plane at its feet (the
// world's collision is milestone 2).
//
// The hooks, each before the original (the bone ones chained after first person's, game/vcs_firstperson.h):
// - CPed::SetDie (FUN_0020a3b8): the ped is noted with its velocity (+0x140 x 50 = m/s).
// - The ped's render: FUN_0024e8d0 builds a tree's bones (return address 0x3C3280, s0 = the ped: its tree is noted),
//   then FUN_0020c310 is called between the bones and the skinned draw (return address 0x200740, a0 = the ped): a noted
//   ped gets its ragdoll from the bones just built, a ragdolled ped's 25 bone matrices are written from its ragdoll.
// - FUN_00408c30, called only right after CWorld::Process: the physics step (CTimer::ms_fTimeStep / 50 s); peds that were
//   removed or got up (the player after Wasted) lose their ragdoll; a ped's position follows its body.
// - CPhysical::ApplyMoveSpeed (FUN_00348098, through the vtable): not run for ragdolled peds (the body moves them).
// - CPed::InflictDamage (FUN_001d7940; it calls SetDie): the blow is noted - attacker, weapon, the piece hit. The one that
//   kills pushes the ragdoll: a shot or melee hit from the attacker's side on that part (by weapon, after SA's mod; a
//   shotgun's harder close up), in place of the game's own knock-back; a vehicle gives the legs its speed and the trunk
//   less, so the body folds onto the bonnet (Game > Physics > Hit force scales both).
// - CWeapon::ProcessLineOfSight (FUN_002d0870; every bullet's line, a shotgun's pellets each): a line that meets a
//   ragdolled body, cast against the ragdolls in the physics, pushes it at that point (the game's own collision for a
//   dead ped is not where its ragdoll lies). Free aim's hook on it, installed after, wraps this one.
// - CWorld::TriggerExplosion (FUN_00192760; position, radius f12, power f13): the ragdolls in reach are thrown part by
//   part, the nearest parts fastest; peds the blast kills get the same throw when their ragdoll is made.
// Vehicles near a ragdoll are moving boxes in the physics (their col model's bounding box; a car's as lower body and
// cabin), so they throw, carry and roll over the bodies.
// VCS_JOLT=0|1 overrides the setting for one run; VCS_JOLT_HOOKS=0 hooks nothing (the reference).
#pragma once

class PS2Runtime;

namespace vcs::jolt
{
    // The Game page's "Physics" section.
    void registerSettings();

    // Before runtime.run(), after firstperson::install (the bone hooks chain to first person's) and before
    // freeaim::install (its line of sight wraps this one's, so the bullets' lines seen here are the camera's).
    void install(PS2Runtime &runtime);
}
