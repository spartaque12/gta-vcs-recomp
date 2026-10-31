# Physics (docs/game-internals.md 12f, docs/DECISIONS.md): Jolt Physics 5.6.0 (third_party/JoltPhysics, MIT, vendored
# unmodified: Jolt/ and Build/CMakeLists.txt of the v5.6.0 tag) and vcs_physics, the only code that includes it. Jolt's
# defines and instruction-set options are PUBLIC on its target, so vcs_physics links it PRIVATE: they reach these
# sources and never the game's generated code (which they would rebuild) - the game sees ragdoll.h's plain API.
set(OVERRIDE_CXX_FLAGS OFF CACHE BOOL "" FORCE)                 # the project's release flags, not Jolt's own
set(FLOATING_POINT_EXCEPTIONS_ENABLED OFF CACHE BOOL "" FORCE)  # never trap inside the game process
set(USE_STATIC_MSVC_RUNTIME_LIBRARY OFF CACHE BOOL "" FORCE)    # /MD like everything else (its default is /MT)
set(ENABLE_ALL_WARNINGS OFF CACHE BOOL "" FORCE)                # its /Wall /WX is -Weverything under clang-cl
set(GENERATE_DEBUG_SYMBOLS OFF CACHE BOOL "" FORCE)             # line tables below, as the runtime's
set(INTERPROCEDURAL_OPTIMIZATION OFF CACHE BOOL "" FORCE)       # native objects: --quick relinks don't redo Jolt
set(ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
set(ENABLE_OBJECT_STREAM OFF CACHE BOOL "" FORCE)
set(DEBUG_RENDERER_IN_DEBUG_AND_RELEASE OFF CACHE BOOL "" FORCE)
set(PROFILER_IN_DEBUG_AND_RELEASE OFF CACHE BOOL "" FORCE)
set(CROSS_PLATFORM_DETERMINISTIC OFF CACHE BOOL "" FORCE)
set(DOUBLE_PRECISION OFF CACHE BOOL "" FORCE)                   # the map is 4 km wide: floats hold it to 0.25 mm
# no GPU compute (its hair): no dxc, no Vulkan SDK needed to build
set(JPH_USE_DX12 OFF CACHE BOOL "" FORCE)
set(JPH_USE_VK OFF CACHE BOOL "" FORCE)
set(JPH_USE_MTL OFF CACHE BOOL "" FORCE)
set(JPH_USE_CPU_COMPUTE OFF CACHE BOOL "" FORCE)
# The instruction set: the game's own baseline, x86-64-v3 (/arch:AVX2, -march=x86-64-v3: AVX2, FMA, BMI, LZCNT,
# F16C) - no CPU the game runs on lacks it. AVX-512 off (most players' CPUs don't have it).
set(USE_SSE4_1 ON CACHE BOOL "" FORCE)
set(USE_SSE4_2 ON CACHE BOOL "" FORCE)
set(USE_AVX ON CACHE BOOL "" FORCE)
set(USE_AVX2 ON CACHE BOOL "" FORCE)
set(USE_AVX512 OFF CACHE BOOL "" FORCE)
set(USE_LZCNT ON CACHE BOOL "" FORCE)
set(USE_TZCNT ON CACHE BOOL "" FORCE)
set(USE_F16C ON CACHE BOOL "" FORCE)
set(USE_FMADD ON CACHE BOOL "" FORCE)
add_subdirectory("${CMAKE_SOURCE_DIR}/third_party/JoltPhysics/Build" "${CMAKE_BINARY_DIR}/jolt" EXCLUDE_FROM_ALL)

add_library(vcs_physics STATIC ragdoll.cpp)
target_include_directories(vcs_physics PUBLIC "${CMAKE_SOURCE_DIR}/src")
target_link_libraries(vcs_physics PRIVATE Jolt)
# Jolt is built without RTTI (its default); classes derived from its own here (the layer interfaces, the group filter)
# must be too: with RTTI their typeinfo names their Jolt base's, which Jolt never emits (a link error on Linux)
if(MSVC)
    target_compile_options(vcs_physics PRIVATE /GR-)
else()
    target_compile_options(vcs_physics PRIVATE -fno-rtti)
endif()
# debug info: the root CMakeLists.txt's VCS_RUNTIME_DEBUG_INFO, with the runtime's targets
