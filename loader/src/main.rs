//! Tunnet modloader.
//!
//! Launches `tunnet.exe` suspended, injects `core.dll` (the mod core), then
//! resumes the game. Mods are scripts/data loaded by the core; they are never
//! DLLs and Steam's files are never modified.

use std::ffi::{c_void, OsStr};
use std::os::windows::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::process::ExitCode;

use windows::core::{s, w, PCWSTR, PWSTR};
use windows::Win32::Foundation::CloseHandle;
use windows::Win32::System::Diagnostics::Debug::WriteProcessMemory;
use windows::Win32::System::LibraryLoader::{GetModuleHandleW, GetProcAddress};
use windows::Win32::System::Memory::{
    VirtualAllocEx, MEM_COMMIT, MEM_RESERVE, PAGE_READWRITE,
};
use windows::Win32::System::Threading::{
    CreateEventW, CreateProcessW, CreateRemoteThread, ResumeThread, TerminateProcess,
    WaitForSingleObject, CREATE_SUSPENDED, INFINITE, LPTHREAD_START_ROUTINE, PROCESS_INFORMATION,
    STARTUPINFOW,
};

fn wide(s: &OsStr) -> Vec<u16> {
    s.encode_wide().chain(std::iter::once(0)).collect()
}

struct Args {
    game: PathBuf,
    core: PathBuf,
    game_args: Vec<String>,
}

fn parse_args() -> Args {
    let mut game = PathBuf::from("tunnet.exe");
    let mut core = PathBuf::from("core.dll");
    let mut game_args = Vec::new();

    let mut it = std::env::args().skip(1);
    let mut passthrough = false;
    while let Some(a) = it.next() {
        if passthrough {
            game_args.push(a);
            continue;
        }
        match a.as_str() {
            "--" => passthrough = true,
            "--game" => {
                if let Some(v) = it.next() {
                    game = PathBuf::from(v);
                }
            }
            "--core" => {
                if let Some(v) = it.next() {
                    core = PathBuf::from(v);
                }
            }
            "-h" | "--help" => {
                println!(
                    "tunnet-loader [--game <path>] [--core <path>] [--] [game args...]\n\
                     \n\
                     Defaults: --game tunnet.exe --core core.dll (resolved next to this exe)"
                );
                std::process::exit(0);
            }
            other => game_args.push(other.to_string()),
        }
    }

    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|p| p.parent().map(Path::to_path_buf))
        .unwrap_or_else(|| PathBuf::from("."));
    if game == Path::new("tunnet.exe") {
        game = exe_dir.join("tunnet.exe");
    }
    if core == Path::new("core.dll") {
        core = exe_dir.join("core.dll");
    }
    if !game.exists() {
        let steam = PathBuf::from(r"G:\SteamLibrary\steamapps\common\Tunnet\tunnet.exe");
        if steam.exists() {
            game = steam;
        }
    }

    // The game relaunches itself via an internal launcher unless this flag is
    // present; without it the injected process is the wrong one.
    if !game_args.iter().any(|a| a == "--bypass-launcher") {
        game_args.insert(0, "--bypass-launcher".to_string());
    }

    Args {
        game,
        core,
        game_args,
    }
}

unsafe fn inject_dll(process: windows::Win32::Foundation::HANDLE, dll: &Path) -> windows::core::Result<()> {
    let dll_w = wide(dll.as_os_str());
    let nbytes = dll_w.len() * std::mem::size_of::<u16>();

    let remote = VirtualAllocEx(process, None, nbytes, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE);
    if remote.is_null() {
        return Err(windows::core::Error::from_win32());
    }

    WriteProcessMemory(process, remote, dll_w.as_ptr() as *const c_void, nbytes, None)?;

    let k32 = GetModuleHandleW(w!("kernel32.dll"))?;
    let load = GetProcAddress(k32, s!("LoadLibraryW"))
        .ok_or_else(windows::core::Error::from_win32)?;
    let start: LPTHREAD_START_ROUTINE = std::mem::transmute(load);

    let thread = CreateRemoteThread(process, None, 0, start, Some(remote), 0, None)?;
    WaitForSingleObject(thread, INFINITE);
    let _ = CloseHandle(thread);
    Ok(())
}

fn run(args: &Args) -> Result<(), String> {
    if !args.game.exists() {
        return Err(format!("game not found: {}", args.game.display()));
    }
    if !args.core.exists() {
        return Err(format!("core not found: {}", args.core.display()));
    }

    let mut cmdline = format!("\"{}\"", args.game.display());
    for a in &args.game_args {
        cmdline.push(' ');
        cmdline.push_str(a);
    }
    let mut cmdline_w: Vec<u16> = OsStr::new(&cmdline)
        .encode_wide()
        .chain(std::iter::once(0))
        .collect();

    let cwd = args
        .game
        .parent()
        .map(|p| wide(p.as_os_str()))
        .unwrap_or_default();
    let cwd_ptr = if cwd.is_empty() {
        PCWSTR::null()
    } else {
        PCWSTR(cwd.as_ptr())
    };

    unsafe {
        let mut si = STARTUPINFOW::default();
        si.cb = std::mem::size_of::<STARTUPINFOW>() as u32;
        let mut pi = PROCESS_INFORMATION::default();

        CreateProcessW(
            PCWSTR::null(),
            PWSTR(cmdline_w.as_mut_ptr()),
            None,
            None,
            false,
            CREATE_SUSPENDED,
            None,
            cwd_ptr,
            &si,
            &mut pi,
        )
        .map_err(|e| format!("CreateProcessW failed: {e}"))?;

        // Handshake: the core signals this event once hooks + mods are ready.
        // We keep the game suspended until then so asset overrides are in place
        // before the game registers its embedded assets.
        let event_name = format!("Local\\TunnetCoreReady_{}", pi.dwProcessId);
        let event_w: Vec<u16> = OsStr::new(&event_name)
            .encode_wide()
            .chain(std::iter::once(0))
            .collect();
        let ready = CreateEventW(None, true, false, PCWSTR(event_w.as_ptr())).ok();

        if let Err(e) = inject_dll(pi.hProcess, &args.core) {
            eprintln!("[loader] injection failed: {e}");
            let _ = TerminateProcess(pi.hProcess, 1);
            let _ = CloseHandle(pi.hThread);
            let _ = CloseHandle(pi.hProcess);
            return Err("injection failed".into());
        }
        println!("[loader] injected {}", args.core.display());

        if let Some(ev) = ready {
            let r = WaitForSingleObject(ev, 15_000);
            if r == windows::Win32::Foundation::WAIT_OBJECT_0 {
                println!("[loader] core ready");
            } else {
                eprintln!("[loader] core ready timeout; resuming anyway");
            }
            let _ = CloseHandle(ev);
        }

        let _ = ResumeThread(pi.hThread);
        let _ = CloseHandle(pi.hThread);
        let _ = CloseHandle(pi.hProcess);
    }
    Ok(())
}

fn main() -> ExitCode {
    let args = parse_args();
    match run(&args) {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("[loader] {e}");
            ExitCode::FAILURE
        }
    }
}
