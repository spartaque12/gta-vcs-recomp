// Streamed files replaced from a folder: any file the game streams through CStreaming (a model's 'ldm' chunk, a texture
// dictionary's 'xet', collision, animation) is taken from <mods>/stream/<id>.<ext> when such a file exists, so models
// converted from other games (the Immersive Weapons Pack port, tools/weapon_convert.py) load without a new
// disc image. <id> is the CStreaming id (models 0..7533, texture dictionaries from 7534, ...; game-internals.md 12g).
// <mods> is VCS_MODS_DIR or "mods" next to vcs.exe. VCS_STREAM_OVERRIDE=0 replaces nothing (the reference).
#pragma once

class PS2Runtime;

namespace vcs::streamoverride
{
    // Before runtime.run() (applyVcs). Hooks nothing when the folder holds no file.
    void install(PS2Runtime &runtime);
}
