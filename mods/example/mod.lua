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
        for _, n in ipairs({
            "bevy_core::time::time::Time",
            "bevy_window::windows::Windows",
        }) do
            tunnet.log(string.format("example mod: resource %s id=%s ptr=0x%x", n,
                tostring(tunnet.component_id(n)), tunnet.resource(n)))
        end
    end
    if tunnet.frame() == 50 then
        tunnet.log(string.format(
            "example mod: credits=%d digging=%s jetpack=%s",
            tunnet.credits(),
            tostring(tunnet.story_unlock("digging")),
            tostring(tunnet.story_unlock("jetpack"))))
        local b = tunnet.asset_bytes("textures/example_new.png")
        tunnet.log(string.format("example mod: new asset bytes = %s", b and #b or "nil"))
        tunnet.log(string.format("example mod: entity_count = %d", tunnet.entity_count()))
        local pp = tunnet.player_pos()
        tunnet.log(string.format("example mod: player_pos = %s",
            pp and string.format("(%.2f, %.2f, %.2f)", pp.x, pp.y, pp.z) or "nil"))
        for _, n in ipairs(tunnet.components()) do
            local sz = tunnet.component_size(n)
            if sz == 320 or n:find("player") or n:find("movement") then
                tunnet.log(string.format("example mod: size(%s) = %d", n, sz))
            end
        end
        -- Writes (uncomment to try):
        -- tunnet.set_credits(999)
        -- tunnet.set_story_unlock("jetpack", true)
    end
end)

-- Replace the Puzzled Squid logo texture with a different icon (visible test).
-- Paths are relative to this mod's own directory; they cannot escape it.
tunnet.override_asset("textures/puzzled_squid.png", "puzzled_squid.png")
-- Register a brand-new asset path (not in the game's embedded table).
tunnet.override_asset("textures/example_new.png", "puzzled_squid.png")
