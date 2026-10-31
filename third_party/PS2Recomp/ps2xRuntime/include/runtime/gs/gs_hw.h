// [gta-recomp] Hardware GS renderer (D3D11 through the RHI, src/rhi; was OpenGL 3.3).
//
// The game thread records: GSHwBackend implements GSRasterBackend, keeps VRAM, transfers and CLUTs in an
// embedded GSCpuBackend (everything but drawing), turns primitives into batched draws, decodes textures
// (cached) and hands each frame's command list over at VBlank. The main thread executes the lists on the
// window's RHI device (render targets, depth, blending, alpha test, fog) and shows the display circuit.
//
// PS2X_GS=hw selects it. PS2X_HW_SCALE=<1..8> renders at that multiple of the PS2 resolution.
#pragma once

#include <string>

#include "runtime/gs/gs_backend.h"

#include <cstdint>
#include <memory>

namespace rhi
{
    class Device;
    class Texture;
}

struct GSHwOptions
{
    uint32_t scale = 1;
    bool nativeFrame = false; // [gta-recomp] PS2X_HW_SCALE=0: the picture's targets at the window's resolution
    uint32_t msaa = 1;        // [gta-recomp] PS2X_HW_MSAA: samples for the picture's targets (1 = off)
    uint32_t anisotropy = 0;  // [gta-recomp] PS2X_HW_ANISO: anisotropic filtering of the game's textures (0 = off)
    static GSHwOptions fromEnvironment();
};

// Main thread side.
class GSHwPresenter
{
public:
    virtual ~GSHwPresenter() = default;
    // Main thread, with the window's device: run every frame recorded since the last call. Returns the texture
    // holding the newest displayed picture (alpha = 1, row 0 at the top; owned by the renderer, valid until the next
    // call) and its size; false until a first frame has been displayed.
    virtual bool executeAndGetDisplay(rhi::Device &device, rhi::Texture *&texture, uint32_t &width, uint32_t &height) = 0;
    // [gta-recomp] Whether the displayed frames draw 3D (depth-tested or native draws), with some hysteresis: frames that
    // are only 2D (loading screens, menus) are presented at 4:3 in widescreen.
    virtual bool showing3d() const = 0;
    // [gta-recomp] One line about the frames composed last (draws, native draws, 3D, displayed buffer): diagnostics.
    virtual std::string lastFrameInfo() const = 0;
};

class GSHwBackendHandle : public GSRasterBackend
{
public:
    // Game thread, at VBlankStart: close the frame's command list (privRegs: PMODE..BGCOLOR in GS order).
    virtual void endFrame(const uint64_t (&privRegs)[15]) = 0;
    virtual GSHwPresenter &presenter() = 0;
};

std::unique_ptr<GSHwBackendHandle> makeHwRasterBackend(const GSHwOptions &options);

// [gta-recomp] Widescreen (docs/SETTINGS_MENU_WIDESCREEN.md): 2D draws (no depth test, into a 640-wide target, not
// covering the whole width) are squeezed horizontally by `factor` around the middle, so the HUD keeps its 4:3 shape in a
// wider picture. 1 = off. Any thread.
void gsHwSetHudSqueeze(float factor);

// [gta-recomp] Per-element HUD placement in widescreen: the game names a 2D primitive's anchor from its vertices'
// positions (x, y pairs in pixels, XYOFFSET removed). Squeezed (as above) towards the anchor: the left edge, the right
// edge or the middle; Stretch keeps the 640-wide position (full-screen draws). None = the squeeze heuristic alone.
// Called on the thread that processes GS packets; set it from any thread. nullptr = off.
enum : uint8_t
{
    GSHwAnchorNone = 0,
    GSHwAnchorCentre,
    GSHwAnchorLeft,
    GSHwAnchorRight,
    GSHwAnchorStretch,
    // [gta-recomp] or'ed in: the primitive is the game's menu. A frame with menu primitives and no 3D is shown at 4:3 at
    // once (the pause menu), not after the half-second the 3D history takes.
    GSHwAnchorMenu = 0x80,
};
using GSHwAnchorFn = uint8_t (*)(const float *xy, uint32_t count);
void gsHwSetHudClassifier(GSHwAnchorFn fn);

// [gta-recomp] Native HUD layer: the primitives the classifier names are kept out of the PS2 frame buffer and drawn over
// the displayed picture at the output size (gsHwSetOutputSize) - sharp at any window size, in its aspect. The displayed
// buffer's latest HUD is drawn; a new scene in that buffer starts the next one. Any thread.
void gsHwSetHudLayer(bool on);
// [gta-recomp] Split layers (the VR mod, docs/VR_PLAN.md M0): while on, each composed display also keeps the shown picture
// without the HUD and the native HUD layer alone, drawn over black and over white (coverage = 1 - (white - black), colour
// premultiplied = black), all RGBA8 at the display's output size. Any thread.
struct GSHwLayers
{
    rhi::Texture *scene = nullptr, *hudBlack = nullptr, *hudWhite = nullptr;
    uint32_t width = 0, height = 0;
    bool has3d = false;  // the picture shows 3D (the recent frames drew it: not a menu / loading screen)
    bool hasHud = false; // a HUD layer was drawn (else the HUD textures are plain black / white)
    uint64_t serial = 0; // counts the composed frames that had layers
};
void gsHwSetSplitLayers(bool on);
// The last composed display's layers (main thread; valid until the next one). False when it had none (a picture from CPU
// VRAM, a black frame, splitting off).
bool gsHwSplitLayers(GSHwLayers &out);
// [gta-recomp] Widescreen: how much wider than 4:3 the game's 640-wide frame is shown (display aspect / (4/3)); the
// native post effects widen their buffers by it so blur and warp keep their 4:3 proportions on screen. Any thread.
void gsHwSetAspectWidening(float widening);
// [gta-recomp] Frame pacing between the game and the window. Off (the PS2's timing): the game may run 3 frames ahead and
// each host frame renders every queued frame, showing the last - game time keeps its pace when the GPU falls behind.
// On (frame-rate independent timing, where game time follows the clock anyway): one frame queued, one rendered and
// shown per host frame - a GPU-bound machine shows every frame it renders (the HD 520: 76 shown fps instead of 30 at the
// same GPU load; docs/PERFORMANCE.md 17) with the least latency. Any thread.
void gsHwSetShowEveryFrame(bool on);
// [gta-recomp] The input snapshot time (PSPadBackend::lastInputNs) of the frame the last host frame showed: for the
// input-to-screen delay (rhi::Device::setFrameInputTime). Main thread.
int64_t gsHwShownInputNs();
// [gta-recomp] How long a frame takes from its input snapshot to ready for the window (game, render worker, GS stage):
// the 95th percentile of recent frames, 0 before any (the frame lead, docs/PERFORMANCE.md 19). Any thread.
int64_t gsHwFrameBuildNs();
// [gta-recomp] Native frame (GSHwOptions::nativeFrame): the size the picture's own targets are drawn at - the window's
// letterboxed area for 3D frames' aspect. 0 = the integer scale. Any thread.
void gsHwSetFrameSize(uint32_t width, uint32_t height);
// [gta-recomp] Alpha dual pass (skygfx's): alpha-blended draws with a low alpha-test reference and depth writes drawn
// twice - texels at alpha >= 0x40 (of 0x80) with depth writes, the rest blended without. Any thread; takes effect at once.
void gsHwSetAlphaDualPass(bool on);
// [gta-recomp] The size the picture is shown at (the window's letterboxed area); 0 = the render targets' size.
void gsHwSetOutputSize(uint32_t width, uint32_t height);
// [gta-recomp] Render targets named by what they are (docs/FULLY_NATIVE.md step 3d): the game says which buffer (FBP,
// FBW) is which. windowScale: drawn at the native frame's scale (gsHwSetFrameSize) like the picture's own targets
// instead of 1x - for a buffer only sampled, never shown or copied 1:1, whose detail grows with it (VCS's reflection
// map); kept at 1x while the GS bloom (PS2X_HW_POSTFX without b) shares its memory. The names show in PS2X_HW_RT_LOG.
// Main thread, before rendering; up to 16.
void gsHwSetTargetRole(uint32_t fbp, uint32_t fbw, const char *name, bool windowScale);
// [gta-recomp] Texture identity by raster (docs/FULLY_NATIVE.md step 3d): the RAM address of the raster the next upload on
// this thread sends, and its byte count - taken by the next upload of exactly that many bytes; a texture made from that
// upload is named by the address (gsHwTextureForRaster). The thread that processes the VIF1 chain.
void gsHwSetUploadSource(uint32_t address, uint32_t bytes);
// [gta-recomp] this thread's upload source, cleared: handed to the GS stage with the next command (gs_frontend.cpp)
void gsHwTakeUploadSource(uint32_t &address, uint32_t &bytes);
// [gta-recomp] The renderer's texture key of the raster at `address` (the latest made from it), 0 if none. Render thread.
uint64_t gsHwTextureForRaster(uint32_t address);
// [gta-recomp] Draw sources (milestone 3's "unconverted draws"): the draws still made from GS primitives, by kind -
// where their packets came from (runtime/gs/gs_draw_source.h), target, texture, blend, depth, coverage - per frame
// since the last call, one kind per line, most draws first; `reset` starts a new window. The first call switches the
// per-kind table on (PS2X_HW_DRAW_SOURCES=1 does from boot and logs it every 5 s). The totals are always in the perf
// line (gs_draws ...). Main thread.
std::string gsHwDrawSourceReport(bool reset);

// [gta-recomp] The frame hook (render mods: src/modapi/mod_render.cpp, docs/MODDING.md "Rendering"). Called on the main
// thread once a 3D frame's scene is drawn - world, water, peds, vehicles, particles - and before the game's post
// effects (bloom, trails, motion blur) and the HUD, with the picture's target, its Z buffer and the camera. The hook
// draws through `device` in passes of its own (the renderer's pass is ended before; its draws set their state again).
struct GSHwFrameView
{
    rhi::Device *device = nullptr;
    rhi::Texture *color = nullptr;         // the picture's target (RGBA8; multisampled with MSAA): draw into it
    rhi::Texture *colorResolved = nullptr; // a single-sampled copy to read, when asked for (GSHwFrameHookResolvedColor)
    rhi::Texture *depth = nullptr;         // its Z buffer, sampleable, when asked for (GSHwFrameHookDepth): D32F holding the
                                           // GS Z / 2^24, 0 = nothing drawn (far); multisampled with MSAA
    uint32_t width = 0, height = 0;        // the 640x448 picture in target pixels, from (0, 0) (the targets may be larger)
    // The camera, from the frame's native draws (camera = true): the target pixel centre (x + 0.5, y + 0.5) at view depth
    // w is the view-space point ((x + 0.5 - cx) / fx * w, (y + 0.5 - cy) / fy * w, w) - x right, y down, metres.
    bool camera = false;
    float fx = 0.0f, fy = 0.0f, cx = 0.0f, cy = 0.0f;
    float depthA = 0.0f, depthB = 0.0f, depthScale = 0.0f; // the Z buffer: GS z = depth / depthScale = depthA + depthB / w
    float fogBias = 255.0f, fogScale = 0.0f;              // the world's fog: visibility clamp((fogBias + fogScale w) / 255)
    uint64_t frame = 0;                                   // frames the hook ran in
    // Temporal AA (gsHwSetJitter): the sub-pixel offset this frame's 3D was drawn with and the last frame's (target pixels),
    // and the camera's reprojection from the frame's static world draws (reprojectValid): row-major Q with
    // (u' w', v' w', ., w') = Q (u w, v w, z w, w) - (u, v) this frame's unjittered target position, z the GS z, w the view
    // depth; (u', v') where that point was in the last frame (unjittered). Camera motion only: moving objects have none.
    float jitterX = 0.0f, jitterY = 0.0f, prevJitterX = 0.0f, prevJitterY = 0.0f;
    bool reprojectValid = false;
    float reproject[16] = {};
    // Per-object motion (GSHwFrameHookVelocity): RGBA16F at width x height - xy the pixels moved since the last frame
    // (unjittered), z the view depth of the surface it describes, w 1 where a matched native draw covers the pixel, 0 else
    // (no motion of its own known: use the reprojection). Compare z with the Z buffer: GS-path draws are not in it.
    rhi::Texture *velocity = nullptr;
    // The picture as it is now, single-sampled (resolved again with MSAA): what an earlier hook drew into it included -
    // call currentColor(currentColorCtx) inside the hook, with no pass of the hook's open.
    rhi::Texture *(*currentColor)(void *ctx) = nullptr;
    void *currentColorCtx = nullptr;
    // The camera's rotation in the world (viewKnown), from the frame's static world draws (their model matrices have no
    // rotation): row-major, view = worldToView world - world x east, y north, z up; view x right, y down, z forward.
    bool viewKnown = false;
    float worldToView[9] = {};
    // Shadow maps (GSHwFrameHookShadow): shadowMap(currentColorCtx, m, count, size, &drawn) draws the scene's native draws
    // that write Z depth only into `count` (1..4) square viewports of `size` pixels side by side in
    // a D32F texture (size * count x size) and returns it; m = count row-major 4x4 matrices from view space (above: metres)
    // to clip space (x, y -1..1, y up; z 0..1, larger = nearer the light, cleared to 0). Inside the hook, no pass open.
    rhi::Texture *(*shadowMap)(void *ctx, const float *viewToClip, uint32_t count, uint32_t size, uint32_t *drawn) = nullptr;
};
using GSHwFrameHookFn = void (*)(void *user, const GSHwFrameView &view);
enum : uint32_t
{
    GSHwFrameHookDepth = 1u,         // the Z buffer is read: made sampleable (from its next frame-start clear on)
    GSHwFrameHookResolvedColor = 2u, // the picture is read: a resolved copy with MSAA
    GSHwFrameHookVelocity = 4u,      // per-object motion: the scene's native draws again with their last-frame matrices
    GSHwFrameHookShadow = 8u,        // shadow maps: the scene's opaque native draws are kept for GSHwFrameView::shadowMap
};
// [gta-recomp] Sets the frame hook (one; nullptr = none) and what it reads (GSHwFrameHook*). Main thread.
void gsHwSetFrameHook(GSHwFrameHookFn fn, void *user, uint32_t needs);
// [gta-recomp] Temporal AA's jitter: the 3D picture's draws offset by the next point of a Halton (2, 3) sequence of `phases`
// points at each frame (0: off, the default). For a render mod that resolves it (DLAA); reported in GSHwFrameView. Any thread.
void gsHwSetJitter(uint32_t phases);
