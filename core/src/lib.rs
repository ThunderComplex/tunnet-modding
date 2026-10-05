//! Tunnet mod core (`core.dll`).
//!
//! Injected into `tunnet.exe` by the modloader. Installs the MVP hooks:
//!   * `EmbeddedAssetIo::add_asset` (RVA 0x81fa10) — path-keyed asset override
//!   * `PeekMessageW` (user32) — main-thread per-frame tick
//!
//! Mods are Lua scripts loaded from `<core dir>/mods` (see `mods/README`).

use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU64, AtomicUsize, Ordering};
use std::sync::Mutex;

use mlua::{Function, Lua, Table};
use once_cell::sync::Lazy;
use retour::GenericDetour;
use windows::core::{s, w, PCWSTR};
use windows::Win32::Foundation::{BOOL, CloseHandle, FALSE, HMODULE, TRUE};
use windows::Win32::System::LibraryLoader::{
    GetModuleFileNameW, GetModuleHandleW, GetProcAddress, LoadLibraryW,
};
use windows::Win32::System::SystemInformation::GetSystemTimeAsFileTime;
use windows::Win32::System::Threading::{
    GetCurrentProcessId, OpenEventW, SetEvent, EVENT_MODIFY_STATE,
};
use windows::Win32::UI::WindowsAndMessaging::MSG;

// RVAs in this exact build (see notes sections 11/12).
const RVA_ADD_ASSET: usize = 0x81fa10;
// ECS bridge: `bevy_app::App::update` and the offset of `App.world` (the first
// thing it passes to `Schedule::run`). See notes section 14.
const RVA_APP_UPDATE: usize = 0x220ee60;
const APP_WORLD_OFFSET: usize = 0xc0;

static CORE_DIR: Lazy<Mutex<PathBuf>> = Lazy::new(|| Mutex::new(PathBuf::new()));
static LOG_READY: AtomicBool = AtomicBool::new(false);
static FRAME_COUNT: AtomicU64 = AtomicU64::new(0);
static LAST_TICK_MS: AtomicU64 = AtomicU64::new(0);

static LUA: Lazy<Mutex<Option<Lua>>> = Lazy::new(|| Mutex::new(None));

/// Directory of the mod currently being loaded / whose callback is running.
/// `override_asset` resolves relative paths against this and cannot escape it.
static CURRENT_MOD_DIR: Lazy<Mutex<Option<PathBuf>>> = Lazy::new(|| Mutex::new(None));

// ----------------------------------------------------------------- logging
fn log(msg: &str) {
    use std::io::Write;
    if !LOG_READY.load(Ordering::Relaxed) {
        return;
    }
    if let Ok(dir) = CORE_DIR.lock() {
        let path = dir.join("core.log");
        if let Ok(mut f) = std::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(path)
        {
            let _ = writeln!(f, "{msg}");
        }
    }
}

// ------------------------------------------------------------ asset overrides
type AddAssetFn = unsafe extern "C" fn(*mut c_void, *const u8, usize, *const u8, usize);
static ADD_ASSET: Lazy<Mutex<Option<GenericDetour<AddAssetFn>>>> =
    Lazy::new(|| Mutex::new(None));

/// (logical path, data ptr as usize, data len)
static ASSET_OVERRIDES: Lazy<Mutex<Vec<(String, usize, usize)>>> =
    Lazy::new(|| Mutex::new(Vec::new()));

fn lookup_override(path: &str) -> Option<(*const u8, usize)> {
    if let Ok(map) = ASSET_OVERRIDES.lock() {
        for (p, ptr, len) in map.iter() {
            if p == path {
                return Some((*ptr as *const u8, *len));
            }
        }
    }
    None
}

unsafe extern "C" fn add_asset_hook(
    this: *mut c_void,
    path_ptr: *const u8,
    path_len: usize,
    data_ptr: *const u8,
    data_len: usize,
) {
    let path = std::str::from_utf8(std::slice::from_raw_parts(path_ptr, path_len)).unwrap_or("");
    let (dptr, dlen) = match lookup_override(path) {
        Some((ptr, len)) => {
            log(&format!("[assets] override {path} ({len} bytes)"));
            (ptr, len)
        }
        None => (data_ptr, data_len),
    };
    if let Ok(guard) = ADD_ASSET.lock() {
        if let Some(detour) = guard.as_ref() {
            let _ = detour.call(this, path_ptr, path_len, dptr, dlen);
        }
    }
}

// -------------------------------------------------------------- frame hook
type PeekMessageFn =
    unsafe extern "system" fn(*mut MSG, windows::Win32::Foundation::HWND, u32, u32, u32) -> BOOL;
static PEEK_MSG: Lazy<Mutex<Option<GenericDetour<PeekMessageFn>>>> =
    Lazy::new(|| Mutex::new(None));

fn now_ms() -> u64 {
    unsafe {
        let ft = GetSystemTimeAsFileTime();
        let v = ((ft.dwHighDateTime as u64) << 32) | ft.dwLowDateTime as u64;
        v / 10_000
    }
}

unsafe extern "system" fn peek_message_hook(
    msg: *mut MSG,
    hwnd: windows::Win32::Foundation::HWND,
    min: u32,
    max: u32,
    remove: u32,
) -> BOOL {
    let t = now_ms();
    let last = LAST_TICK_MS.load(Ordering::Relaxed);
    if t.saturating_sub(last) >= 16 {
        LAST_TICK_MS.store(t, Ordering::Relaxed);
        FRAME_COUNT.fetch_add(1, Ordering::Relaxed);
        let dt = (t.saturating_sub(last)) as f64;
        on_frame(dt);
    }
    if let Ok(guard) = PEEK_MSG.lock() {
        if let Some(detour) = guard.as_ref() {
            return detour.call(msg, hwnd, min, max, remove);
        }
    }
    FALSE
}

fn on_frame(dt_ms: f64) {
    let n = FRAME_COUNT.load(Ordering::Relaxed);
    if n == 1 {
        log("[core] first frame");
    }
    if let Ok(mut guard) = LUA.lock() {
        if let Some(lua) = guard.as_mut() {
            let _ = dispatch(lua, "_frame", dt_ms);
        }
    }
}

// ---------------------------------------------------------------- ECS bridge
// Hook `bevy_app::App::update` (called once per frame by the winit runner).
// `App.world` is the field passed to `Schedule::run`, at `APP_WORLD_OFFSET`.
type AppUpdateFn = unsafe extern "C" fn(*mut c_void);
static APP_UPDATE: Lazy<Mutex<Option<GenericDetour<AppUpdateFn>>>> =
    Lazy::new(|| Mutex::new(None));
static WORLD_PTR: AtomicUsize = AtomicUsize::new(0);
static UPDATE_COUNT: AtomicU64 = AtomicU64::new(0);

unsafe extern "C" fn app_update_hook(app: *mut c_void) {
    let world = (app as usize).wrapping_add(APP_WORLD_OFFSET);
    WORLD_PTR.store(world, Ordering::Relaxed);
    let n = UPDATE_COUNT.fetch_add(1, Ordering::Relaxed) + 1;
    if n == 1 {
        log(&format!("[core] first App::update; world @ {:#x}", world));
    }
    // Run mod callbacks before the game's systems for this frame.
    on_update();
    if let Ok(guard) = APP_UPDATE.lock() {
        if let Some(detour) = guard.as_ref() {
            let _ = detour.call(app);
        }
    }
}

fn on_update() {
    if let Ok(mut guard) = LUA.lock() {
        if let Some(lua) = guard.as_mut() {
            let _ = dispatch(lua, "_update", 0.0);
        }
    }
}

fn dispatch(lua: &Lua, table: &str, dt_ms: f64) -> mlua::Result<()> {
    let tunnet: Table = lua.globals().get("tunnet")?;
    let cbs: Table = tunnet.get(table)?;
    for pair in cbs.pairs::<i64, Table>() {
        let (_, entry) = pair?;
        let dir: String = entry.get("dir").unwrap_or_default();
        let f: Function = entry.get("fn")?;
        // Scope override_asset to the mod that registered this callback.
        if let Ok(mut cur) = CURRENT_MOD_DIR.lock() {
            *cur = if dir.is_empty() {
                None
            } else {
                Some(PathBuf::from(&dir))
            };
        }
        let res = if table == "_frame" {
            f.call::<()>(dt_ms)
        } else {
            f.call::<()>(())
        };
        if let Err(e) = res {
            log(&format!("[mods] {table} callback error: {e}"));
        }
    }
    Ok(())
}

// ------------------------------------------------------------------ mods
fn mods_dir() -> PathBuf {
    if let Ok(d) = std::env::var("TUNNET_MODS") {
        if !d.is_empty() {
            return PathBuf::from(d);
        }
    }
    CORE_DIR
        .lock()
        .map(|d| d.join("mods"))
        .unwrap_or_else(|_| PathBuf::from("mods"))
}

fn current_mod_dir_string() -> String {
    CURRENT_MOD_DIR
        .lock()
        .ok()
        .and_then(|d| d.clone())
        .map(|p| p.to_string_lossy().to_string())
        .unwrap_or_default()
}

fn load_mods() {
    let mods_dir = mods_dir();
    if !mods_dir.is_dir() {
        log(&format!("[mods] no mods dir at {}", mods_dir.display()));
        return;
    }

    let lua = Lua::new();

    // Build the `tunnet` API table.
    let api = match lua.create_table() {
        Ok(t) => t,
        Err(e) => {
            log(&format!("[mods] create_table failed: {e}"));
            return;
        }
    };

    let _ = api.set(
        "log",
        lua.create_function(|_, msg: String| {
            log(&format!("[lua] {msg}"));
            Ok(())
        })
        .unwrap(),
    );

    let _ = api.set(
        "override_asset",
        lua.create_function(|_, (logical, file): (String, String)| {
            // Resolve strictly inside the calling mod's own directory.
            let base = CURRENT_MOD_DIR
                .lock()
                .ok()
                .and_then(|d| d.clone())
                .ok_or_else(|| {
                    mlua::Error::external(
                        "override_asset called outside of a mod (call it at load time)",
                    )
                })?;
            if std::path::Path::new(&file).is_absolute() {
                return Err(mlua::Error::external(
                    "override_asset: file must be relative to the mod directory",
                ));
            }
            let candidate = base.join(&file);
            let canon = candidate.canonicalize().map_err(|e| {
                mlua::Error::external(format!("cannot open {}: {e}", candidate.display()))
            })?;
            let base_canon = base.canonicalize().map_err(|e| {
                mlua::Error::external(format!("cannot resolve mod directory: {e}"))
            })?;
            if !canon.starts_with(&base_canon) {
                return Err(mlua::Error::external(
                    "override_asset: path escapes the mod directory",
                ));
            }
            match std::fs::read(&canon) {
                Ok(bytes) => {
                    let boxed = bytes.into_boxed_slice();
                    let len = boxed.len();
                    let leaked: &'static mut [u8] = Box::leak(boxed);
                    let ptr = leaked.as_ptr() as usize;
                    if let Ok(mut map) = ASSET_OVERRIDES.lock() {
                        map.retain(|(p, _, _)| p != &logical);
                        map.push((logical.clone(), ptr, len));
                    }
                    log(&format!(
                        "[mods] override_asset {logical} <- {} ({len} bytes)",
                        canon.display()
                    ));
                    Ok(())
                }
                Err(e) => Err(mlua::Error::external(format!(
                    "cannot read {}: {e}",
                    canon.display()
                ))),
            }
        })
        .unwrap(),
    );

    let load_cbs = lua.create_table().unwrap();
    let frame_cbs = lua.create_table().unwrap();
    let update_cbs = lua.create_table().unwrap();
    let _ = api.set("_load", load_cbs);
    let _ = api.set("_frame", frame_cbs);
    let _ = api.set("_update", update_cbs);

    let _ = api.set(
        "on_load",
        lua.create_function(|lua, f: Function| {
            let tunnet: Table = lua.globals().get("tunnet")?;
            let cbs: Table = tunnet.get("_load")?;
            let entry = lua.create_table()?;
            entry.set("dir", current_mod_dir_string())?;
            entry.set("fn", f)?;
            cbs.set(cbs.len()? + 1, entry)
        })
        .unwrap(),
    );
    let _ = api.set(
        "on_frame",
        lua.create_function(|lua, f: Function| {
            let tunnet: Table = lua.globals().get("tunnet")?;
            let cbs: Table = tunnet.get("_frame")?;
            let entry = lua.create_table()?;
            entry.set("dir", current_mod_dir_string())?;
            entry.set("fn", f)?;
            cbs.set(cbs.len()? + 1, entry)
        })
        .unwrap(),
    );
    let _ = api.set(
        "on_update",
        lua.create_function(|lua, f: Function| {
            let tunnet: Table = lua.globals().get("tunnet")?;
            let cbs: Table = tunnet.get("_update")?;
            let entry = lua.create_table()?;
            entry.set("dir", current_mod_dir_string())?;
            entry.set("fn", f)?;
            cbs.set(cbs.len()? + 1, entry)
        })
        .unwrap(),
    );
    // ECS bridge accessors.
    let _ = api.set(
        "world_ptr",
        lua.create_function(|_, ()| Ok(WORLD_PTR.load(Ordering::Relaxed) as i64))
            .unwrap(),
    );
    let _ = api.set(
        "frame",
        lua.create_function(|_, ()| Ok(UPDATE_COUNT.load(Ordering::Relaxed) as i64)).unwrap(),
    );

    // Low-level memory access. Advanced/dangerous: used to build typed ECS
    // accessors and to inspect the World. Invalid addresses will crash.
    let mem = lua.create_table().unwrap();
    macro_rules! mem_read {
        ($name:literal, $ty:ty) => {
            let _ = mem.set(
                $name,
                lua.create_function(|_, a: i64| unsafe {
                    Ok(std::ptr::read_unaligned(a as usize as *const $ty))
                })
                .unwrap(),
            );
        };
    }
    macro_rules! mem_write {
        ($name:literal, $ty:ty) => {
            let _ = mem.set(
                $name,
                lua.create_function(|_, (a, v): (i64, $ty)| unsafe {
                    std::ptr::write_unaligned(a as usize as *mut $ty, v);
                    Ok(())
                })
                .unwrap(),
            );
        };
    }
    mem_read!("read_u8", u8);
    mem_read!("read_u16", u16);
    mem_read!("read_u32", u32);
    mem_read!("read_u64", u64);
    mem_read!("read_i32", i32);
    mem_read!("read_f32", f32);
    mem_read!("read_f64", f64);
    mem_write!("write_u8", u8);
    mem_write!("write_u32", u32);
    mem_write!("write_u64", u64);
    mem_write!("write_f32", f32);
    let _ = mem.set(
        "read_bytes",
        lua.create_function(|lua, (a, len): (i64, usize)| {
            let s = unsafe { std::slice::from_raw_parts(a as usize as *const u8, len) };
            lua.create_string(s)
        })
        .unwrap(),
    );
    let _ = mem.set(
        "read_cstr",
        lua.create_function(|_, a: i64| {
            let p = a as usize as *const u8;
            let mut n = 0usize;
            unsafe {
                while n < 4096 && *p.add(n) != 0 {
                    n += 1;
                }
                let s = std::slice::from_raw_parts(p, n);
                Ok(String::from_utf8_lossy(s).into_owned())
            }
        })
        .unwrap(),
    );
    let _ = api.set("mem", mem);

    let _ = lua.globals().set("tunnet", api);

    // Load mods: each `mods/<name>/mod.lua`, plus flat `mods/*.lua`.
    let mut files: Vec<PathBuf> = Vec::new();
    if let Ok(rd) = std::fs::read_dir(&mods_dir) {
        for e in rd.flatten() {
            let p = e.path();
            if p.is_dir() {
                let m = p.join("mod.lua");
                if m.is_file() {
                    files.push(m);
                }
            } else if p.extension().map(|x| x == "lua").unwrap_or(false) {
                files.push(p);
            }
        }
    }
    files.sort();

    for f in &files {
        if let Ok(mut cur) = CURRENT_MOD_DIR.lock() {
            *cur = f.parent().map(|p| p.to_path_buf());
        }
        match std::fs::read_to_string(f) {
            Ok(src) => match lua.load(&src).set_name(f.to_string_lossy()).exec() {
                Ok(()) => log(&format!("[mods] loaded {}", f.display())),
                Err(e) => log(&format!("[mods] error in {}: {e}", f.display())),
            },
            Err(e) => log(&format!("[mods] cannot read {}: {e}", f.display())),
        }
    }
    if let Ok(mut cur) = CURRENT_MOD_DIR.lock() {
        *cur = None;
    }

    // Fire on_load callbacks.
    if let Err(e) = dispatch(&lua, "_load", 0.0) {
        log(&format!("[mods] on_load dispatch error: {e}"));
    }

    log(&format!("[mods] {} mod file(s) loaded", files.len()));
    *LUA.lock().unwrap() = Some(lua);
}

// ---------------------------------------------------------------- install
unsafe fn module_base() -> usize {
    GetModuleHandleW(PCWSTR::null())
        .map(|h| h.0 as usize)
        .unwrap_or(0)
}

unsafe fn install_asset_hook() {
    let base = module_base();
    let target = (base + RVA_ADD_ASSET) as *const ();
    let orig: AddAssetFn = std::mem::transmute(target);
    match GenericDetour::<AddAssetFn>::new(orig, add_asset_hook) {
        Ok(d) => {
            if let Err(e) = d.enable() {
                log(&format!("[core] add_asset enable failed: {e}"));
            } else {
                log(&format!(
                    "[core] add_asset hook installed @ {:#x}",
                    target as usize
                ));
                *ADD_ASSET.lock().unwrap() = Some(d);
            }
        }
        Err(e) => log(&format!("[core] add_asset detour failed: {e}")),
    }
}

unsafe fn install_frame_hook() {
    let user32 = LoadLibraryW(w!("user32.dll")).unwrap_or_default();
    let Some(proc) = GetProcAddress(user32, s!("PeekMessageW")) else {
        log("[core] PeekMessageW not found");
        return;
    };
    let target = proc as usize as *const ();
    let orig: PeekMessageFn = std::mem::transmute(target);
    match GenericDetour::<PeekMessageFn>::new(orig, peek_message_hook) {
        Ok(d) => {
            if let Err(e) = d.enable() {
                log(&format!("[core] PeekMessageW enable failed: {e}"));
            } else {
                log("[core] PeekMessageW hook installed");
                *PEEK_MSG.lock().unwrap() = Some(d);
            }
        }
        Err(e) => log(&format!("[core] PeekMessageW detour failed: {e}")),
    }
}

unsafe fn install_update_hook() {
    let base = module_base();
    let target = (base + RVA_APP_UPDATE) as *const ();
    let orig: AppUpdateFn = std::mem::transmute(target);
    match GenericDetour::<AppUpdateFn>::new(orig, app_update_hook) {
        Ok(d) => {
            if let Err(e) = d.enable() {
                log(&format!("[core] App::update enable failed: {e}"));
            } else {
                log(&format!(
                    "[core] App::update hook installed @ {:#x}",
                    target as usize
                ));
                *APP_UPDATE.lock().unwrap() = Some(d);
            }
        }
        Err(e) => log(&format!("[core] App::update detour failed: {e}")),
    }
}

fn core_dir_from_module(module: HMODULE) -> PathBuf {
    let mut buf = vec![0u16; 1024];
    let n = unsafe { GetModuleFileNameW(module, &mut buf) } as usize;
    if n == 0 {
        return PathBuf::from(".");
    }
    let s = String::from_utf16_lossy(&buf[..n]);
    PathBuf::from(s)
        .parent()
        .map(|p| p.to_path_buf())
        .unwrap_or_else(|| PathBuf::from("."))
}

fn signal_ready() {
    unsafe {
        let pid = GetCurrentProcessId();
        let name = format!("Local\\TunnetCoreReady_{pid}");
        let name_w: Vec<u16> = std::ffi::OsStr::new(&name)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();
        if let Ok(ev) = OpenEventW(EVENT_MODIFY_STATE, false, PCWSTR(name_w.as_ptr())) {
            let _ = SetEvent(ev);
            let _ = CloseHandle(ev);
            log("[core] signalled loader: ready");
        } else {
            log("[core] ready event not found");
        }
    }
}

unsafe fn init(module_usize: usize) {
    let module = HMODULE(module_usize as *mut c_void);
    *CORE_DIR.lock().unwrap() = core_dir_from_module(module);
    LOG_READY.store(true, Ordering::Relaxed);
    log("==================== tunnet-core attach ====================");
    log(&format!("[core] module base = {:#x}", module_base()));
    install_asset_hook();
    install_frame_hook();
    install_update_hook();
    load_mods();
    log("[core] init complete");
    signal_ready();
}

// ----------------------------------------------------------------- DllMain
#[no_mangle]
#[allow(non_snake_case)]
pub extern "system" fn DllMain(module: HMODULE, reason: u32, _reserved: *mut c_void) -> BOOL {
    const DLL_PROCESS_ATTACH: u32 = 1;
    if reason == DLL_PROCESS_ATTACH {
        let m = module.0 as usize;
        std::thread::spawn(move || unsafe { init(m) });
    }
    TRUE
}
