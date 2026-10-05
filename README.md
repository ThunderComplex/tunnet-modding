# Tunnet Modloader

A mod loader and Lua mod API for the game **Tunnet** (a Rust game built on
Bevy 0.7). It launches the game with a small injected core, loads Lua mods, and
lets them replace embedded assets and run per-frame code — without modifying any
Steam files and without shipping mods as DLLs.

> Status: early MVP. See [Capabilities](#what-it-can-and-cant-do) for exactly
> what works today.

---

## For players: install & use

The loader is drag-and-drop. You do **not** need to edit or patch `tunnet.exe`.

1. Locate your Tunnet install folder, e.g.
   `...\steamapps\common\Tunnet\`.
2. Copy these files into that folder (next to `tunnet.exe`):
   - `tunnet-loader.exe`
   - `core.dll`
3. Put mods in a `mods\` folder there, one subfolder per mod:
   ```
   Tunnet\
     tunnet.exe
     steam_api64.dll
     tunnet-loader.exe
     core.dll
     mods\
       example\
         mod.lua
         puzzled_squid.png
   ```
4. Launch the game with **`tunnet-loader.exe`** (not `tunnet.exe`).
   - On Steam, add it as a non-Steam shortcut, or just double-click it.
5. A `core.log` file appears next to the loader. It lists loaded mods and any
   errors.

To play without mods, launch `tunnet.exe` directly as usual.

### Uninstall

Delete `tunnet-loader.exe`, `core.dll`, `mods\`, and `core.log`. The game is
untouched.

---

## For mod developers

### Anatomy of a mod

```
mods\my-mod\
  mod.lua          <- entry point, loaded once
  some_texture.png <- assets your mod uses (optional)
```

Mods are plain Lua 5.4 scripts. There is no build step and no manifest.

### The `tunnet` API

| Function | Description |
|---|---|
| `tunnet.log(msg)` | Write `msg` to `core.log` (prefixed `[lua]`). |
| `tunnet.on_load(fn)` | Register `fn()` to run once, after all mods are loaded, before the game starts. |
| `tunnet.on_frame(fn)` | Register `fn(dt_ms)` to run on the main thread (~60 Hz), driven by the Win32 message pump. `dt_ms` is milliseconds since the last tick. |
| `tunnet.on_update(fn)` | Register `fn()` to run once per game frame from inside Bevy's `App::update`, just before the frame's systems run. ECS-synced. |
| `tunnet.frame()` | Number of `App::update` frames so far. |
| `tunnet.world_ptr()` | Address of the game's Bevy `World` (0 until the first update). |
| `tunnet.components()` | Array of registered component/resource type names (e.g. `"tunnet::state::GameState"`). |
| `tunnet.component_id(name)` | `ComponentId` index for a type name, or `nil` if not registered yet. |
| `tunnet.resource(name)` | Pointer to a resource's data (0 if absent). Populated from the game's own resource lookups, so call it after a few frames. Use with `tunnet.mem.*`. |
| `tunnet.credits()` / `tunnet.set_credits(n)` | Read/write the player's credits. |
| `tunnet.story_unlock(name)` / `tunnet.set_story_unlock(name, bool)` | Read/write story unlock flags: `digging`, `relay`, `hub`, `filter`, `scan_short`, `scan_long`, `jetpack`, `antivirus`, `sprint`, `optical_fiber`, `antenna`, `surface`, `companion`. |
| `tunnet.read_resource(name, offset, kind)` / `tunnet.write_resource(name, offset, kind, value)` | Generic typed field access. `kind` is `"u8"`, `"u32"`, `"i32"`, or `"f32"`. |
| `tunnet.asset_bytes(path)` | Read an asset's bytes by logical path (returns `nil` if not found). Mods can add brand-new paths via `override_asset`; they're served on demand by the asset IO hook. |
| `tunnet.find_vec3(x, y, z[, tol])` | Best-effort scan of private memory for an `(f32,f32,f32)` triple; returns its address or 0. Bounded and can miss; advanced use only. |
| `tunnet.mem.*` | Low-level memory access (advanced). See below. |
| `tunnet.override_asset(logical_path, relative_file)` | Replace an embedded asset. See below. |

`override_asset` rules:

- `logical_path` is the game's asset path, e.g. `"textures/puzzled_squid.png"`
  (see the asset list in the notes / `data/asset_table.csv`).
- `relative_file` is a path **relative to your mod's own folder**. Absolute
  paths and `..` escapes are rejected — a mod can only load files it ships.
- Call it at load time (top level, or inside `on_load`). Overrides are applied
  before the game builds its asset table.

#### Low-level memory access (`tunnet.mem`)

Advanced, dangerous — invalid addresses crash the game. These exist to build
typed ECS accessors and to inspect the running `World`.

| Function | Description |
|---|---|
| `tunnet.mem.read_u8/u16/u32/u64/i32/f32/f64(addr)` | Read a value at an address. |
| `tunnet.mem.write_u8/u32/u64/f32(addr, value)` | Write a value at an address. |
| `tunnet.mem.read_bytes(addr, len)` | Read `len` bytes as a Lua string. |
| `tunnet.mem.read_cstr(addr)` | Read a NUL-terminated string (max 4096 bytes). |

The `World` pointer plus this API let advanced mods traverse Bevy's data. Typed
game-state accessors (credits, story flags, inventory, entities) are the next
milestone; see [What it can and can't do](#what-it-can-and-cant-do).

### Example

`mods\example\mod.lua`:

```lua
tunnet.log("example mod: loaded")

tunnet.on_load(function()
    tunnet.log("example mod: on_load")
end)

local frames = 0
tunnet.on_frame(function(dt)
    frames = frames + 1
    if frames == 60 then
        tunnet.log(string.format("example mod: 60 frames (dt=%.2f ms)", dt))
    end
end)

-- ECS-synced: runs once per game frame; world_ptr() is the Bevy World.
tunnet.on_update(function()
    if tunnet.frame() == 1 then
        local w = tunnet.world_ptr()
        tunnet.log(string.format("example mod: first ECS update; world @ 0x%x", w))
    end
end)

-- Assets are resolved relative to this mod's folder ("example/" is implicit).
tunnet.override_asset("textures/puzzled_squid.png", "puzzled_squid.png")
```

### Finding asset paths

The complete list of assets the game embeds (608 of them) is recoverable with
the tooling in `analysis/`; see `data/asset_table.csv` (columns: `path`,
`data_off`, `data_len`, `data_va`). Common folders: `textures/`, `snd/`,
`models/`, `man/`, `shaders/`, `fonts/`.

To regenerate the list, point the tools at your `tunnet.exe` and run the
pipeline in order (details in [`analysis/README.md`](analysis/README.md)):

```powershell
$env:TUNNET_EXE = "C:\...\steamapps\common\Tunnet\tunnet.exe"
python analysis/scan_paths.py        # optional recon
python analysis/map_assets.py
python analysis/map_assets2.py
python analysis/find_include_all.py
python analysis/analyze_unmapped.py  # optional diagnostic
python analysis/parse_iaa.py         # exact table (uses objdump)
python analysis/extract_assets.py    # -> assets_extracted/
```

Outputs land in `data/` (gitignored) and `assets_extracted/` (gitignored).

---

## What it can and can't do

### Works today

- Load Lua mods from `mods\<name>\mod.lua`.
- **Replace any embedded asset** (textures, sounds, models, shaders, fonts) at
  startup, keyed by the game's logical asset path.
- **Run per-frame Lua** on the main thread (timers, polling, scripted logic that
  doesn't need game state).
- **ECS hook.** Run code once per game frame from inside Bevy's `App::update`
  (`tunnet.on_update`) and get the game's `World` pointer (`tunnet.world_ptr()`),
  plus low-level `tunnet.mem.*` read/write.
- **Component registry.** List every registered component/resource type name
  (`tunnet.components()`), look up a type's `ComponentId`
  (`tunnet.component_id(name)`), and get a pointer to a resource's data
  (`tunnet.resource(name)`).
- **Typed game state.** Read/write player credits (`tunnet.credits()` /
  `set_credits`), story unlock flags (`tunnet.story_unlock` /
  `set_story_unlock`), and arbitrary resource fields by offset
  (`tunnet.read_resource` / `write_resource`).
- **New asset files.** Mods can register brand-new asset paths with
  `override_asset`; the asset IO hook serves them on demand, and
  `tunnet.asset_bytes(path)` reads any asset's bytes.
- Write to `core.log`.

### Not yet (roadmap)

- **Using new assets in-game.** `asset_bytes` returns raw bytes; creating a
  Bevy asset handle and attaching it to entities/UI needs entity/archetype
  access (next milestone).
- **Entities / player position / spawning.** Needs the entity/archetype/storage
  layouts; not exposed yet.
- **Other fields.** Only credits and the 13 unlock flags have named accessors;
  other fields need per-type offsets (use `read_resource`/`write_resource`).
  Game types only register in-game, so call these after starting/loading a game
  (not at the main menu).
- **New content.** You can replace existing assets, but you cannot add brand-new
  asset paths the game never requests (until a loader hook supports it).
- **Save/config interception.** Runtime save/load hooks are planned; for now
  you can edit `%APPDATA%\tunnet\*.json|*.toml` externally.
- **Native mods.** By design, mods are Lua/data, never DLLs.

### Constraints

- **Windows only**, and tuned to the current Steam build. Hook addresses are
  build-specific; a game update may require new signatures.
- Single-player game, no anti-cheat. Injecting into a live process can be
  flagged by overly aggressive antivirus; allow-list the loader if needed.
- The loader always passes `--bypass-launcher` to the game (the game otherwise
  relaunches itself, and the injected process would be the wrong one).

---

## Building from source

Requirements:

- Rust (the workspace targets `x86_64-pc-windows-gnu`; see `.cargo/config.toml`)
- MinGW-w64 `gcc` (for the GNU target and for vendored Lua)
- Python 3 (only for the `analysis/` tooling)

```powershell
cargo build --release
```

Outputs (in `target\x86_64-pc-windows-gnu\release\`):

- `tunnet-loader.exe`
- `core.dll`

Copy both next to `tunnet.exe` and launch `tunnet-loader.exe`.

### Loader options

```
tunnet-loader.exe [--game <path>] [--core <path>] [--] [game args...]
```

Defaults resolve next to the loader (`.\tunnet.exe`, `.\core.dll`), so it can be
dropped straight into the install directory. Extra args after `--` are passed to
the game.

### Core environment variables

- `TUNNET_MODS` — override the mods directory (default: `<core dir>\mods`).

---

## How it works

1. `tunnet-loader.exe` starts `tunnet.exe` **suspended** with
   `--bypass-launcher`.
2. It injects `core.dll` via `CreateRemoteThread(LoadLibraryW)`.
3. `core.dll` installs three detours:
   - `EmbeddedAssetIo::add_asset` — called once per embedded asset at startup;
     used to substitute mod assets by path.
   - `PeekMessageW` — the game's Win32 message pump on the main thread; used as
     a ~60 Hz tick to run Lua `on_frame`.
   - `bevy_app::App::update` — once per game frame; captures the `World` pointer
     (`App.world`) and runs Lua `on_update` before the frame's systems.
4. The core loads `mods\**\mod.lua` and signals a ready event.
5. Only then does the loader resume the game, so asset overrides are always in
   place before the game registers its assets.

No Steam file is modified and no permanent patch is applied.

---

## Repository layout

```
loader/     modloader executable (Rust)
core/       injected core DLL: hooks + Lua runtime (Rust, mlua)
mods/       example mods
analysis/   Python reverse-engineering tooling (asset map, xref, etc.)
data/       recovered tables/symbols (gitignored; regenerate with analysis/)
notes/      detailed reverse-engineering notes
```

The reverse-engineering notes in `notes/TUNNET_MODDING_NOTES.md` document the
engine identification, the exact asset table, hook addresses, and the roadmap.

---

## Troubleshooting

- **Nothing happens / no `core.log`** — make sure `core.dll` sits next to
  `tunnet-loader.exe`, and launch the loader (not `tunnet.exe`).
- **Game opens then closes** — the loader may have failed to inject; check the
  console output of `tunnet-loader.exe`.
- **`override_asset` error about escaping the mod directory** — use a path
  relative to your mod folder (no absolute paths, no `..`).
- **Two `tunnet.exe` processes** — the game relaunched itself; the loader should
  be passing `--bypass-launcher`. Update to the current loader.
