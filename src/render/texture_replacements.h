// PCSX2-named PNG packs. Index and requests: GS stage; decoding: one worker; GPU upload: main thread.
#pragma once

#include <cstddef>
#include <cstdint>
#include <filesystem>
#include <memory>
#include <vector>

namespace render
{
    uint64_t textureHash(const void *data, size_t bytes);

    struct ReplacementImage
    {
        uint32_t id = 0, width = 0, height = 0;
        std::vector<uint32_t> pixels; // unmodified RGBA8: PCSX2 packs keep GS alpha (128 = opaque)
    };

    // A wind list entry (gsHwSetWind): metres per position unit, the reach (position units; footZ unused, 0)
    struct WindModel
    {
        float metresPerUnit[3] = {};
        float footZ = 0.0f, invHeight = 0.0f;
    };

    // The wind list's path (VcsModApi::render_set_wind_list): before the renderer starts, which reads it then (else the
    // environment's VCS_WIND_LIST). false once it has started, or when the file cannot be opened.
    bool setWindList(const char *path);

    class TextureReplacements
    {
    public:
        TextureReplacements();
        ~TextureReplacements();
        TextureReplacements(const TextureReplacements &) = delete;
        TextureReplacements &operator=(const TextureReplacements &) = delete;

        bool candidate(uint32_t bits) const;
        uint32_t find(uint64_t pixels, uint64_t palette, uint32_t bits);
        // VCS_TEXTURE_DUMP=<dir>: every texture the renderer hashes is written once as <dir>/<PCSX2 name>.png (GS alpha,
        // 128 = opaque) - the names a pack's images need (tools/veg_convert.py --hd). Every shape is a candidate then.
        bool dumping() const;
        void dump(uint64_t pixels, uint64_t palette, uint32_t bits, uint32_t width, uint32_t height, const uint32_t *rgba);
        // setWindList / VCS_WIND_LIST=<file> (tools/veg_convert.py writes mods/wind.txt): lines "<PCSX2 name> mx my mz 0 reach",
        // the textures whose draws sway in the wind - with or without replacements. Its shapes are candidates.
        const WindModel *wind(uint64_t pixels, uint64_t palette, uint32_t bits) const;
        void request(uint32_t id);
        std::vector<std::shared_ptr<const ReplacementImage>> takeReady();
        size_t budget() const;
        static constexpr uint64_t key(uint32_t id) { return 0xFFFF545800000000ull | id; }

    private:
        struct Impl;
        std::unique_ptr<Impl> m;
    };
}
