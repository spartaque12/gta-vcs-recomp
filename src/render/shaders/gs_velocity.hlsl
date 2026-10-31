// Per-object motion for temporal AA (gs_hw.cpp RhiExecutor::velocityPass, docs/RENDERHOOK_PLAN.md "DLAA, step 2"): the
// frame's native draws again, each with this frame's and the last frame's GS window matrix (gs_draw.hlsl nativePosition:
// S = c0 x + c1 y + c2 z + c3, pixel = S.xy / S.w - XYOFFSET), into an RGBA16F target with a depth buffer of its own.
// Output: xy = this frame's unjittered target position minus the last frame's (pixels moved), z = the view depth (S.w),
// w = 1 (covered). vs_velocity_mesh: a cached mesh (static world, rigid models) - the same vertices under both matrices;
// vs_velocity_skinned: a skinned draw's vertices of this frame and the last, side by side.

cbuffer Velocity : register(b0)
{
    float4 cur[4];   // this frame's window matrix columns
    float4 prev[4];  // the last frame's
    float4 offsets;  // XYOFFSET (pixels): this frame xy, the last frame zw
    float4 target;   // target pixels per PS2 pixel xy, pixel-centre offset z, Z format scale w
    float4 size;     // the target's size in PS2 pixels xy
};

struct VSOut
{
    float4 pos : SV_Position;
    float3 now : TEXCOORD0; // S.xyw and P.xyw: homogeneous, interpolated perspective-correctly, divided per pixel
    float3 was : TEXCOORD1;
};

float4 window(float4 c[4], float3 p)
{
    return c[0] * p.x + c[1] * p.y + c[2] * p.z + c[3];
}

VSOut velocity(float3 pNow, float3 pWas)
{
    const float4 S = window(cur, pNow), P = window(prev, pWas);
    VSOut o;
    const float2 xy = S.xy / S.w - offsets.xy;
    const float depth = min(floor(S.z / S.w) * target.w, 1.0);
    const float2 ndc = (xy + target.z) / size.xy;
    o.pos = float4((ndc.x * 2.0 - 1.0) * S.w, (1.0 - ndc.y * 2.0) * S.w, depth * S.w, S.w);
    o.now = S.xyw;
    o.was = P.xyw;
    return o;
}

VSOut vs_velocity_mesh(float3 pos : POSITION)
{
    return velocity(pos, pos);
}

VSOut vs_velocity_skinned(float3 pos : POSITION, float3 was : TEXCOORD0)
{
    return velocity(pos, was);
}

float4 ps_velocity(VSOut i) : SV_Target0
{
    const float2 now = (i.now.xy / i.now.z - offsets.xy + target.z) * target.xy;
    const float2 was = (i.was.xy / i.was.z - offsets.zw + target.z) * target.xy;
    return float4(now - was, i.now.z, 1.0);
}
