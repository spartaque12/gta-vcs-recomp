// Streamed files replaced from a folder (vcs_stream_override.h). How the game streams (game-internals.md 12g):
// - CStreaming (*0x489FF8): +8 / +0xC / +0x10 the first texture dictionary / collision / animation id; +200 -> the
//   streaming infos, 0x18 bytes per id: +0xC load state (1 loaded, 3 requested), +0x10 position and +0x14 size, both in
//   2 KB sectors of GTA3PS2.IMG.
// - CStreaming::RequestModel (FUN_003C7ED8: streaming a0, id a1, flags a2) allocates a buffer of size x 2048 bytes
//   (FUN_003C6478) and reads the file's sectors into it (FUN_002213D0 -> the disc read FUN_00220EC8).
// - When the read is done FUN_003C7048 checks the bytes read against the size and calls
//   CStreaming::ConvertBufferToObject (FUN_003C72A8: streaming a0, id a1, buffer a2), which relocates the chunk in place
//   (models FUN_003C7498, dictionaries FUN_003C7918, collision FUN_003C79A8, animations FUN_003C7AD8).
// The hooks (both before the original): RequestModel sets the size of an id with a file here to the file's sectors
// (the read then takes that many sectors from the original place - bytes overwritten next), ConvertBufferToObject
// copies the file over the buffer.
#include "game/vcs_stream_override.h"

#include "ps2_runtime.h"
#include "ps2_runtime_macros.h"

#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <fstream>
#include <iterator>
#include <map>
#include <string>
#include <system_error>
#include <vector>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif

namespace vcs::streamoverride
{
    namespace
    {
        constexpr uint32_t kRamMask = 0x01FFFFFFu;
        constexpr uint32_t kRequestModel = 0x003C7ED8u;  // CStreaming::RequestModel(streaming, id, flags)
        constexpr uint32_t kConvertBuffer = 0x003C72A8u; // CStreaming::ConvertBufferToObject(streaming, id, buffer)
        constexpr uint32_t kInfos = 200u;                // CStreaming + 200 -> the streaming infos
        constexpr uint32_t kInfoSize = 0x18u, kInfoSectors = 0x14u;
        constexpr uint32_t kSector = 2048u;
        constexpr int kA0 = 4, kA1 = 5, kA2 = 6;

        PS2Runtime::RecompiledFunction g_origRequest = nullptr;
        PS2Runtime::RecompiledFunction g_origConvert = nullptr;
        std::map<uint32_t, std::vector<uint8_t>> g_files; // id -> the file (read once at start)

        uint32_t rd32(const uint8_t *ram, uint32_t a)
        {
            uint32_t v;
            std::memcpy(&v, ram + (a & kRamMask), 4);
            return v;
        }

        void wr32(uint8_t *ram, uint32_t a, uint32_t v) { std::memcpy(ram + (a & kRamMask), &v, 4); }

        std::filesystem::path exeDir()
        {
#ifdef _WIN32
            wchar_t buffer[MAX_PATH];
            const DWORD n = GetModuleFileNameW(nullptr, buffer, MAX_PATH);
            if (n && n < MAX_PATH)
                return std::filesystem::path(buffer).parent_path();
#else
            std::error_code ec;
            const auto p = std::filesystem::read_symlink("/proc/self/exe", ec);
            if (!ec)
                return p.parent_path();
#endif
            return std::filesystem::current_path();
        }

        uint32_t sectorsOf(const std::vector<uint8_t> &file) { return static_cast<uint32_t>((file.size() + kSector - 1) / kSector); }

        // The info's size word of `id`, 0 when the streaming infos are not there yet.
        uint32_t sizeWord(const uint8_t *ram, uint32_t streaming, uint32_t id)
        {
            const uint32_t infos = rd32(ram, streaming + kInfos);
            return infos ? infos + id * kInfoSize + kInfoSectors : 0u;
        }

        PS2_GUEST_CC void requestModel(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            const uint32_t id = GPR_U32(ctx, kA1);
            if (const auto it = g_files.find(id); it != g_files.end())
                if (const uint32_t at = sizeWord(rdram, GPR_U32(ctx, kA0), id))
                {
                    const uint32_t want = sectorsOf(it->second), was = rd32(rdram, at);
                    if (was != want)
                    {
                        wr32(rdram, at, want);
                        std::fprintf(stderr, "[streamoverride] request %u: size %u -> %u sectors\n", id, was, want);
                    }
                }
            return g_origRequest(rdram, ctx, runtime);
        }

        PS2_GUEST_CC void convertBuffer(uint8_t *rdram, R5900Context *ctx, PS2Runtime *runtime)
        {
            const uint32_t id = GPR_U32(ctx, kA1);
            if (const auto it = g_files.find(id); it != g_files.end())
            {
                const uint32_t at = sizeWord(rdram, GPR_U32(ctx, kA0), id);
                const uint32_t room = at ? rd32(rdram, at) * kSector : 0u;
                const uint32_t buffer = GPR_U32(ctx, kA2) & kRamMask;
                const size_t size = it->second.size();
                if (buffer && room >= size && buffer + size <= kRamMask + 1u)
                {
                    std::memcpy(rdram + buffer, it->second.data(), size);
                    std::fprintf(stderr, "[streamoverride] loaded %u: %zu bytes at 0x%08x\n", id, size, buffer);
                }
                else
                    std::fprintf(stderr, "[streamoverride] %u not replaced: buffer 0x%08x holds %u bytes, the file %zu\n", id,
                                 buffer, room, size);
            }
            return g_origConvert(rdram, ctx, runtime);
        }
    }

    void install(PS2Runtime &runtime)
    {
        if (const char *e = std::getenv("VCS_STREAM_OVERRIDE"); e && e[0] == '0')
            return;
        const char *env = std::getenv("VCS_MODS_DIR");
        const std::filesystem::path dir = (env && *env ? std::filesystem::path(env) : exeDir() / "mods") / "stream";
        std::error_code ec;
        for (const auto &entry : std::filesystem::directory_iterator(dir, ec))
        {
            if (!entry.is_regular_file(ec))
                continue;
            const std::string stem = entry.path().stem().string();
            if (stem.empty() || stem.size() > 6 || stem.find_first_not_of("0123456789") != std::string::npos)
                continue;
            std::ifstream in(entry.path(), std::ios::binary);
            std::vector<uint8_t> data((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
            if (data.size() < 0x20)
                continue;
            const uint32_t id = static_cast<uint32_t>(std::stoul(stem));
            std::fprintf(stderr, "[streamoverride] %u <- %s (%zu bytes, %u sectors)\n", id, entry.path().filename().string().c_str(),
                         data.size(), sectorsOf(data));
            g_files[id] = std::move(data);
        }
        if (g_files.empty())
            return;
        g_origRequest = runtime.lookupFunction(kRequestModel);
        g_origConvert = runtime.lookupFunction(kConvertBuffer);
        if (!g_origRequest || !g_origConvert)
            return;
        runtime.replaceFunction(kRequestModel, &requestModel);
        runtime.replaceFunction(kConvertBuffer, &convertBuffer);
    }
}
