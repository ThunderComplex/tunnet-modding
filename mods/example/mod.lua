-- Example Tunnet mod.
-- Demonstrates the MVP API: logging, per-frame callbacks, asset overrides.

tunnet.log("example mod: loaded")

tunnet.on_load(function()
    tunnet.log("example mod: on_load")
end)

local frames = 0
tunnet.on_frame(function(dt)
    frames = frames + 1
    if frames == 60 then
        tunnet.log(string.format("example mod: 60 frames (last dt=%.2f ms)", dt))
    end
end)

-- ECS bridge: runs once per game frame from App::update, with the World pointer
-- available via tunnet.world_ptr().
tunnet.on_update(function()
    if tunnet.frame() == 1 then
        local w = tunnet.world_ptr()
        tunnet.log(string.format(
            "example mod: first ECS update; world @ 0x%x (byte0=%d)",
            w, tunnet.mem.read_u8(w)))
    end
    if tunnet.frame() == 5 then
        local comps = tunnet.components()
        tunnet.log(string.format("example mod: %d types registered", #comps))
        tunnet.log("example mod: GameState id = " ..
            tostring(tunnet.component_id("tunnet::state::GameState")))
    end
end)

-- Replace the Puzzled Squid logo texture with a different icon (visible test).
-- Paths are relative to this mod's own directory; they cannot escape it.
tunnet.override_asset("textures/puzzled_squid.png", "puzzled_squid.png")
