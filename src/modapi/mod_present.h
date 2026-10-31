// The mods' present hook and split layers (VcsModApi.add_present_hook / render_set_split_layers / present_window_copy;
// docs/MODDING.md "VR"): what the VR mod (VR.asi, docs/VR_PLAN.md M0) needs from the frame - the D3D11 device, a call
// just before the window's frame is presented, the game's picture without the HUD and the HUD alone.
#pragma once

struct VcsModApi;

namespace vcs::modapi::present_hooks
{
    void fillApi(VcsModApi &api);
}
