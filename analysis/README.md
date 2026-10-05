# Analysis tooling

Python 3 scripts that reverse-engineer `tunnet.exe`: recover the embedded asset
table (608 assets), locate functions, and cross-reference strings. They are
build-specific but read the executable at runtime, so no game binary is stored
in this repo.

## Setup

- Python 3.8+
- `objdump` on `PATH` (only needed by `parse_iaa.py`; override with
  `TUNNET_OBJDUMP`)
- A copy of `tunnet.exe`

All scripts share `common.py` and accept the same flags:

| Flag | Env var | Default |
|---|---|---|
| `--exe PATH` | `TUNNET_EXE` | `./tunnet.exe`, then `<repo>/tunnet.exe` |
| `--data DIR` | `TUNNET_DATA` | `<repo>/data` (gitignored) |

Set the exe once and forget it:

```powershell
$env:TUNNET_EXE = "C:\Program Files (x86)\Steam\steamapps\common\Tunnet\tunnet.exe"
```

or pass it per call: `python analysis/scan_paths.py --exe "C:\...\tunnet.exe"`.

## Order to run them

Run the pipeline top to bottom. Each step writes into `data/`; later steps read
earlier outputs.

### 0. Recon (optional, fast)

```powershell
python analysis/scan_paths.py
```
Prints asset-like path strings by folder/extension. No files written.

### 1. Carve blobs and test the layout

```powershell
python analysis/map_assets.py
```
Carves PNG/OGG/GLB blobs by container format, reports counts and whether path
order lines up with blob order. Writes `data/asset_map.json`.

### 2. Refine (separate real assets from in-model textures)

```powershell
python analysis/map_assets2.py
```
Splits standalone assets from PNGs embedded inside `.glb` models and tests order
alignment per extension. Writes `data/asset_mapping.csv`,
`data/asset_summary.json`.

### 3. Locate `include_all_assets()` and pair path -> blob

```powershell
python analysis/find_include_all.py
```
Finds the generated asset-registration function via `.pdata` + RIP-relative
xrefs and pairs each path literal with its data blob. Writes
`data/asset_mapping_exact.csv`, `data/include_all_assets.json`.

### 4. Diagnose leftovers (optional)

```powershell
python analysis/analyze_unmapped.py
```
Reads `data/include_all_assets.json` and reports blobs that were not paired and
which functions reference them. Diagnostic only.

### 5. Recover the exact table (authoritative)

```powershell
python analysis/parse_iaa.py
```
If `data/iaa.asm` is missing it generates it with `objdump`, then parses the
`include_all_assets()` disassembly, tracking argument registers to recover every
`add_asset(path, data)` pair. Writes `data/asset_table.csv` and
`data/asset_table.json` (columns: `path`, `data_off`, `data_len`, `data_va`).

> The function range in `parse_iaa.py` (`0x1408202c0`..`0x140825aa5`) is for the
> current Steam build. On a different build, use `find_include_all.py` /
> `refs_raw.py` to find the new `include_all_assets()` range and update it.

### 6. Extract the assets

```powershell
python analysis/extract_assets.py
```
Reads `data/asset_table.json`, validates each container size, and writes all 608
assets to `assets_extracted/` (gitignored). Use `--dest DIR` to change the
destination.

### Full sequence

```powershell
python analysis/scan_paths.py
python analysis/map_assets.py
python analysis/map_assets2.py
python analysis/find_include_all.py
python analysis/analyze_unmapped.py
python analysis/parse_iaa.py
python analysis/extract_assets.py
```

Result: `data/asset_table.csv` (the asset list) and `assets_extracted/` (the
original files, useful as replacement bases).

## Cross-reference helpers (use ad hoc)

These are for locating code, not part of the linear pipeline.

| Tool | Purpose |
|---|---|
| `xref.py <pattern>...` | Functions that reference matching string literals (LEA + static pointer tables). |
| `xref_va.py <VA>...` | Code LEAs and static pointers that reference specific addresses. |
| `refs_raw.py <pattern>...` | Raw LEA reference instruction addresses for patterns. |
| `callers.py <VA>` | Direct callers (rel32 call/jmp) of an address, plus its `.pdata` range. |
| `pdata_lookup.py <VA>...` | Resolve VAs to their containing `.pdata` function. |
| `find_string.py <string>` | Exact (delimiter-bounded) occurrences of a string and their xrefs. |

Examples:

```powershell
python analysis/xref.py "tunnet::net::NetPlugin" "tunnet::map::MapPlugin"
python analysis/callers.py 0x14081fa10
python analysis/pdata_lookup.py 0x1404e0ce0
python analysis/find_string.py "--bypass-launcher"
```

See `notes/TUNNET_MODDING_NOTES.md` for the findings these tools produced.
