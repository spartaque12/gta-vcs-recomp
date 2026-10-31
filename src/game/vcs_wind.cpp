// Vegetation wind sway: the noise field the renderer sways the wind list's textures with (gs_draw.hlsl vs_world).
#include "game/vcs_wind.h"

#include "runtime/gs/gs_hw.h"
#include "settings/settings.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>

namespace vcs::wind
{
    namespace
    {
        constexpr uint32_t kTimeMs = 0x4CD104; // CTimer::m_snTimeInMilliseconds (stops while paused; game-internals.md 4)
        constexpr uint32_t kWind = 0x4CD2A4;   // CWeather::Wind: 0.25 sunny, 0.7 cloudy, 1 rain, 2 hurricane (12j)

        std::atomic<bool> g_enabled{false};
        std::atomic<int> g_strength{100};
        uint32_t g_lastMs = 0;
        double g_x = 0.0, g_y = 0.0; // the field's position (metres), kept in a 4 km period
        float g_wind = 0.0f;         // the game's wind, smoothed
        bool g_on = false;
    }

    void registerSettings()
    {
        using namespace settings;
        Spec s;
        s.key = "graphics.wind_sway";
        s.page = "Graphics";
        s.section = "Image quality";
        s.label = "Vegetation wind";
        s.help = "The converted palms' and trees' leaves (tools/veg_convert.py) sway in the wind, as with SkyGfx Extended's wind "
                 "for San Andreas; stronger in storms. The PS2's own models stay still.";
        s.type = Type::Toggle;
        s.defaultValue = 0;
        s.env = "VCS_WIND";
        s.onChange = [](int v) { g_enabled = v != 0; };
        add(s);

        s = {};
        s.key = "graphics.wind_strength";
        s.page = "Graphics";
        s.section = "Image quality";
        s.label = "Vegetation wind strength";
        s.help = "How far the leaves move (100 %: 6 m from the top of the trunk, about 15 cm in a calm, 45 cm in the "
                 "rain, 75 cm in a hurricane; longer fronds more). Trunks stay still.";
        s.type = Type::Integer;
        s.min = 0;
        s.max = 300;
        s.format = "%d %%";
        s.defaultValue = 100;
        s.env = "VCS_WIND_STRENGTH";
        s.onChange = [](int v) { g_strength = v; };
        add(s);
    }

    void onGameFrame(const uint8_t *rdram)
    {
        if (!g_enabled.load(std::memory_order_relaxed))
        {
            if (g_on)
                gsHwSetWind(0.0f, 0.0f, 0.0f);
            g_on = false;
            return;
        }
        uint32_t ms;
        float wind;
        std::memcpy(&ms, rdram + kTimeMs, 4);
        std::memcpy(&wind, rdram + kWind, 4);
        if (!std::isfinite(wind))
            wind = 0.0f;
        wind = std::clamp(wind, 0.0f, 2.0f);
        // the game's clock: still while paused; a load or a jump back starts the field from where it is
        const uint32_t step = ms - g_lastMs;
        g_lastMs = ms;
        const double dt = (g_on && step < 1000u) ? step / 1000.0 : 0.0;
        g_wind = g_on ? g_wind + (wind - g_wind) * float(std::min(dt * 0.5, 1.0)) : wind;
        g_on = true;
        // the field drifts with the wind (a slowly turning direction); its 1 m cells pass at 0.6 - 3 m/s
        const double t = ms / 1000.0, angle = 0.7 + 0.35 * std::sin(t * 0.013);
        const double speed = 0.6 + 1.2 * g_wind;
        g_x = std::fmod(g_x + std::cos(angle) * speed * dt, 4096.0);
        g_y = std::fmod(g_y + std::sin(angle) * speed * dt, 4096.0);
        const float strength = (0.3f + 0.6f * g_wind) * g_strength.load(std::memory_order_relaxed) / 100.0f;
        gsHwSetWind(float(g_x), float(g_y), strength);
    }
}
