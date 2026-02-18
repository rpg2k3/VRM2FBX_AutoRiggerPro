# VRM to FBX/GLB/DAE/OBJ Batch Pipeline

Batch-converts `.vrm` avatar files into `.fbx` (with embedded textures/skins), `.glb`, `.dae` (COLLADA) and `.obj` (Wavefront) files using Blender 4.1.1, the VRM Addon for Blender, and Auto-Rig Pro.

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
    fbx_out\             <- exported .fbx, .glb, .dae and .obj files appear here
    vrm_done\            <- successfully processed .vrm files are moved here
    vrm_failed\          <- failed .vrm files are moved here
```

No configuration is needed. Just drop `.vrm` files into `vrm_in\` and run the bat.

## Usage

### UI mode (recommended for ARP)

Double-click `run_vrm_to_fbx.bat` or run:

```bat
run_vrm_to_fbx.bat
```

This launches Blender **with UI** (default): a visible window opens, and Auto-Rig Pro can run. The batch opens a **persistent console** so you can read the output; press any key to close it when done. Use UI mode when you want full ARP processing (auto_scale, guess_markers, match_to_rig, bind_to_rig).

### Headless mode

```bat
run_vrm_to_fbx.bat --headless
```

Runs Blender in the background (no window). **ARP is skipped** in this mode. The pipeline still produces FBX output by using a **conversion-only** path: the imported VRM armature and mesh are exported as-is. Successfully converted files are moved to `vrm_done\`, not `vrm_failed\`. Use headless for batch runs where ARP is not required or when ARP is unavailable (e.g. version mismatch).

### ARP and Blender version mismatch

Auto-Rig Pro may report that it was "written for Blender 4.2" (or another version). If the addon’s required Blender version is **newer** than your installed Blender, the script detects this, logs a clear **WARNING**, and **skips ARP** for that run. It then uses the **fallback conversion-only export** so you still get an FBX (VRM rig + mesh as-is). No crash; output is still produced when possible.

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
2. For each file, Blender will:
   - Clean the scene (delete all objects, purge orphan data)
   - Import the VRM model and identify the main armature and mesh
   - Apply transforms
   - **Try Auto-Rig Pro** (in UI mode, when version-compatible): auto_scale, guess_markers, match_to_rig, bind_to_rig
   - If ARP fails at any step (context error, version mismatch, etc.), **fall back to conversion-only export**: export the VRM armature and mesh as-is to FBX
   - Export `.fbx` (with embedded textures), `.glb`, `.dae` and `.obj` (either from ARP or from the fallback)
3. Successfully processed `.vrm` files (ARP or fallback) are moved to `vrm_done\`.
4. Only files that fail **both** ARP and conversion-only export are moved to `vrm_failed\`.
5. A timestamped log file in the output directory shows per-file details and a summary: `total`, `arp_success`, `fallback_success`, `failed`.

### Output Structure

```
vrm_pipeline\
    bat_debug_log_20260215_153022.txt
    fbx_out\
        default-female.fbx
        default-female.glb
        default-female_dae\
            default-female.dae
            texture1.png
            texture2.png
        default-female_obj\
            default-female.obj
            default-female.mtl
            texture1.png
            texture2.png
        default-male.fbx
        default-male.glb
        default-male_dae\
            default-male.dae
            texture1.png
            texture2.png
        default-male_obj\
            default-male.obj
            default-male.mtl
            texture1.png
            texture2.png
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

**Symptom:** `Missing ARP operators`, `auto_scale failed`, or `context is incorrect` in the log.

**Behaviour:** The pipeline **automatically falls back** to conversion-only export (VRM armature + mesh as-is). If that succeeds, the file is still moved to `vrm_done\` and you get an FBX. Only if **both** ARP and fallback fail does the file go to `vrm_failed\`.

**Possible causes and fixes:**

- **ARP not installed:** Install and enable it via Blender preferences. Without ARP, fallback export still runs.
- **ARP "written for Blender 4.2" (or newer):** If ARP’s required Blender version is higher than your installed Blender, the script logs a WARNING and skips ARP; fallback export is used so FBX output is still produced.
- **ARP version/operator names:** Some ARP builds register operators under different names. Run `dump_ops.py` to see available `arp` operators.
- **Armature incompatible:** ARP works best with humanoid skeletons and standard bone names. Non-standard VRM rigs may fail; fallback export still produces an FBX.
- **Headless mode:** ARP is skipped when you pass `--headless`; fallback export runs instead.
- **Context error:** The script tries several selection/mode strategies for ARP. If all fail, fallback export is attempted automatically.

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
