// The mod API's rendering part (modapi/vcs_mod_api.h "Rendering", docs/MODDING.md): mods' render hooks run at a point of
// the frame through the renderer's frame hook (runtime/gs/gs_hw.h gsHwSetFrameHook), and draw with the RHI behind
// opaque handles.
#pragma once

struct VcsModApi;

namespace vcs::modapi::render
{
    // makeApi: the table's add_render_hook and render_* functions
    void fillApi(VcsModApi &api);
}
