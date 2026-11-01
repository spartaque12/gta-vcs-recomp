// See mod_present.h. Main thread only: hooks are added while the mods register (or later, from a setting), and run from
// present::present() (src/render/presenter.cpp), after the window's picture and Dear ImGui are drawn and before the
// swapchain shows them.
#include "modapi/mod_present.h"

#include "game/vcs_framerate.h"
#include "modapi/vcs_mod_api.h"
#include "render/presenter.h"
#include "rhi/rhi.h"
#include "runtime/gs/gs_hw.h"

#include <cstdio>
#include <vector>

namespace vcs::modapi::present_hooks
{
    namespace
    {
        struct Hook
        {
            VcsPresentHookFn fn = nullptr;
            void *user = nullptr;
        };
        std::vector<Hook> g_hooks;
        bool g_inHook = false;

        void *nativeTexture(rhi::Device &d, rhi::Texture *t) { return t ? d.native(rhi::Device::Native::Texture, t) : nullptr; }

        void beforePresent(void *)
        {
            rhi::Device *d = present::device();
            if (!d || g_hooks.empty())
                return;
            VcsPresentFrame f = {};
            f.size = sizeof(f);
            f.backend = static_cast<int>(d->backend());
            f.device = d->native(rhi::Device::Native::Device);
            f.context = d->native(rhi::Device::Native::Context);
            d->backbufferSize(f.window_width, f.window_height);
            GSHwLayers layers;
            if (gsHwSplitLayers(layers))
            {
                f.scene = nativeTexture(*d, layers.scene);
                f.hud_black = nativeTexture(*d, layers.hudBlack);
                f.hud_white = nativeTexture(*d, layers.hudWhite);
                f.layer_width = layers.width;
                f.layer_height = layers.height;
                f.has_3d = layers.has3d ? 1 : 0;
                f.has_hud = layers.hasHud ? 1 : 0;
                f.layer_serial = layers.serial;
            }
            f.input_ns = gsHwShownInputNs();
            g_inHook = true;
            for (const Hook &h : g_hooks)
                h.fn(h.user, &f);
            g_inHook = false;
        }

        int apiAddHook(VcsPresentHookFn fn, void *user)
        {
            if (!fn)
                return 0;
            g_hooks.push_back({fn, user});
            present::setBeforePresent(&beforePresent, nullptr);
            return 1;
        }

        void *apiWindowCopy(uint32_t width, uint32_t height)
        {
            rhi::Device *d = present::device();
            if (!g_inHook || !d)
            {
                static int reported = 0;
                if (reported++ < 8)
                    std::fprintf(stderr, "[mods] present_window_copy outside a present hook - ignored\n");
                return nullptr;
            }
            return nativeTexture(*d, present::windowCopy(static_cast<int>(width), static_cast<int>(height)));
        }
    }

    void fillApi(VcsModApi &a)
    {
        a.add_present_hook = &apiAddHook;
        a.render_set_split_layers = [](int on) { gsHwSetSplitLayers(on != 0); };
        a.present_window_copy = &apiWindowCopy;
        a.vr_set_pacing = [](float hz) {
            vcs::setFrameRateOverride(hz > 0.0f ? hz : 0.0);
            present::setPresentModeOverride(hz > 0.0f ? 0 : -1); // Immediate while the headset paces
        };
        a.render_set_output_size = [](uint32_t w, uint32_t h) { gsHwSetOutputOverride(w, h); };
    }
}
