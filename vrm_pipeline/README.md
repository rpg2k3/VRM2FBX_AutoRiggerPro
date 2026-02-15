# VRM to FBX Batch Pipeline

Batch-converts `.vrm` avatar files into Cascadeur-ready `.fbx` files using Blender 4.1.1, the VRM Addon for Blender, and Auto-Rig Pro.

## Prerequisites

| Component | Version | Notes |
|-----------|---------|-------|
| Blender | 4.1.1 (portable zip) | Extracted to `D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\` |
| VRM Addon for Blender | Latest | [GitHub](https://github.com/saturday06/VRM-Addon-for-Blender) |
| Auto-Rig Pro | Full version | [Blender Market](https://blendermarket.com/products/auto-rig-pro) |

## Setup

### 1. Install Blender (Portable)

Extract the Blender 4.1.1 portable zip so that the executable is at:
```
D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\blender.exe
```

### 2. Install VRM Addon

1. Open Blender (double-click `blender.exe`).
2. Go to **Edit > Preferences > Add-ons**.
3. Click **Install...** and select the VRM addon `.zip` file.
4. Enable the addon by checking the box next to **Import-Export: VRM format**.
5. Click **Save Preferences**.

### 3. Install Auto-Rig Pro

1. In Blender, go to **Edit > Preferences > Add-ons**.
2. Click **Install...** and select the Auto-Rig Pro `.zip` file.
3. Enable the addon by checking the box next to **Rigging: Auto-Rig Pro**.
4. Click **Save Preferences**.

### 4. Verify Installation

Run the diagnostic script to confirm both addons are installed and their operators are registered:

```bat
"D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\blender.exe" --background --python dump_ops.py
```

You should see operators listed under `vrm`, `arp`, `export`, and `fbx` categories.

## Default Folder Structure

By default, all folders are **inside the project directory** (next to `run_vrm_to_fbx.bat`):

```
vrm_pipeline\
    run_vrm_to_fbx.bat
    vrm_to_fbx_batch.py
    dump_ops.py
    README.md
    vrm_in\              <- place .vrm files here
    fbx_out\             <- exported .fbx files appear here
    vrm_done\            <- successfully processed .vrm files are moved here
    vrm_failed\          <- failed .vrm files are moved here
```

No configuration is needed. Just drop `.vrm` files into `vrm_in\` and run the bat.

## Usage

### Basic (double-click)

Double-click `run_vrm_to_fbx.bat`. It will automatically open a **persistent console window** that stays open after the pipeline finishes (or if any error occurs), so you can always read the output. Press any key to close the window when done.

```bat
run_vrm_to_fbx.bat
```

This launches Blender **with UI** (the default), which is **required** for Auto-Rig Pro operators. Blender will open a visible window, run the pipeline, and close when done.

### Headless mode

```bat
run_vrm_to_fbx.bat --headless
```

Runs Blender in background mode (no window). **ARP operators will not work** in this mode — files will be moved to `vrm_failed\` with an explanatory error in the log. This mode is only useful for testing VRM import/export without ARP.

### Override with custom paths

```bat
run_vrm_to_fbx.bat "D:\some\input" "D:\some\output"
run_vrm_to_fbx.bat --headless "D:\some\input" "D:\some\output"
```

When custom paths are provided, `vrm_done` and `vrm_failed` still default to the project directory.

### Logs

Two types of log files are generated each run:

| Log | Location | Contents |
|-----|----------|----------|
| `bat_debug_log_*.txt` | Project root (next to `.bat`) | BAT-level debug output: resolved paths, Blender command line, exit codes |
| `vrm_pipeline_*.log` | `fbx_out\` | Python-level pipeline log: per-file import/rig/export details |

Both logs are timestamped so previous runs are never overwritten.

### What Happens

1. The script scans the input directory for all `.vrm` files.
2. For each file, Blender (with UI) will:
   - Clean the scene (delete all objects, purge orphan data)
   - Import the VRM model
   - Identify the main armature and mesh
   - Apply transforms
   - Run Auto-Rig Pro: auto_scale, guess_markers, match_to_rig, bind_to_rig
   - Export a Cascadeur-compatible `.fbx`
3. Successfully processed `.vrm` files are moved to `vrm_done\`.
4. Failed `.vrm` files are moved to `vrm_failed\`.
5. A timestamped log file is written to the output directory.

### Output Structure

```
vrm_pipeline\
    bat_debug_log_20260215_153022.txt
    fbx_out\
        default-female.fbx
        default-male.fbx
        vrm_pipeline_20260215_153022.log
    vrm_done\
        default-female.vrm
        default-male.vrm
```

## Troubleshooting

### Blender path is invalid

**Symptom:** `ERROR: Blender executable not found`

**Fix:** Verify Blender is extracted to the correct path:
```
D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\blender.exe
```
Open a command prompt and run:
```bat
"D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\blender.exe" --version
```
If this fails, re-extract the Blender portable zip to the correct location.

### VRM addon is missing

**Symptom:** `Operator bpy.ops.import_scene.vrm not found` in the log.

**Fix:**
1. Open Blender normally (with GUI).
2. Go to **Edit > Preferences > Add-ons**.
3. Search for "VRM". If not listed, install it.
4. Make sure the checkbox is **enabled**.
5. Click **Save Preferences**.
6. Run `dump_ops.py` to verify:
   ```bat
   "D:\DevTools\blender 4.1\blender-4.1.1-windows-x64\blender.exe" --background --python dump_ops.py
   ```

### Auto-Rig Pro fails

**Symptom:** `Missing ARP operators` or `auto_scale failed` in the log.

**Possible causes and fixes:**

- **ARP not installed:** Install and enable it via Blender preferences, then save preferences.
- **ARP version mismatch:** Some ARP versions register operators differently. Run `dump_ops.py` and look for any `arp` operators. If they exist under different names, the script may need updating.
- **Armature incompatible:** ARP's `guess_markers()` works best with humanoid skeletons that use standard bone naming conventions. Non-standard VRM rigs (e.g., animal avatars, mechanical rigs) will likely fail.
- **Running in headless mode:** ARP requires a real Blender UI context. If you see `ARP requires UI mode` in the log, remove the `--headless` flag. The default (no flag) runs with UI, which is correct.
- **Context error:** ARP operators require specific object selection states. The script handles this automatically, but if you see context errors, ensure no other Blender instances are running.

### FBX export fails

**Symptom:** `FBX export exception` in the log.

**Possible causes and fixes:**

- **Output path permissions:** Make sure the output directory is writable. Try a path without spaces or special characters.
- **Disk space:** Verify there is sufficient disk space in the output directory.
- **Corrupted scene state:** If ARP partially completed, the scene may be in an unexpected state. Check the log for earlier warnings. The specific VRM file may be incompatible.

### Pipeline runs but produces bad FBX

**Possible causes:**

- **Wrong axis orientation:** The script exports with `-Z` forward and `Y` up (standard for Cascadeur). If your target application expects different axes, modify the `axis_forward` and `axis_up` parameters in `export_fbx()`.
- **Missing bones:** `use_armature_deform_only=True` strips non-deform bones. If Cascadeur needs additional bones, set this to `False` in the export call.
- **Scale issues:** The script applies `apply_unit_scale=True`. If your model appears at the wrong scale in Cascadeur, check the VRM's original scale units.

### All files end up in the "failed" folder

**Fix:** Check the log file in the output directory for specific error messages. Common causes:
- Make sure you are **not** using `--headless` mode — ARP requires UI.
- Both addons need to be enabled and saved in preferences so they persist across sessions.
- The VRM files may be corrupt or use an unsupported VRM version.
- Run `dump_ops.py` to verify your environment is correctly configured.

## File Reference

| File | Purpose |
|------|---------|
| `run_vrm_to_fbx.bat` | Windows batch entry point; validates paths, opens persistent console, writes debug log, launches Blender |
| `vrm_to_fbx_batch.py` | Main pipeline script; runs inside Blender's Python environment |
| `dump_ops.py` | Diagnostic tool; lists relevant operators and addon versions |
| `README.md` | This documentation file |
