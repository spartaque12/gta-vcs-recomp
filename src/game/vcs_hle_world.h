// The native world draw (vcs_hle_world.cpp) as the RSL world draws (vcs_rsl_world.cpp) use it: a world packet's mesh -
// its content key and converted vertices - kept with a recorded geometry block so a replay needs neither the hashing nor
// the conversion. Both are per thread and cover one MSCAL.
#pragma once

#include <cstdint>
#include <vector>

namespace vcs::hleworld
{
    struct WorldMesh
    {
        bool valid = false;
        uint64_t key = 0;
        uint32_t count = 0;
        std::vector<uint8_t> vertices; // count x 32 bytes (vs_world's layout)
    };

    // the next world packet the native handler draws stores its mesh here (it is marked valid when it does)
    void setMeshCapture(WorldMesh *capture);
    // the next world packet takes its mesh from here when it has the same vertex count (the replay of the same block)
    void setMeshHint(const WorldMesh *hint);

    // The mod API's lit-model refiner (VcsModApi::set_lit_refiner, modapi/vcs_mod_api.h): a mod's replacement geometry
    // for lit model batches. fn: VcsLitRefineFn; nullptr removes it.
    void setLitRefiner(const void *fn, void *user);
    // another refiner, asked before the one set (VcsModApi::add_lit_refiner); false when 8 are added already
    bool addLitRefiner(const void *fn, void *user);
}
