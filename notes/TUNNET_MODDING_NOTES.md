# Tunnet — Reverse Engineering / Mod API Research Notes

_Generated: 2026-10-05. Working copy: `G:\SteamLibrary\steamapps\common\Tunnet`_

## 1. TL;DR

- **Tunnet is a Rust game built on the Bevy game engine, version 0.7.0.**
- It is shipped as a **single, statically-linked Windows executable** (`tunnet.exe`, ~90 MB) with **all game assets embedded into the binary** (`bevy_embedded_assets`). There is no external `assets/` folder.
- The binary is **stripped of its symbol table and has no debug info**, BUT Bevy stores the Rust `type_name` of every system, component, event, and plugin at runtime, and those strings survive in the binary. We recovered **~625 game-owned symbols** (`tunnet::…`) — effectively a partial symbol map.
- Game data (saves, settings, keybindings) is **plaintext JSON / TOML** in `%APPDATA%\tunnet\`. This is the easiest modding surface.
- The game is cleanly organized into **Bevy plugins, one per feature** (e.g. `DigPlugin`, `DoorPlugin`, `RelayPlugin`, `EndpointPlugin`, `CablePlugin`, …), which is very favorable for a mod API.
- There is **no scripting layer** (no Lua, no WASM). Mods must be native code (DLL injection / proxy DLL / binary patching) and/or data/asset replacement.

## 2. How the engine was identified

| Evidence | Conclusion |
|---|---|
| `LICENSES.txt` lists `bevy 0.7.0`, `bevy_ecs 0.7.0`, `bevy_render 0.7.0`, `wgpu 0.12.0`, `bevy_embedded_assets 0.2.1`, `bevy_kira_audio 0.8.0`, `heron 0.12.1` + `rapier3d 0.11.1`, `bevy_steamworks 0.4.0`, `bevy_text_mesh 0.1.0`, `transvoxel 0.1.1`, `egui 0.18.1` | Bevy 0.7 stack |
| PE sections include `.eh_frame`, `.pdata`, `.xdata`; no `.pdb`; no symbol table (`nm` → "no symbols") | Rust, x86_64, stripped, no DWARF |
| `strings` shows `/home/puzzled_squid/src/tunnet/src/*.rs` panic paths and `target/x86_64-pc-windows-gnu/release/…` | Built on Linux for the `x86_64-pc-windows-gnu` target; crate/package name `tunnet` |
| `bevy_embedded_assets` in deps + no `assets/` folder on disk + raw PNG/Ogg/glTF signatures inside the exe | Assets are `include_bytes!`-embedded in `.rdata` |

### Dependency highlights (from `LICENSES.txt`)
- **Engine:** `bevy 0.7.0` (ecs, render/wgpu 0.12, pbr, sprite, ui, text, gltf, winit 0.26, gilrs).
- **Assets embedded:** `bevy_embedded_assets 0.2.1`.
- **Audio:** `bevy_kira_audio 0.8.0` + `kira 0.5.3`, `cpal`, `rodio` (mp3/ogg loaders).
- **Physics:** `heron 0.12.1`, `heron_rapier`, `rapier3d 0.11.1`, `parry3d 0.7.1`.
- **Terrain/voxels:** `transvoxel 0.1.1` / `transvoxel-data 0.2.1` (marching-cubes style voxel terrain).
- **Steam:** `steamworks 0.9.0` + `bevy-steamworks 0.4.0` (achievements, etc.).
- **UI/dev:** `egui 0.18.1` / `eframe` (likely debug overlay), `bevy_text_mesh` + `ttf2mesh`.
- **Misc:** `serde`/`serde_json`/`ron`/`toml` (save + config), `image 0.23`, `gltf`, `noise 0.7`, `ureq`/`rustls` (HTTP — the in-game chatbot / "review" endpoint?).

## 3. Architecture (recovered from `type_name` strings)

The game is a Bevy `App` composed of feature plugins. Recovered game plugins include:

```
tunnet::net::endpoint::EndpointPlugin        tunnet::net::relay::RelayPlugin
tunnet::net::cable::CablePlugin              tunnet::net::transport::TransportPlugin
tunnet::net::build::NetBuildingPlugin        tunnet::net::bridge::BridgePlugin
tunnet::net::filter::FilterConfig            tunnet::net::errors::ErrorPlugin
tunnet::net::hub::HubPlugin                  tunnet::net::debug::NetDebugPlugin
tunnet::net::pc::PersonalComputerPlugin      tunnet::net::tester::…
tunnet::map::dig::DigPlugin                  tunnet::map::edit::EditPlugin
tunnet::map::water::WaterPlugin              tunnet::map::MapPlugin
tunnet::map::chunks::objects::door::DoorPlugin
tunnet::map::chunks::objects::sign::SignPlugin
tunnet::map::chunks::objects::cart::CartPlugin
tunnet::npc::hearing::HearingPlugin          tunnet::npc::wandering::WanderingPlugin
tunnet::npc::path_finding::PathFindingPlugin tunnet::npc::photophobia::PhotophobiaPlugin
tunnet::npc::hide::HidePlugin                tunnet::npc::shy::ShyPlugin
tunnet::npc::stalk::StalkPlugin
```

Representative systems / components / events (all names are exact Rust paths):

- **Player / movement:** `player.rs`, `movement.rs` (`movement`, `jetpack`, footsteps), `tunnet::player::JetPackLight`.
- **Network gameplay (core loop):** `net::endpoint`, `relay`, `hub`, `filter`, `tester`, `cable`, `bridge`, `antenna`, `transport`, `proto`, `infection`, `pc`, `monitor`, `build`, `debug`. Systems: `tunnet::net::transport::tick`, `tunnet::net::animate_cable`, `tunnet::net::build::update_wire_preview`, etc.
- **World:** `map::chunk` (`Chunk`, `DirtyChunk`, `generate_meshes`), `map::terrain` (`Permanent`, `AudioState`), `map::voxel`, `map::water`, `map::dig` (`Diggable`, `ExplosionEvent`), `map::bunker`, `map::chunks::supermarket`, `map::edit`.
- **NPCs:** `npc::chase`, `hearing`, `hide`, `hit`, `path_finding`, `photophobia`, `shy`, `stalk`, `wandering`.
- **Meta:** `save`, `settings`, `menu`, `pause`, `hud`, `inventory`, `knowledge` (journal), `dialog`, `manual`, `shop`, `loot`, `grab`, `compass`, `booth`, `credits`, `end_credits`, `review`, `boss`, `death`, `home`, `surface`, `particle`, `postprocessing`, `tweening`, `achievement`, `earthquake`, `audio`.
- **Story:** `tunnet::story::Story` resource, with a `state` enum (values seen in saves: e.g. `ConnectToShelters`, `InfectMainframeWithAB`, …).

### Recovered source module tree (game-owned)
```
src/main.rs  src/save.rs  src/settings.rs  src/menu.rs  src/pause.rs
src/hud.rs  src/input.rs  src/dialog.rs  src/manual.rs  src/knowledge.rs
src/inventory.rs  src/tools.rs  src/shop.rs  src/loot.rs  src/grab.rs
src/compass.rs  src/booth.rs  src/credits.rs  src/end_credits.rs  src/review.rs
src/death.rs  src/boss.rs  src/home.rs  src/surface.rs  src/particle.rs
src/postprocessing.rs  src/tweening.rs  src/movement.rs  src/player.rs
src/audio.rs  src/achievement.rs  src/earthquake.rs  src/story.rs
src/map.rs + map/{chunk,terrain,voxel,water,dig,bunker,edit,core,core/raw}.rs
src/map/chunks/{objects,objects/cart,objects/door,objects/sign,supermarket}.rs
src/net.rs + net/{endpoint,relay,hub,filter,tester,cable,bridge,antenna,
                   transport,proto,infection,pc,monitor,build,debug}.rs
src/npc.rs + npc/{chase,hearing,hide,hit,path_finding,photophobia,shy,stalk,wandering}.rs
```

## 4. Assets

- Embedded in the exe via `include_bytes!` (raw, not compressed by the packer).
- Asset namespaces seen in strings: `textures/…png`, `snd/…ogg` (incl. `snd/songs/…`), `models/…glb#Scene0` / `…#AnimationN` (glTF scenes/animations), `shaders/monitor.wgsl`, `fonts/…`.
- **No external asset folder** → asset modding requires either (a) binary patching/repacking the embedded bytes, or (b) runtime interception of `bevy_asset` loads.
- `bevy_embedded_assets` registers an in-memory `AssetIo` source; the game reads assets from a static directory baked into `.rdata`.

## 5. Persistent data (easy modding surface)

Location: **`%APPDATA%\tunnet\`** (i.e. `C:\Users\<user>\AppData\Roaming\tunnet`).

| File | Format | Notes |
|---|---|---|
| `slot_0.json`, `slot_1.json`, `slot_2.json` | JSON | Save slots. Large (1–4 MB). |
| `auto` | JSON | Autosave (`auto_save_interval`). |
| `settings.toml` | TOML | `safe`, `placement_preview`, `leaderboard`, `photosensitive`, `arachnophobia`, `dig_anywhere`. |
| `system_settings.toml` | TOML | `ssao`, `sensitivity`, `volume`, `music`, `fullscreen`, `invert_x`, `invert_y`, `vsync`. |
| `key_bindings.toml` | TOML | `user_cfg = [[Action, Key], …]`. |
| `steam_autocloud.vdf` | VDF | Steam Cloud bookkeeping. |

### Save schema (from `slot_0.json` + `struct Save`/`struct PlayerSave` serde metadata)
Top-level `Save` (15 fields):
```
player, story, nodes, edges, endpoints, relays, filters, testers,
hubs, antennas, bridges, chunk_types, chunks, toolboxes, pages
```
`player`: `{ pos:[x,y,z], credits:int }`

`story` (partial, ~45 fields):
```
state, digging, relay, hub, filter, scan_short, scan_long, connection_status,
streaks, mainframes, jetpack, antivirus, sprint, optical_fiber, antenna, surface,
companion, shop_level, disinfected, disinfection_dialog, movement, look, tester,
military_cleared, luxury_cleared, monastry_cleared, researchlab_cleared,
inventory, knowledge, visited_chunks, map_annotations, boss_phase, page_no, pages,
review, auto_map, relay_light, home, patch, filter_collision, filter_full_address,
tester_repeat, tester_spoof, tester_snoop, scan_short_enhanced, scan_long_peers,
antivirus_v2
```
Save/load uses **serde_json** (`src/save.rs`, `load_slot`, `Cannot open save file` / `Corrupted save file`).

## 6. Build / binary facts

- Target: `x86_64-pc-windows-gnu` (MinGW), built on Linux at `/home/puzzled_squid/src/tunnet`.
- Release build; **stripped**, no PDB, no DWARF.
- Sections: `.text` ~37.7 MB, `.rdata` ~49 MB (contains embedded assets + strings), `.pdata`/`.xdata` (SEH), `.reloc`.
- `bevy_dynamic_plugin` and `bevy_dylib` are present in the dependency list (Bevy default workspace members), so **dynamic plugin support code exists in the binary** — but no evidence the game actually loads external plugins.
- Steam integration: `steam_api64.dll` present; achievements via `bevy_steamworks`.
- CLI flag found: `--bypass-launcher` (the shipped Steam build has no launcher exe, so likely inert here).

## 7. Modding approaches (initial assessment)

| Approach | Difficulty | What it enables | Notes |
|---|---|---|---|
| **Save / config editing** | Easy | Cheats, unlock flags, story state, keybinds, graphics | Plaintext JSON/TOML. Highest ROI to start. |
| **Asset replacement via exe repack** | Medium | Textures, sounds, models, shaders | Assets are raw embedded bytes in `.rdata`; need to locate offsets and rebuild/relink sections. |
| **Proxy DLL (e.g. `steam_api64.dll`) or DLL injection** | Medium–Hard | Native in-process code, hooking, custom systems | Best route to a real "mod API". Requires ABI knowledge of the running Bevy `App`/`World`. |
| **Runtime ECS hooking** | Hard | Add components/systems, alter gameplay | Locate game systems by signature/`type_name`; call into Bevy 0.7 internals. Version-locked to Bevy 0.7. |
| **Static binary patching** | Medium–Hard | Constants, feature flags, small behavior changes | No symbols; use string/`type_name` cross-references as anchors. |
| **`bevy_dynamic_plugin`** | Hard | Clean Rust plugin loading | Requires patching `main` to load a plugin and matching Bevy 0.7 exactly. |

Key constraints for a mod API:
1. **No scripting layer** → mods are native or data-only.
2. **Assets embedded** → no drop-in asset folder.
3. **Bevy 0.7 is old** and ABI/type-layout-sensitive; a native mod must compile against the exact same crate versions.
4. **Reflection** exists for Bevy types but **the game's own components do not appear to be `#[derive(Reflect)]`-registered** (their names appear only via Bevy's `type_name` system labels, not the `TypeRegistry`), so runtime reflection-based modding of game types is limited.

## 8. Open research tasks (TODO)

- [ ] Confirm whether the game registers any game types in `TypeRegistry` (search for `tunnet::…` inside registry dumps at runtime).
- [x] Map the embedded asset index (see section 10) — **DONE**: 608 assets, exact path→offset/size, extracted.
- [ ] Locate the game's `App::build()` / plugin registration to identify a stable injection point.
- [ ] Determine if `bevy_dynamic_plugin` is actually reachable.
- [ ] Identify the in-game chatbot/`review` HTTP endpoint (`ureq`/`rustls`) — could be a hook point or just telemetry.
- [ ] Recover the `story.state` enum's full set of variants (from save snapshots + strings).
- [ ] Check whether the itch.io / GOG / other builds differ (they may be unstripped or have external assets).
- [ ] Decide mod distribution: proxy DLL vs patcher vs save editor.

## 9. Tooling available on this machine

- `C:\mingw64\bin\strings.exe`, `nm.exe`, `objdump.exe`, `objcopy.exe`, `readelf.exe`.
- Extracted string dump: `C:\Users\THUNDE~1\AppData\Local\Temp\opencode\tunnet_strings.txt`.
- Extracted `tunnet::` symbol list: `C:\Users\THUNDE~1\AppData\Local\Temp\opencode\tunnet_symbols.txt` (~625 entries).

---

## 10. Embedded asset map — SOLVED (2026-10-05)

### Mechanism
`bevy_embedded_assets 0.2.1` uses a build script that generates
`include_all_assets(embedded: &mut EmbeddedAssetIo)` containing one
`embedded.add_asset(Path::new(<relpath>), include_bytes!(<abspath>))` per file
under the build-time `assets/` directory. In the release binary this function is
**not** inlined.

### Key addresses (this exact build)
| Symbol | VA | Notes |
|---|---|---|
| `include_all_assets()` | `0x1408202c0` | 608 `add_asset` calls; ends `0x140825aa5` |
| `EmbeddedAssetIo::add_asset()` | `0x14081fa10` | called once per asset |
| `.rdata` region holding the table | ~`0x1424b2d***` onward | interleaved `[path][data]` |

### Layout
The `.rdata` asset region is **contiguous**: for each asset, the relative path
string literal is immediately followed by its file bytes:

```
[ "man/17.png" (10 bytes) ][ PNG bytes (7013) ][ "man/24.png" ][ PNG bytes ] ...
```

Each call is compiled as (Windows x64 method ABI):
```
movq $<data_len>, 0x20(%rsp)   ; data.len
lea  <path_ptr>(%rip), %rdx    ; path.ptr
lea  <data_ptr>(%rip), %r9     ; data.ptr   (may be `mov %reg,%r9` when reused)
mov  $<path_len>, %r8d         ; path.len
mov  %rsi, %rcx                ; self
call 0x14081fa10               ; add_asset
```
Identical files can share a data array (register reuse), e.g. `man/02.png` and
`man/04.png`.

### Result
- **608 assets**, exact `path → (file offset, length)` recovered and validated
  (container size == table length for all PNG/OGG/GLB; 0 mismatches).
- 42.9 MB of assets extracted to `assets_extracted/`.
- Inventory: `textures/` 179 PNG, `man/` 53 PNG, `snd/` 174 OGG,
  `models/` 196 GLB, `shaders/` 4 WGSL, `fonts/` 2 (TTF; `.attf` duplicate),
  `textures/icon.ico`, `models/medusa` (GLB with no extension).

### Artifacts
- `data/asset_table.json` / `data/asset_table.csv` — the exact 608-entry table.
- `assets_extracted/` — all original assets on disk (reference/replacement base).
- `analysis/map_assets.py`, `map_assets2.py`, `scan_paths.py`,
  `find_include_all.py`, `parse_iaa.py`, `extract_assets.py`.

### Implications for the mod API
- **Asset replacement is fully viable**: overwrite the bytes at each
  `data_off` (same length) for a static repack, or intercept at runtime.
- **Best runtime hook target:** `EmbeddedAssetIo::load_path_sync` (or the
  `AssetIo` trait vtable) so a proxy DLL can substitute bytes by asset path
  without touching the exe. `add_asset` (`0x14081fa10`) is a secondary anchor.
- The recovered table can seed a manifest-driven asset mod format
  (`path` → replacement file), independent of exe offsets.

---

## 11. Injection points & launch architecture (2026-10-05)

### Decision
Mods are **not** distributed as DLLs. Ship:
1. **Modloader exe** — launches `tunnet.exe`, injects the core, passes mod list.
2. **Core DLL** (`core.dll`) — the only native artifact; exposes a C-ABI mod API
   and hosts the scripting runtime.
3. **Mods** — manifests + scripts (Lua/WASM) and/or asset/data files.

Injection: `CreateProcess(tunnet.exe, ..., CREATE_SUSPENDED)` →
`VirtualAllocEx`/`WriteProcessMemory`/`CreateRemoteThread(LoadLibraryW, core.dll)`
→ `ResumeThread`. This avoids touching `steam_api64.dll`, keeps Steamworks and
the overlay intact, and survives game updates.

### Binary anchors recovered (this exact build)
| Anchor | VA | Use |
|---|---|---|
| PE entry (`mainCRTStartup`) | `0x1400014b0` | startup |
| `__tmainCRTStartup` | `0x140001180` | CRT; stores `main` ptr in global `0x14564b160` |
| `main` shim | `0x140001000` | (1-byte `ret`; Rust entry is wired via `lang_start`) |
| `EmbeddedAssetIo::add_asset` | `0x14081fa10` | asset table build |
| `include_all_assets` | `0x1408202c0` | asset registration (608 calls) |
| per-plugin `name()` thunks | `0x1404e0ce0`… | one per game plugin; returns type_name `&str` |
| `Tunnet Crash Reporter` site | `0x14038cc60` | crash handler |

### What is hard
- **No symbols, no DWARF**, heavy inlining. Many strings (incl. config paths and
  the window title) are reached through **static pointer tables**, not code LEAs,
  so naive xref misses them.
- Game types are **not** in Bevy's `TypeRegistry` (saves use serde), so no
  reflection-based access to game components.
- `main` does not appear as a normal callable function; the Rust entry is passed
  to `lang_start`. Pinning `App::run` / `Schedule::run` requires more RE.

### Recoverable anchors for game functions
- Bevy stores `type_name` for every system/component/event; ~625 game symbols
  were recovered. Each game system's registration references its type_name, and
  each source file's panic `Location` lives in a `.rdata` table (e.g. 63 entries
  for `bevy_winit/src/lib.rs`). These give us offline **byte-pattern + xref
  signatures** to locate specific systems per build.

### Recommended path (MVP → full)
- **MVP (no Bevy ABI):** core hooks, by signature, the asset load path
  (`EmbeddedAssetIo::load_path_sync`), the save/load path (serde_json in
  `save.rs`), and one per-frame + one startup game system. Mods are scripts that
  register callbacks. Covers asset replacement, save/config/cheats, and many
  gameplay tweaks.
- **Full (Bevy ABI bridge):** locate and hook a schedule entry (`App::run` /
  `Schedule::run` / `World::run_schedule`) to obtain the `World` and inject a
  mod `Plugin` compiled against the exact Bevy 0.7 versions. Highest power;
  highest fragility (must match Bevy 0.7 layout/features).
- **Tooling note:** a reference Bevy 0.7 build for signature diffing is risky
  (Bevy 0.7 predates the installed Rust 1.97); prefer offline signatures derived
  from this binary + Bevy 0.7 source.

### Open questions
- Which Bevy 0.7 functions can be pinned reliably without a reference build?
- Exact `AssetIo` vtable location for `load_path_sync` hooking.
- Whether a stable per-frame game system exists with a simple signature.
- Scripting runtime choice: Lua (mlua) vs WASM (wasmtime) for mod scripts.

---

## 12. MVP hook plan (chosen) — hook-based, Lua mods

Decisions: **MVP hook-based first, then ECS bridge**; mods scripted in **Lua
(mlua)**. Modloader exe + injected `core.dll`; mods are data/scripts, never DLLs.

### Hook 1 — assets: detour `EmbeddedAssetIo::add_asset` @ `0x14081fa10`
Called **608×** during `EmbeddedAssetIo::preloaded()` (before `main` builds the
`App`), once per asset, with the asset path and its bytes. Detouring it lets us
substitute bytes by path at startup. Calling convention (Win x64):

```
rcx = self (&mut EmbeddedAssetIo)
rdx = path.ptr      r8 = path.len
r9  = data.ptr      [rsp+0x20] = data.len
```
Equivalent Rust: `fn(&mut self, path: &Path, data: &[u8])`.
A detour reads `path`, looks up a mod override, and calls the trampoline with a
leaked replacement `&'static [u8]` (or the original). No need to hook
`load_path_sync` for asset replacement.

### Hook 2 — per-frame: detour a Win32 message API
Bevy 0.7/winit pumps messages on the main thread every frame. Detour
`PeekMessageW` (user32) and run mod `on_frame` callbacks throttled to ~60 Hz.
This gives a reliable main-thread tick **without** any Bevy internals, and is
replaced/augmented later by the ECS bridge.

### Hook 3 — startup: first `add_asset` call or a one-shot flag in the frame hook
Mods get an `on_start` after assets are registered.

### Hook 4 — config/save: pre-launch file patching (no hook)
The loader/core runs before the game reads `%APPDATA%\tunnet\*.json|*.toml`, so
mods can patch saves/settings/keybinds on disk. Runtime save interception (file
API detours) is a later add-on.

### Deferred — ECS bridge
Later, pin `App::run` / `Schedule::run` / `World::run_schedule` to obtain the
`World` and inject a mod `Plugin` compiled against Bevy 0.7. Until then,
gameplay mods use the frame hook + any game-function detours located by
signature.

### Module layout (planned)
```
tunnet-modding/
  loader/        # modloader exe: CreateProcess(SUSPENDED) + inject core.dll
  core/          # injected cdylib: hooks, Lua runtime, C-ABI mod API
  sdk/           # Rust/Lua mod SDK + manifest schema
  mods/          # example mods
  analysis/      # RE tooling (this)
  data/          # recovered tables/symbols
  notes/         # this file
```

---

## 13. MVP implementation status — WORKING (2026-10-05)

Toolchain: `x86_64-pc-windows-gnu` + MinGW gcc 13.2 (`.cargo/config.toml`).

### Built and verified end-to-end
```
tunnet-loader.exe   launches tunnet.exe SUSPENDED (with --bypass-launcher),
                    injects core.dll via CreateRemoteThread(LoadLibraryW),
                    waits for the core "ready" event, then resumes.
core.dll            installs add_asset + PeekMessageW detours (retour),
                    embeds Lua 5.4 (mlua, vendored), loads mods.
mods/<name>/mod.lua Lua mod: tunnet.log/on_load/on_frame/override_asset.
```

### Startup race fix
The game can call `add_asset` before an async init thread registers overrides.
Handshake: loader creates `Local\TunnetCoreReady_<pid>` and waits (15 s) before
`ResumeThread`; the core sets it after hooks + mods are ready. The game's main
thread stays suspended the whole time, so overrides are always in place.

### Verified log (real run)
```
[core] add_asset hook installed @ 0x7ff6f6f3fa10
[core] PeekMessageW hook installed
[lua] example mod: loaded
[mods] override_asset textures/puzzled_squid.png <- .../mods/example/puzzled_squid.png (487 bytes)
[lua] example mod: on_load
[core] signalled loader: ready
[assets] override textures/puzzled_squid.png (487 bytes)   <-- hook substituted bytes
[lua] example mod: 60 frames (last dt=25.00 ms)            <-- per-frame Lua
```

### Notes / gotchas
- Run the game with `--bypass-launcher` (loader adds it) or it relaunches itself
  and the injected process is the wrong one.
- `add_asset` ABI: `rcx=self, rdx=path.ptr, r8=path.len, r9=data.ptr, [rsp+0x20]=data.len`.
- The detour addresses are RVAs (`0x81fa10`), resolved against the runtime module
  base (ASLR-safe).
- `PeekMessageW` tick is throttled to ~16 ms on the main thread.

### Next
- Save/config pre-launch patching; runtime file-API detours.
- ECS bridge (App/Schedule hook) for gameplay + new content + UI.
- Harden signatures against game updates (signature DB from this build).

---

## 14. ECS bridge — World captured (2026-10-05)

### Locating Bevy functions without symbols
`<Schedule as Stage>::run` (Bevy 0.7 `schedule/mod.rs`) contains a unique panic:
`` panic!("`NoAndCheckAgain` would loop infinitely in this situation.") ``.
That string literal lives in `.rdata` (VA `0x145265970`, referenced via a static
pointer, not a code LEA). Following the pointer to the code that loads it gives
the function at **`0x14221cd40`** = `<Schedule as Stage>::run(&mut self, world)`.

Its callers were then examined; **`App::update` = `0x14220ee60`**:

```
mov  %rcx,%rdi            ; rdi = &mut App
add  $0x50,%rcx           ; rcx = &mut App.schedule
lea  0xc0(%rdi),%r14      ; r14 = &mut App.world
mov  %r14,%rdx
call 0x14221cd40          ; Schedule::run(schedule, world)
... loop sub_apps, call runner(world, app)
```

So in this build:
- **`App::update` @ RVA `0x220ee60`**
- **`App.world` @ offset `0xc0`** (field order is compiler-reordered; do not
  trust Bevy source order)
- `App.schedule` @ offset `0x50`

`App::update` has exactly one caller (`0x140e92020`, the winit runner), i.e. once
per frame.

### Hook + API (implemented, verified)
- Detour `App::update` (RVA `0x220ee60`): capture `world = app + 0xc0`, store it,
  run Lua `on_update`, then call the trampoline (so mods run before the frame's
  systems).
- Lua API added: `tunnet.on_update(fn)`, `tunnet.frame()`, `tunnet.world_ptr()`,
  and `tunnet.mem.*` (read/write u8/u16/u32/u64/i32/f32/f64, `read_bytes`,
  `read_cstr`).

Verified run:
```
[core] App::update hook installed @ 0x7ff7489bee60
[core] first App::update; world @ 0x2092bd5af00
[lua] example mod: first ECS update; world @ 0x2092bd5af00 (byte0=0)
```

### Why typed access needs the component registry
- Game types are **not** in Bevy's reflection `TypeRegistry` (saves use serde).
- Rust `TypeId`s are derived from the crate's disambiguator, so we **cannot
  reconstruct** the game's `TypeId` for e.g. `tunnet::story::Story` from a
  separately compiled crate. `TypeId`-keyed resource lookup is therefore out.
- However, Bevy's `World` keeps a `Components` registry of every component type
  that systems use, storing each type's **name string** (e.g.
  `tunnet::story::Story`) and its `ComponentId`/`TypeId`. Game component/resource
  names are present there at runtime.
- Plan: reverse the `World`/`Components`/`Storages` layouts, enumerate the
  component registry by name, and access resources/components by `ComponentId`.
  This yields typed access without linking against the game's Bevy.

### Next
- Reverse `World.components` (name -> id) and `World.storages.resources`.
- Expose `tunnet.resource("tunnet::story::Story")` etc. and typed field access.
- Then entities/queries and UI.
- Save/config hooks and update-resilient signatures remain on the roadmap.

---

## 15. Component registry reversed (2026-10-05)

### Method
`World::resource::<T>` monomorphizations were located via the panic string
`` Requested resource {} does not exist in the `World`. `` (see
`analysis/find_resource_lookup.py`). Their disassembly gave the `Components`
HashMaps near `World+0x218`. Because Rust reorders fields, offsets were then
determined **empirically**: the core dumps `World[0..0x800]` plus one level of
heap (each readable pointer's first `0x200`/`0x40` bytes), validated with
`VirtualQuery` (`is_readable`), behind `TUNNET_DUMP_WORLD=1`
(`world.bin`, `world_deep.bin`; analyzer `analysis/analyze_world_deep.py`).

### Layout (this build)
- `World.components.components` (`Vec<ComponentInfo>`): header at **World+0x180**
  (ptr/cap/len at +0x180/+0x188/+0x190).
- Entry stride **0x50**. `ComponentInfo`:
  - `+0x00` `ComponentId` (usize index)
  - `+0x30` `descriptor.name` ptr, `+0x38` name len (empirical; fields are
    reordered, so Bevy source order is not usable)
  - `+0x40` `drop` fn pointer
- Bevy source (v0.7.0) for reference: `World { id, entities, components,
  archetypes, storages, bundles, removed_components, ... }`;
  `Components { components: Vec<ComponentInfo>, indices: HashMap<TypeId,usize>,
  resource_indices: HashMap<TypeId,usize> }`;
  `ComponentInfo { id, descriptor }`;
  `ComponentDescriptor { name: String, storage_type, is_send_and_sync,
  type_id: Option<TypeId>, layout, drop }`; `Storages { sparse_sets, tables }`
  (resources live in `Storages.tables`).

### API added
- `tunnet.components()` -> array of registered type names.
- `tunnet.component_id(name)` -> `ComponentId` index or nil.
- Verified: at the main menu, 127 types are registered, all engine types except
  `bevy_ecs::schedule::state::State<tunnet::state::GameState>`; the game's own
  components/resources register later (once a game starts), so they appear
  in-game.

### Next
- Reverse `Storages.tables` to turn a `ComponentId` into a resource data
  pointer: expose `tunnet.resource(name) -> ptr` and typed field access.
- Then entities/queries and UI; save/config hooks; update-resilient signatures.

---

## 16. Resource pointers — SOLVED via the game's own lookups (2026-10-05)

### Bevy 0.7 resource storage
Resources are **not** in `Storages`; they live in the special resource
archetype's `unique_components`:
`World.archetypes.resource().unique_components: SparseSet<ComponentId, Column>`.
- `Archetypes { archetypes: Vec<Archetype>, .. }`, `resource()` =
  `archetypes[ArchetypeId::RESOURCE]`.
- `Archetype { id, entities, edges, table_info, table_components,
  sparse_set_components, unique_components, components }`.
- `SparseSet { dense: Vec<V>, indices: Vec<I>, sparse: SparseArray<I, usize> }`.
- `Column { component_id, data: BlobVec, ticks }`.
- `BlobVec { item_layout, capacity, len, data, swap_scratch, drop }`.

### Accessor at RVA 0x225f810 (leaf)
Disassembly (called by `World::resource::<T>` monomorphizations):
```
mov  0x120(%rcx),%rax        ; X = [self+0x120]
cmp  %rdx,0x220(%rax)        ; if cid >= sparse_len -> null
mov  0x218(%rax),%rcx        ; sparse values ptr (Vec<Option<usize>>, 16B elems)
imul $0x58,0x8(%rcx,%rdx,16) ; dense index -> Column stride 0x58
mov  0x1e8(%rax),%r8         ; dense Vec<Column> ptr
mov  0x38(%r8,%rcx,1),%rcx   ; Column+0x38 = BlobVec.len
cmove %rcx,%rax              ; return 0 if empty, else &Column
```
Then the caller reads `Column+0x40` = `BlobVec.data` = the resource pointer.
So: **Column stride 0x58; len at +0x38; data at +0x40.**

### Why we cache instead of computing from the World
The accessor's `self` (arg0) is **not** the main `World` (`world_ptr`); hooking
`0x225f810` showed a constant arg0 different from `App.world`, i.e. it is called
on another world/self. Rather than pin `World -> resource archetype ->
unique_components` offsets, the core **hooks `0x225f810`** and records
`ComponentId -> Column.data` for every resource the game looks up (validated:
`len == 1`, readable heap pointer). This covers all resources the game actually
uses (e.g. `Time`, `Windows` every frame).

### API added
- `tunnet.resource(name) -> ptr` (0 if unknown/not yet accessed).
- Verified: `Time` (cid 8) -> `0x29d9c223560`, `Windows` (cid 41) ->
  `0x29d0d5fdc70`; hook log `ret=<Column> len=1 data=<heap ptr>`.

### Next
- Typed field access: reverse per-type field offsets (start with
  `tunnet::story::Story`, `tunnet::player::...`) or reverse
  `ComponentInfo.descriptor.layout`/`type_id` to auto-derive offsets.
- Entities/queries/spawning and UI; save/config hooks; update-resilient
  signatures.

---

## 17. Typed game state — credits + story unlocks (2026-10-05)

### Getting in-game (for testing)
The main menu was screenshotted to locate buttons. "Continue" is at ~(783, 644)
on a 3440x1440 screen; clicking it (`SetCursorPos` + `mouse_event`) loads the
last save. In-game the registry grows to **255 types**; `tunnet::story::Story`
is `ComponentId` 150. Game type names recovered include `tunnet::player::Body/
Head/Hand`, `tunnet::credits::Credits`, `tunnet::story::Story`,
`tunnet::settings::UserSettings/UserGameSettings`, `tunnet::input::Actions/
KeyBindings`, `tunnet::tools::Tool`, and many `Handles`/`AudioState` resources.

### Empirical field reversing
Dumped live `Story`/`Credits` memory via `tunnet.mem.read_bytes` and correlated
with the loaded save (`%APPDATA%\tunnet\slot_2.json`):
- `player.credits = 131`, `story.digging/relay/hub = true`, `filter = false`,
  `scan_short = true`, `scan_long = false`, `jetpack..companion = false`.
- **Credits**: value `131` found at `Credits + 0x20`.
- **Story unlocks**: the exact 13-bool run
  `digging,relay,hub,filter,scan_short,scan_long,jetpack,antivirus,sprint,
  optical_fiber,antenna,surface,companion` is contiguous at **Story+0x1c6**.
- Nearby (unverified): `shop_level`~+0x1b0, `page_no`~+0x1bc, `pages`~+0x1c0.
- Note: Rust reorders struct fields, so runtime order != save JSON order; the
  bools were grouped by the compiler, which is why they are contiguous.

### API added
- `tunnet.credits()` / `tunnet.set_credits(n)`.
- `tunnet.story_unlock(name)` / `tunnet.set_story_unlock(name, bool)`.
- `tunnet.read_resource(name, offset, kind)` /
  `tunnet.write_resource(name, offset, kind, value)` (`kind`: u8/u32/i32/f32).

Verified in-game:
```
credits=131 digging=true jetpack=false
after write: credits=999 jetpack=true
```

### Next
- Name more fields (shop_level, page_no, boss_phase, visited_chunks...), and
  player position via the `tunnet::player::Body` transform.
- Entities/queries/spawning and UI; save/config hooks; update-resilient
  signatures.

---

## 18. New assets — asset IO hook (2026-10-05)

### Goal
Let mods ship brand-new asset files (not just replace the 608 embedded ones).

### Hook: `EmbeddedAssetIo::load_path_sync` @ RVA 0x81fd20
Found as the function after `add_asset` that hashes the path via the same
hasher (`0x14081d470`) and does a hashbrown lookup on `self+0x20/0x38`.
Win x64 ABI (large `Result` return via sret):
```
rcx = sret (Result<Vec<u8>, AssetIoError>)
rdx = self (&EmbeddedAssetIo)
r8  = path.ptr   r9 = path.len
```
The hook:
1. records `self` (`EMBEDDED_IO`) for later manual loads,
2. if the path is a mod override and not yet inserted, inserts it by calling
   the **original `add_asset`** (via its detour trampoline) with leaked bytes,
3. calls the original `load_path_sync`.

This means any path the game requests resolves to a mod file, including paths
that were never in the embedded table.

### Manual load API
`tunnet.asset_bytes(path)`:
- ensures the override is inserted, then calls the original `load_path_sync`
  via the trampoline with an sret buffer,
- parses `Result<Vec<u8>, AssetIoError>`: **tag@0, len@8, ptr@0x10, cap@0x18**
  (observed), with a `(ptr,cap,len)` fallback,
- returns a Lua string (or nil).

Verified in-game:
```
[assets] inserted asset textures/example_new.png (487 bytes)
[lua] example mod: new asset bytes = 487
```

### Next
- Entity/archetype access: player position (via `tunnet::player::Body`
  transform) and spawning entities; then attach loaded assets to entities/UI
  (Bevy asset handles), enabling real new content.
- Save/config hooks; update-resilient signatures.
