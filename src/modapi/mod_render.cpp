// See mod_render.h and docs/MODDING.md "Rendering". Everything here runs on the main thread: hooks are added while the
// mods register, and run inside the renderer's frame hook (RhiExecutor::runSceneHook), where the RHI device is in use.
#include "modapi/mod_render.h"

#include "modapi/vcs_mod_api.h"
#include "render/texture_replacements.h"
#include "rhi/rhi.h"
#include "runtime/gs/gs_hw.h"

#include <cstdio>
#include <cstring>
#include <memory>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <vector>

namespace vcs::modapi::render
{
    namespace
    {
        struct Hook
        {
            int point = 0;
            VcsRenderHookFn fn = nullptr;
            void *user = nullptr;
            uint32_t flags = 0;
        };
        std::vector<Hook> g_hooks;
        uint32_t g_needs = 0; // VCS_RENDER_NEEDS_* of all hooks

        // inside a hook: the renderer's device, the pass the hook has open, its markers
        rhi::Device *g_device = nullptr;
        const GSHwFrameView *g_view = nullptr; // inside a hook
        bool g_inPass = false;
        bool g_pipelineSet = false; // a pipeline of the mod's since its pass began (else the renderer's last one is bound)
        int g_markers = 0;

        // what mods made; a handle is the RHI object's address
        std::unordered_map<const void *, std::unique_ptr<rhi::Texture>> g_textures;
        std::unordered_map<const void *, std::unique_ptr<rhi::Buffer>> g_buffers;
        std::unordered_map<const void *, std::unique_ptr<rhi::Pipeline>> g_pipelines;
        std::unique_ptr<rhi::Sampler> g_samplers[2]; // VCS_RENDER_SAMPLER_POINT / _LINEAR, clamped
        std::unordered_set<std::string> g_names;     // the RHI keeps a desc's name pointer

        VcsRenderTexture *handle(rhi::Texture *t) { return reinterpret_cast<VcsRenderTexture *>(t); }
        rhi::Texture *texture(VcsRenderTexture *t) { return reinterpret_cast<rhi::Texture *>(t); }
        const char *keep(const char *name, const char *fallback) { return g_names.insert(name ? name : fallback).first->c_str(); }

        bool inHook(const char *what)
        {
            if (g_device)
                return true;
            static int reported = 0;
            if (reported++ < 8)
                std::fprintf(stderr, "[mods] %s outside a render hook - ignored\n", what);
            return false;
        }

        // the renderer's frame hook: the mods' hooks of that point, in order; what a hook leaves open is closed for it
        void frameHook(void *, const GSHwFrameView &v)
        {
            if (!v.device)
                return;
            VcsRenderFrame f = {};
            f.size = sizeof(f);
            f.backend = static_cast<int>(v.device->backend());
            f.frame = v.frame;
            f.color = handle(v.color);
            f.color_resolved = handle(v.colorResolved);
            f.depth = handle(v.depth);
            f.color_samples = v.color ? v.color->desc().samples : 0u;
            f.depth_samples = v.depth ? v.depth->desc().samples : 0u;
            f.width = v.width;
            f.height = v.height;
            f.camera_valid = v.camera ? 1 : 0;
            f.fx = v.fx;
            f.fy = v.fy;
            f.cx = v.cx;
            f.cy = v.cy;
            f.depth_a = v.depthA;
            f.depth_b = v.depthB;
            f.depth_scale = v.depthScale;
            f.fog_bias = v.fogBias;
            f.fog_scale = v.fogScale;
            f.jitter_x = v.jitterX;
            f.jitter_y = v.jitterY;
            f.prev_jitter_x = v.prevJitterX;
            f.prev_jitter_y = v.prevJitterY;
            f.reproject_valid = v.reprojectValid ? 1 : 0;
            std::memcpy(f.reproject, v.reproject, sizeof(f.reproject));
            f.velocity = handle(v.velocity);
            f.view_valid = v.viewKnown ? 1 : 0;
            std::memcpy(f.world_to_view, v.worldToView, sizeof(f.world_to_view));
            f.position_valid = v.positionKnown ? 1 : 0;
            std::memcpy(f.camera_position, v.cameraPosition, sizeof(f.camera_position));
            f.point = v.point == GSHwHookBeforeWater  ? VCS_RENDER_BEFORE_WATER
                      : v.point == GSHwHookAfterWater ? VCS_RENDER_AFTER_WATER
                                                      : VCS_RENDER_BEFORE_POST;
            std::memcpy(f.water_rect, v.waterRect, sizeof(f.water_rect));
            std::memcpy(f.water_color, v.waterColor, sizeof(f.water_color));
            g_device = v.device;
            g_view = &v;
            for (const Hook &h : g_hooks)
            {
                if (h.point != f.point)
                    continue;
                h.fn(h.user, &f);
                if (g_inPass)
                    g_device->endPass();
                g_inPass = g_pipelineSet = false;
                for (; g_markers > 0; --g_markers)
                    g_device->popMarker();
            }
            g_device = nullptr;
            g_view = nullptr;
        }

        int apiAddHook(int point, VcsRenderHookFn fn, void *user, uint32_t flags)
        {
            if ((point != VCS_RENDER_BEFORE_POST && point != VCS_RENDER_BEFORE_WATER && point != VCS_RENDER_AFTER_WATER) || !fn)
                return 0;
            g_hooks.push_back({point, fn, user, flags});
            g_needs |= flags;
            uint32_t needs = 0;
            if (g_needs & VCS_RENDER_NEEDS_DEPTH)
                needs |= GSHwFrameHookDepth;
            if (g_needs & VCS_RENDER_NEEDS_RESOLVED_COLOR)
                needs |= GSHwFrameHookResolvedColor;
            if (g_needs & VCS_RENDER_NEEDS_VELOCITY)
                needs |= GSHwFrameHookVelocity;
            if (g_needs & VCS_RENDER_NEEDS_SHADOW)
                needs |= GSHwFrameHookShadow;
            for (const Hook &h : g_hooks)
                if (h.point == VCS_RENDER_BEFORE_WATER || h.point == VCS_RENDER_AFTER_WATER)
                    needs |= GSHwFrameHookWater;
            gsHwSetFrameHook(&frameHook, nullptr, needs);
            return 1;
        }

        VcsRenderTexture *apiCreateTextureEx(uint32_t width, uint32_t height, int format, uint32_t flags, const char *name)
        {
            if (!inHook("render_create_texture") || !width || !height || width > 16384u || height > 16384u ||
                (format != VCS_RENDER_FORMAT_RGBA8 && format != VCS_RENDER_FORMAT_R32F && format != VCS_RENDER_FORMAT_RGBA16F))
                return nullptr;
            rhi::TextureDesc d;
            d.width = width;
            d.height = height;
            d.format = format == VCS_RENDER_FORMAT_R32F     ? rhi::Format::R32F
                       : format == VCS_RENDER_FORMAT_RGBA16F ? rhi::Format::RGBA16F
                                                             : rhi::Format::RGBA8;
            d.usage = rhi::UsageRenderTarget | rhi::UsageSampled | ((flags & VCS_RENDER_TEXTURE_STORAGE) ? rhi::UsageStorage : 0u);
            d.name = keep(name, "mod texture");
            std::unique_ptr<rhi::Texture> t = g_device->createTexture(d);
            if (!t)
                return nullptr;
            rhi::Texture *raw = t.get();
            g_textures[raw] = std::move(t);
            return handle(raw);
        }

        VcsRenderTexture *apiCreateTexture(uint32_t width, uint32_t height, int format, const char *name)
        {
            return apiCreateTextureEx(width, height, format, 0u, name);
        }

        void closePass()
        {
            if (g_inPass)
            {
                g_device->endPass();
                g_inPass = g_pipelineSet = false;
            }
        }

        VcsRenderTexture *apiCurrentColor()
        {
            if (!inHook("render_current_color") || !g_view || !g_view->currentColor)
                return nullptr;
            closePass();
            return handle(g_view->currentColor(g_view->currentColorCtx));
        }

        VcsRenderTexture *apiShadowMap(const float *viewToClip, uint32_t count, uint32_t size, uint32_t *drawn)
        {
            if (drawn)
                *drawn = 0;
            if (!inHook("render_shadow_map") || !g_view || !g_view->shadowMap || !viewToClip)
                return nullptr;
            closePass();
            return handle(g_view->shadowMap(g_view->currentColorCtx, viewToClip, count, size, drawn));
        }

        void *apiNative(int what, VcsRenderTexture *t)
        {
            if (!inHook("render_native"))
                return nullptr;
            closePass();
            switch (what)
            {
            case VCS_RENDER_NATIVE_DEVICE: return g_device->native(rhi::Device::Native::Device);
            case VCS_RENDER_NATIVE_CONTEXT: return g_device->native(rhi::Device::Native::Context);
            case VCS_RENDER_NATIVE_TEXTURE: return t ? g_device->native(rhi::Device::Native::Texture, texture(t)) : nullptr;
            default: return nullptr;
            }
        }

        void apiDestroyTexture(VcsRenderTexture *t)
        {
            if (t && inHook("render_destroy_texture"))
                g_textures.erase(t); // only the mods' own (the frame's are the renderer's)
        }

        VcsRenderBuffer *apiCreateConstants(uint32_t size, const char *name)
        {
            if (!inHook("render_create_constants") || !size || size > 65536u)
                return nullptr;
            std::unique_ptr<rhi::Buffer> b =
                g_device->createBuffer({(size + 15u) & ~15u, rhi::BufferUsage::Constant, true, keep(name, "mod constants")});
            if (!b)
                return nullptr;
            rhi::Buffer *raw = b.get();
            g_buffers[raw] = std::move(b);
            return reinterpret_cast<VcsRenderBuffer *>(raw);
        }

        void apiUpdateConstants(VcsRenderBuffer *b, const void *data, uint32_t size)
        {
            auto it = b ? g_buffers.find(b) : g_buffers.end();
            if (inHook("render_update_constants") && it != g_buffers.end() && data && size <= it->second->desc().size)
                g_device->updateBuffer(*it->second, data, size);
        }

        void apiDestroyConstants(VcsRenderBuffer *b)
        {
            if (b && inHook("render_destroy_constants"))
                g_buffers.erase(b);
        }

        VcsRenderPipeline *apiCreatePipeline(const VcsRenderPipelineDesc *in)
        {
            if (!inHook("render_create_pipeline") || !in || in->size < sizeof(VcsRenderPipelineDesc) || !in->vertex_code ||
                !in->vertex_size || !in->pixel_code || !in->pixel_size)
                return nullptr;
            rhi::PipelineDesc d;
            d.vertex = {in->vertex_code, in->vertex_size}; // a mod's code stays loaded: the bytes outlive the pipeline
            d.pixel = {in->pixel_code, in->pixel_size};
            d.topology = rhi::Topology::Triangles;
            d.blend.writeMask = static_cast<uint8_t>(in->write_mask & 0xFu);
            switch (in->blend)
            {
            case VCS_RENDER_BLEND_MULTIPLY:
                d.blend.enable = true;
                d.blend.srcColor = rhi::BlendFactor::Zero;
                d.blend.dstColor = rhi::BlendFactor::SrcAlpha;
                break;
            case VCS_RENDER_BLEND_ALPHA:
                d.blend.enable = true;
                d.blend.srcColor = rhi::BlendFactor::SrcAlpha;
                d.blend.dstColor = rhi::BlendFactor::InvSrcAlpha;
                break;
            case VCS_RENDER_BLEND_ADD:
                d.blend.enable = true;
                d.blend.srcColor = rhi::BlendFactor::One;
                d.blend.dstColor = rhi::BlendFactor::One;
                break;
            default:
                break;
            }
            d.multisampledTextures = in->multisampled_textures;
            d.name = keep(in->name, "mod pipeline");
            std::unique_ptr<rhi::Pipeline> p = g_device->createPipeline(d);
            if (!p)
                return nullptr;
            rhi::Pipeline *raw = p.get();
            g_pipelines[raw] = std::move(p);
            return reinterpret_cast<VcsRenderPipeline *>(raw);
        }

        void apiDestroyPipeline(VcsRenderPipeline *p)
        {
            if (p && inHook("render_destroy_pipeline"))
                g_pipelines.erase(p);
        }

        void apiBeginPass(VcsRenderTexture *target)
        {
            rhi::Texture *t = texture(target);
            if (!inHook("render_begin_pass") || !t || t->desc().format == rhi::Format::D32F)
                return;
            if (g_inPass)
                g_device->endPass();
            rhi::PassDesc p;
            p.color = t;
            g_device->beginPass(p);
            g_inPass = true;
            g_pipelineSet = false;
        }

        void apiSetViewport(int x, int y, int width, int height)
        {
            if (!inHook("render_set_viewport") || !g_inPass || width <= 0 || height <= 0)
                return;
            g_device->setViewport(static_cast<float>(x), static_cast<float>(y), static_cast<float>(width), static_cast<float>(height));
            g_device->setScissor(x, y, width, height);
        }

        void apiSetPipeline(VcsRenderPipeline *p)
        {
            auto it = p ? g_pipelines.find(p) : g_pipelines.end();
            if (!inHook("render_set_pipeline") || it == g_pipelines.end())
                return;
            g_device->setPipeline(*it->second);
            g_pipelineSet = true;
        }

        void apiSetTexture(uint32_t slot, VcsRenderTexture *t, int sampler)
        {
            if (!inHook("render_set_texture") || slot >= 8u)
                return;
            std::unique_ptr<rhi::Sampler> &s = g_samplers[sampler == VCS_RENDER_SAMPLER_LINEAR ? 1 : 0];
            if (!s)
                s = g_device->createSampler({sampler == VCS_RENDER_SAMPLER_LINEAR ? rhi::Filter::Linear : rhi::Filter::Nearest,
                                             rhi::Wrap::Clamp, rhi::Wrap::Clamp});
            g_device->setTexture(slot, texture(t), s.get());
        }

        void apiSetConstants(uint32_t slot, VcsRenderBuffer *b)
        {
            auto it = b ? g_buffers.find(b) : g_buffers.end();
            if (inHook("render_set_constants") && it != g_buffers.end() && slot < 8u)
                g_device->setConstants(slot, *it->second);
        }

        void apiDraw(uint32_t vertexCount)
        {
            if (inHook("render_draw") && g_inPass && g_pipelineSet && vertexCount)
                g_device->draw(vertexCount);
        }

        void apiEndPass()
        {
            if (inHook("render_end_pass") && g_inPass)
            {
                g_device->endPass();
                g_inPass = g_pipelineSet = false;
            }
        }

        void apiPushMarker(const char *name)
        {
            if (!inHook("render_push_marker"))
                return;
            g_device->pushMarker(name ? name : "mod");
            ++g_markers;
        }

        void apiPopMarker()
        {
            if (inHook("render_pop_marker") && g_markers > 0)
            {
                g_device->popMarker();
                --g_markers;
            }
        }
    }

    void fillApi(VcsModApi &a)
    {
        a.add_render_hook = &apiAddHook;
        a.render_create_texture = &apiCreateTexture;
        a.render_destroy_texture = &apiDestroyTexture;
        a.render_create_constants = &apiCreateConstants;
        a.render_update_constants = &apiUpdateConstants;
        a.render_destroy_constants = &apiDestroyConstants;
        a.render_create_pipeline = &apiCreatePipeline;
        a.render_destroy_pipeline = &apiDestroyPipeline;
        a.render_begin_pass = &apiBeginPass;
        a.render_set_viewport = &apiSetViewport;
        a.render_set_pipeline = &apiSetPipeline;
        a.render_set_texture = &apiSetTexture;
        a.render_set_constants = &apiSetConstants;
        a.render_draw = &apiDraw;
        a.render_end_pass = &apiEndPass;
        a.render_push_marker = &apiPushMarker;
        a.render_pop_marker = &apiPopMarker;
        a.render_set_jitter = [](uint32_t phases) { gsHwSetJitter(phases); };
        a.render_set_wind = [](float x, float y, float strength) { gsHwSetWind(x, y, strength); };
        a.render_set_wind_list = [](const char *path) { return ::render::setWindList(path) ? 1 : 0; };
        a.render_current_color = &apiCurrentColor;
        a.render_native = &apiNative;
        a.render_create_texture_ex = &apiCreateTextureEx;
        a.render_shadow_map = &apiShadowMap;
    }
}
