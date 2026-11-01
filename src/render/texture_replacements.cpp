#include "render/texture_replacements.h"

#define XXH_INLINE_ALL
#include "../../third_party/xxhash/xxhash.h"
#define STB_IMAGE_IMPLEMENTATION
#define STBI_ONLY_PNG
#define STBI_NO_STDIO
#define STBI_MAX_DIMENSIONS 8192
#include "../../third_party/stb/stb_image.h"

#include <algorithm>
#include <atomic>
#include <charconv>
#include <cctype>
#include <condition_variable>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <deque>
#include <fstream>
#include <mutex>
#include <string>
#include <thread>
#include <unordered_map>
#include <unordered_set>

namespace render
{
    uint64_t textureHash(const void *data, size_t bytes) { return XXH3_64bits(data, bytes); }

    namespace
    {
        struct Name
        {
            uint64_t pixels = 0, palette = 0;
            uint32_t bits = 0;
            bool operator==(const Name &) const = default;
        };
        struct NameHash
        {
            size_t operator()(const Name &n) const { return size_t(n.pixels ^ (n.palette * 31) ^ n.bits); }
        };
        bool parseName(const std::string &stem, Name &n)
        {
            // Full-texture base images; reject region/mip filenames instead of accidentally aliasing them.
            const size_t a = stem.find('-'), b = a == stem.npos ? a : stem.find('-', a + 1);
            auto hex = [](std::string_view s, auto &v) {
                if (s.empty()) return false;
                const auto r = std::from_chars(s.data(), s.data() + s.size(), v, 16);
                return r.ec == std::errc{} && r.ptr == s.data() + s.size();
            };
            if (a == stem.npos || !hex(std::string_view(stem).substr(0, a), n.pixels)) return false;
            if (b != stem.npos && !hex(std::string_view(stem).substr(a + 1, b - a - 1), n.palette)) return false;
            if (!hex(std::string_view(stem).substr((b == stem.npos ? a : b) + 1), n.bits)) return false;
            n.bits &= ~(1u << 14); // old PCSX2 TCC flag; modern PCSX2 ignores it too
            return true;
        }
        size_t memoryBudget()
        {
            const char *e = std::getenv("VCS_TEXTURE_CACHE_MB");
            return size_t(e ? std::clamp(std::atoi(e), 64, 4096) : 512) * 1024 * 1024;
        }
        std::shared_ptr<ReplacementImage> load(const std::filesystem::path &path, uint32_t id)
        {
            std::ifstream f(path, std::ios::binary | std::ios::ate);
            const auto bytes = f ? f.tellg() : std::streampos(-1);
            if (bytes <= 0 || bytes > 128 * 1024 * 1024) return {};
            std::vector<uint8_t> encoded(static_cast<size_t>(bytes));
            f.seekg(0);
            if (!f.read(reinterpret_cast<char *>(encoded.data()), encoded.size())) return {};
            int w = 0, h = 0, channels = 0;
            if (!stbi_info_from_memory(encoded.data(), int(encoded.size()), &w, &h, &channels) ||
                w <= 0 || h <= 0 || w > 8192 || h > 8192 || uint64_t(w) * h > 64 * 1024 * 1024) return {};
            auto *rgba = stbi_load_from_memory(encoded.data(), int(encoded.size()), &w, &h, &channels, 4);
            if (!rgba) return {};
            auto image = std::make_shared<ReplacementImage>();
            image->id = id;
            image->width = uint32_t(w);
            image->height = uint32_t(h);
            image->pixels.resize(size_t(w) * h);
            std::memcpy(image->pixels.data(), rgba, image->pixels.size() * 4);
            stbi_image_free(rgba);
            return image;
        }
        // An RGBA PNG with stored (uncompressed) deflate blocks: no encoder library for a diagnostic
        bool writePng(const std::filesystem::path &path, uint32_t w, uint32_t h, const uint32_t *rgba)
        {
            static uint32_t table[256];
            if (!table[1])
                for (uint32_t i = 0; i < 256; ++i)
                {
                    uint32_t c = i;
                    for (int k = 0; k < 8; ++k) c = c & 1 ? 0xEDB88320u ^ (c >> 1) : c >> 1;
                    table[i] = c;
                }
            std::vector<uint8_t> raw;
            raw.reserve(size_t(h) * (w * 4 + 1));
            for (uint32_t y = 0; y < h; ++y)
            {
                raw.push_back(0);
                const auto *row = reinterpret_cast<const uint8_t *>(rgba + size_t(y) * w);
                raw.insert(raw.end(), row, row + w * 4);
            }
            std::vector<uint8_t> z{0x78, 0x01};
            for (size_t o = 0; o == 0 || o < raw.size(); o += 65535)
            {
                const size_t n = std::min<size_t>(65535, raw.size() - o);
                z.push_back(o + n >= raw.size() ? 1 : 0);
                z.push_back(uint8_t(n)); z.push_back(uint8_t(n >> 8));
                z.push_back(uint8_t(~n)); z.push_back(uint8_t(~n >> 8));
                z.insert(z.end(), raw.begin() + o, raw.begin() + o + n);
            }
            uint32_t a = 1, b = 0;
            for (uint8_t c : raw) { a = (a + c) % 65521; b = (b + a) % 65521; }
            for (int s = 24; s >= 0; s -= 8) z.push_back(uint8_t(((b << 16) | a) >> s));
            std::vector<uint8_t> png{0x89, 'P', 'N', 'G', '\r', '\n', 0x1A, '\n'};
            auto chunk = [&](const char *type, const std::vector<uint8_t> &data) {
                for (int s = 24; s >= 0; s -= 8) png.push_back(uint8_t(data.size() >> s));
                const size_t start = png.size();
                png.insert(png.end(), type, type + 4);
                png.insert(png.end(), data.begin(), data.end());
                uint32_t crc = 0xFFFFFFFFu;
                for (size_t i = start; i < png.size(); ++i) crc = table[(crc ^ png[i]) & 0xFF] ^ (crc >> 8);
                crc = ~crc;
                for (int s = 24; s >= 0; s -= 8) png.push_back(uint8_t(crc >> s));
            };
            std::vector<uint8_t> ihdr;
            for (uint32_t v : {w, h})
                for (int s = 24; s >= 0; s -= 8) ihdr.push_back(uint8_t(v >> s));
            ihdr.insert(ihdr.end(), {8, 6, 0, 0, 0});
            chunk("IHDR", ihdr);
            chunk("IDAT", z);
            chunk("IEND", {});
            std::ofstream f(path, std::ios::binary);
            return f.write(reinterpret_cast<const char *>(png.data()), png.size()).good();
        }
    }

    struct TextureReplacements::Impl
    {
        struct File { std::filesystem::path path; bool pending = false, failed = false, matched = false; };
        std::vector<File> files{1}; // id 0 = no match
        std::unordered_map<Name, uint32_t, NameHash> names;
        std::unordered_set<uint32_t> shapes;
        size_t gpuBudget = memoryBudget(), readyBytes = 0;
        std::mutex mutex;
        std::condition_variable cv;
        std::deque<uint32_t> queue;
        std::vector<std::shared_ptr<const ReplacementImage>> ready;
        std::thread worker;
        bool stopping = false;
        uint32_t matched = 0, loaded = 0;
        std::filesystem::path dumpDir;
        std::unordered_set<std::string> dumped;
        std::unordered_map<Name, WindModel, NameHash> wind;
        std::unordered_set<uint32_t> windShapes;

        void run()
        {
            for (;;)
            {
                uint32_t id;
                {
                    std::unique_lock lock(mutex);
                    cv.wait(lock, [&] { return stopping || !queue.empty(); });
                    if (stopping) return;
                    id = queue.front(); queue.pop_front();
                }
                auto image = load(files[id].path, id);
                std::unique_lock lock(mutex);
                if (!image)
                {
                    files[id].failed = true;
                    files[id].pending = false;
                    std::fprintf(stderr, "[textures] failed to load %s; keeping original\n", files[id].path.string().c_str());
                    continue;
                }
                // Bound decoded images waiting for the GS stage. One large image may exceed 128 MiB on its own.
                const size_t bytes = image->pixels.size() * 4;
                cv.wait(lock, [&] { return stopping || ready.empty() || readyBytes + bytes <= 128 * 1024 * 1024; });
                if (stopping) return;
                readyBytes += bytes;
                ++loaded;
                std::fprintf(stderr, "[textures] loaded %s (%ux%u, %.1f MiB)\n", files[id].path.filename().string().c_str(),
                             image->width, image->height, bytes / 1048576.0);
                ready.push_back(std::move(image));
            }
        }
    };

    namespace
    {
        std::string g_windList;            // setWindList (a mod's VcsModRegister: the main thread, before the renderer)
        std::atomic<bool> g_started{false}; // a TextureReplacements was made: the list was read
    }

    bool setWindList(const char *path)
    {
        if (g_started.load() || !path || !*path)
            return false;
        std::ifstream in(std::filesystem::path(std::u8string_view(reinterpret_cast<const char8_t *>(path))));
        if (!in)
            return false;
        g_windList = path;
        return true;
    }

    TextureReplacements::TextureReplacements() : m(std::make_unique<Impl>())
    {
        g_started = true;
        if (const char *dump = std::getenv("VCS_TEXTURE_DUMP"); dump && *dump)
        {
            m->dumpDir = std::filesystem::path(std::u8string_view(reinterpret_cast<const char8_t *>(dump)));
            std::error_code ec;
            std::filesystem::create_directories(m->dumpDir, ec);
            std::fprintf(stderr, "[textures] dumping hashed textures to %s\n", m->dumpDir.string().c_str());
        }
        const char *env = std::getenv("VCS_WIND_LIST");
        if (const char *list = env && *env ? env : g_windList.empty() ? nullptr : g_windList.c_str())
        {
            std::ifstream in(std::filesystem::path(std::u8string_view(reinterpret_cast<const char8_t *>(list))));
            std::string line;
            while (std::getline(in, line))
            {
                char stem[96];
                WindModel w;
                float height = 0.0f;
                Name n;
                if (std::sscanf(line.c_str(), "%95s %f %f %f %f %f", stem, &w.metresPerUnit[0], &w.metresPerUnit[1],
                                &w.metresPerUnit[2], &w.footZ, &height) != 6 || !parseName(stem, n) || height <= 0.0f ||
                    !(w.metresPerUnit[0] > 0.0f && w.metresPerUnit[1] > 0.0f && w.metresPerUnit[2] > 0.0f))
                    continue;
                w.invHeight = 1.0f / height;
                m->wind[n] = w;
                m->windShapes.insert(n.bits & 0x3FFFu);
            }
            std::fprintf(stderr, "[textures] wind list %s: %zu textures\n", list, m->wind.size());
        }
        const char *enabled = std::getenv("VCS_TEXTURE_REPLACEMENTS");
        if (!enabled || enabled[0] != '1') return;
        const char *dir = std::getenv("VCS_TEXTURE_PACK");
        if (!dir || !*dir)
        {
            std::fprintf(stderr, "[textures] no pack directory configured; keeping originals\n");
            return;
        }
        const auto *utf8 = reinterpret_cast<const char8_t *>(dir);
        auto root = std::filesystem::path(std::u8string_view(utf8));
        std::error_code ec;
        if (std::filesystem::is_directory(root / "replacements", ec)) root /= "replacements";
        std::vector<std::filesystem::path> paths;
        for (std::filesystem::recursive_directory_iterator it(root, std::filesystem::directory_options::skip_permission_denied, ec), end;
             !ec && it != end; it.increment(ec))
        {
            if (it->is_regular_file(ec)) paths.push_back(it->path());
        }
        std::sort(paths.begin(), paths.end()); // deterministic duplicate handling
        uint32_t rejected = 0, duplicates = 0;
        for (const auto &path : paths)
        {
            auto ext = path.extension().string();
            std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return char(std::tolower(c)); });
            if (ext != ".png") continue;
            Name n;
            if (!parseName(path.stem().string(), n)) { ++rejected; continue; }
            if (!m->names.emplace(n, uint32_t(m->files.size())).second) { ++duplicates; continue; }
            m->files.push_back({path});
            m->shapes.insert(n.bits & 0x3FFFu);
        }
        std::fprintf(stderr, "[textures] indexed %zu PNG replacements in %s (%u unsupported names, %u duplicates); cache %zu MiB%s\n",
                     m->names.size(), root.string().c_str(), rejected, duplicates, m->gpuBudget >> 20, ec ? "; directory scan failed" : "");
        if (!m->names.empty()) m->worker = std::thread([this] { m->run(); });
    }
    TextureReplacements::~TextureReplacements()
    {
        { std::lock_guard lock(m->mutex); m->stopping = true; }
        m->cv.notify_all();
        if (m->worker.joinable()) m->worker.join();
        if (!m->names.empty())
            std::fprintf(stderr, "[textures] summary: %u/%zu pack files matched, %u image loads\n", m->matched, m->names.size(), m->loaded);
    }
    bool TextureReplacements::candidate(uint32_t bits) const
    {
        return !m->dumpDir.empty() || m->shapes.contains(bits & 0x3FFFu) || m->windShapes.contains(bits & 0x3FFFu);
    }
    const WindModel *TextureReplacements::wind(uint64_t pixels, uint64_t palette, uint32_t bits) const
    {
        if (m->wind.empty()) return nullptr;
        const auto it = m->wind.find({pixels, palette, bits});
        return it == m->wind.end() ? nullptr : &it->second;
    }
    bool TextureReplacements::dumping() const { return !m->dumpDir.empty(); }
    void TextureReplacements::dump(uint64_t pixels, uint64_t palette, uint32_t bits, uint32_t width, uint32_t height,
                                   const uint32_t *rgba)
    {
        char name[64];
        if (palette)
            std::snprintf(name, sizeof(name), "%016llx-%016llx-%08x", (unsigned long long)pixels, (unsigned long long)palette, bits);
        else
            std::snprintf(name, sizeof(name), "%016llx-%08x", (unsigned long long)pixels, bits);
        if (m->dumpDir.empty() || !m->dumped.insert(name).second) return;
        if (!writePng(m->dumpDir / (std::string(name) + ".png"), width, height, rgba))
            std::fprintf(stderr, "[textures] could not write dump %s\n", name);
    }
    uint32_t TextureReplacements::find(uint64_t pixels, uint64_t palette, uint32_t bits)
    {
        // Opt-in diagnostic: exact names computed by the renderer (never texture data).
        static const bool trace = std::getenv("VCS_TEXTURE_TRACE") != nullptr;
        if (trace)
            std::fprintf(stderr, "[textures] lookup %llx-%llx-%08x\n", (unsigned long long)pixels,
                         (unsigned long long)palette, bits);
        const auto it = m->names.find({pixels, palette, bits});
        if (it == m->names.end()) return 0;
        auto &file = m->files[it->second];
        if (!file.matched)
        {
            file.matched = true; ++m->matched;
            std::fprintf(stderr, "[textures] matched %s (%u/%zu)\n", file.path.filename().string().c_str(), m->matched, m->names.size());
        }
        return it->second;
    }
    void TextureReplacements::request(uint32_t id)
    {
        std::lock_guard lock(m->mutex);
        auto &file = m->files.at(id);
        if (file.pending || file.failed) return;
        file.pending = true;
        m->queue.push_back(id);
        m->cv.notify_all();
    }
    std::vector<std::shared_ptr<const ReplacementImage>> TextureReplacements::takeReady()
    {
        std::vector<std::shared_ptr<const ReplacementImage>> result;
        if (!m->worker.joinable()) return result;
        {
            std::lock_guard lock(m->mutex);
            result.swap(m->ready);
            m->readyBytes = 0;
            for (const auto &image : result) m->files[image->id].pending = false;
        }
        m->cv.notify_all();
        return result;
    }
    size_t TextureReplacements::budget() const { return m->gpuBudget; }
}
