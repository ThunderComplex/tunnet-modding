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

-- Replace the Puzzled Squid logo texture with a different icon (visible test).
-- Paths are relative to this mod's own directory; they cannot escape it.
tunnet.override_asset("textures/puzzled_squid.png", "puzzled_squid.png")
