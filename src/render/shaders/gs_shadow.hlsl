// Shadow maps for render mods (gs_hw.cpp RhiExecutor::shadowPass, docs/RENDERHOOK_PLAN.md "Sun shadows"): the frame's
// opaque native draws again, depth only, with a matrix per draw that the executor builds on the CPU: the mod's camera ->
// light clip matrix times the draw's window matrix taken back into camera space (the lens). Rows of that matrix in `rows`,
// applied to the model-space position. Depth: larger = nearer the light (cleared to 0, GreaterEqual), as the GS's Z.

cbuffer Shadow : register(b0)
{
    float4 rows[4];
};

float4 vs_shadow_mesh(float3 pos : POSITION) : SV_Position
{
    const float4 p = float4(pos, 1.0);
    return float4(dot(rows[0], p), dot(rows[1], p), dot(rows[2], p), dot(rows[3], p));
}

void ps_shadow()
{
}
