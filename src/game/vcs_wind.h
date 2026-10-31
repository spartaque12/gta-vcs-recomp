// Vegetation wind sway (SkyGfx Extended's for GTA SA, on the native world draws; docs/DECISIONS.md, game-internals.md 12j).
// The renderer moves the textures of a wind list (mods/wind.txt, tools/veg_convert.py) with a drifting noise field;
// here the field drifts with the game's clock and its strength follows the game's wind.
#pragma once

#include <cstdint>

namespace vcs::wind
{
    // Graphics > Vegetation wind (off by default: the PS2's palms stand still); VCS_WIND_LIST beside the mods.
    void registerSettings();
    // At the frame kick (game thread): the field's position and strength (gsHwSetWind).
    void onGameFrame(const uint8_t *rdram);
}
