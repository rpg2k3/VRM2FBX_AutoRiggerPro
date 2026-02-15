"""
vrm_to_fbx_batch.py
====================
Blender script that batch-converts .vrm files into Cascadeur-ready .fbx
files via Auto-Rig Pro.

Requires UI mode (no --background) because ARP operators depend on a
real VIEW_3D context that cannot be faked in headless mode.

Usage (called by run_vrm_to_fbx.bat):
    blender.exe --python vrm_to_fbx_batch.py -- INPUT_DIR OUTPUT_DIR [DONE_DIR] [FAILED_DIR]

All directories default to sibling folders next to this script:
    vrm_in, fbx_out, vrm_done, vrm_failed

Requirements:
    - Blender 4.1.1 (portable zip)
    - VRM Addon for Blender (installed & enabled)
    - Auto-Rig Pro Full (installed & enabled)
"""

import bpy
import sys
import os
import shutil
import traceback
import datetime
import time

# ---------------------------------------------------------------------------
# SCRIPT DIRECTORY (base for all default paths)
# ---------------------------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def timestamp():
    """Return ISO-style timestamp for logging."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, log_lines, level="INFO"):
    """Print and buffer a log line."""
    line = f"[{timestamp()}] [{level}] {msg}"
    print(line, flush=True)
    log_lines.append(line)


def ensure_dir(path):
    """Create directory if it does not exist."""
    os.makedirs(path, exist_ok=True)


def enable_addon_safe(addon_module, log_lines):
    """Enable a Blender addon, returning True on success."""
    try:
        bpy.ops.preferences.addon_enable(module=addon_module)
        log(f"Addon enabled: {addon_module}", log_lines)
        return True
    except Exception as exc:
        log(f"Failed to enable addon '{addon_module}': {exc}", log_lines, "ERROR")
        return False


def find_addon_module(keyword, log_lines):
    """
    Search installed addons for one whose module name contains the keyword.
    Returns the module name string or None.
    """
    import addon_utils
    for mod in addon_utils.modules():
        if keyword.lower() in mod.__name__.lower():
            log(f"Found addon module: {mod.__name__}", log_lines)
            return mod.__name__
    return None


# ---------------------------------------------------------------------------
# SCENE MANAGEMENT
# ---------------------------------------------------------------------------

def clean_scene(log_lines):
    """
    Remove all objects, collections, and orphan data from the current scene
    WITHOUT calling read_factory_settings().

    This avoids triggering ARP's load_pre handler which causes:
      - draw_handler_remove(...): nullptr handler given
      - AttributeError: Scene has no attribute arp_debug_mode
    """
    log("Cleaning scene (safe method, no factory reset)", log_lines)

    # Switch to OBJECT mode if we're in another mode
    if bpy.context.mode != 'OBJECT':
        try:
            bpy.ops.object.mode_set(mode='OBJECT')
        except Exception:
            pass

    # Deselect all, then select all and delete
    for obj in bpy.data.objects:
        obj.hide_set(False)
        obj.hide_select = False
        obj.select_set(True)
    try:
        bpy.ops.object.delete(use_global=True)
    except Exception:
        pass

    # Remove any remaining objects via data-level API
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)

    # Remove all non-master collections
    scene = bpy.context.scene
    for coll in list(scene.collection.children):
        scene.collection.children.unlink(coll)
    # Remove orphan collections from bpy.data
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)

    # Purge all orphan data blocks (meshes, armatures, materials, etc.)
    # Run multiple passes to catch nested dependencies
    for _ in range(3):
        bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)

    log("Scene cleaned", log_lines)


def ensure_addons(log_lines):
    """
    Make sure VRM and ARP addons are enabled. Returns (vrm_ok, arp_ok).
    """
    vrm_candidates = ["vrm", "io_scene_vrm"]
    arp_candidates = ["auto_rig_pro", "rig_tools", "auto_rig"]

    vrm_ok = False
    for candidate in vrm_candidates:
        found = find_addon_module(candidate, log_lines)
        if found:
            vrm_ok = enable_addon_safe(found, log_lines)
            if vrm_ok:
                break
    if not vrm_ok:
        for candidate in vrm_candidates:
            vrm_ok = enable_addon_safe(candidate, log_lines)
            if vrm_ok:
                break

    arp_ok = False
    for candidate in arp_candidates:
        found = find_addon_module(candidate, log_lines)
        if found:
            arp_ok = enable_addon_safe(found, log_lines)
            if arp_ok:
                break
    if not arp_ok:
        for candidate in arp_candidates:
            arp_ok = enable_addon_safe(candidate, log_lines)
            if arp_ok:
                break

    return vrm_ok, arp_ok


# ---------------------------------------------------------------------------
# IMPORT / DETECTION
# ---------------------------------------------------------------------------

def import_vrm(filepath, log_lines):
    """Import a .vrm file. Returns True on success."""
    log(f"Importing VRM: {filepath}", log_lines)

    if not hasattr(bpy.ops.import_scene, "vrm"):
        log("Operator bpy.ops.import_scene.vrm not found. Is VRM addon enabled?",
            log_lines, "ERROR")
        return False

    try:
        result = bpy.ops.import_scene.vrm(filepath=filepath)
        if result == {"FINISHED"}:
            log("VRM import succeeded", log_lines)
            return True
        else:
            log(f"VRM import returned: {result}", log_lines, "WARN")
            return True  # Some versions return CANCELLED but still import
    except Exception as exc:
        log(f"VRM import exception: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False


def find_main_armature(log_lines):
    """Find the ARMATURE object with the most bones (likely the VRM skeleton)."""
    best = None
    best_bones = -1
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            bone_count = len(obj.data.bones)
            log(f"  Armature found: '{obj.name}' ({bone_count} bones)", log_lines)
            if bone_count > best_bones:
                best = obj
                best_bones = bone_count
    if best:
        log(f"Main armature identified: '{best.name}' ({best_bones} bones)", log_lines)
    else:
        log("No armature found in scene", log_lines, "ERROR")
    return best


def find_main_mesh(log_lines):
    """Find the MESH object with the most vertices."""
    best = None
    best_verts = -1
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            vert_count = len(obj.data.vertices)
            log(f"  Mesh found: '{obj.name}' ({vert_count} verts)", log_lines)
            if vert_count > best_verts:
                best = obj
                best_verts = vert_count
    if best:
        log(f"Main mesh identified: '{best.name}' ({best_verts} verts)", log_lines)
    else:
        log("No mesh found in scene", log_lines, "ERROR")
    return best


def select_only(obj):
    """Deselect everything (data-level), then select and activate the given object."""
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def apply_transforms(obj, log_lines):
    """Apply location, rotation, and scale transforms to an object."""
    log(f"Applying transforms to '{obj.name}'", log_lines)
    select_only(obj)
    try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception as exc:
        log(f"transform_apply failed for '{obj.name}': {exc}", log_lines, "WARN")


def get_all_armatures():
    """Return a set of all current armature object names."""
    return {obj.name for obj in bpy.data.objects if obj.type == "ARMATURE"}


# ---------------------------------------------------------------------------
# AUTO-RIG PRO SEQUENCE
# ---------------------------------------------------------------------------

def run_arp_sequence(armature, mesh, log_lines):
    """
    Run the Auto-Rig Pro rigging sequence:
      1. auto_scale
      2. guess_markers
      3. match_to_rig
      4. bind_to_rig

    REQUIRES UI mode (bpy.app.background must be False).

    Returns (success: bool, arp_rig: Object or None)
    """
    # Runtime guard: ARP needs a real UI context
    if bpy.app.background:
        log("ERROR: Auto-Rig Pro operators require Blender UI mode.", log_lines, "ERROR")
        log("ARP cannot run with --background. Remove the --headless flag", log_lines, "ERROR")
        log("from run_vrm_to_fbx.bat (or don't pass --headless).", log_lines, "ERROR")
        return False, None

    # Validate ARP operators exist
    arp_ops = {
        "auto_scale": getattr(bpy.ops.arp, "auto_scale", None),
        "guess_markers": getattr(bpy.ops.arp, "guess_markers", None),
        "match_to_rig": getattr(bpy.ops.arp, "match_to_rig", None),
        "bind_to_rig": getattr(bpy.ops.arp, "bind_to_rig", None),
    }

    missing = [name for name, op in arp_ops.items() if op is None]
    if missing:
        log(f"Missing ARP operators: {missing}. Is Auto-Rig Pro enabled?",
            log_lines, "ERROR")
        return False, None

    # Helper: select armature and set mode
    def _setup(obj, mode='OBJECT', extra_selected=None):
        if bpy.context.mode != 'OBJECT':
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:
                pass
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj
        if extra_selected:
            for o in extra_selected:
                o.select_set(True)
        if mode != 'OBJECT' and obj.type == 'ARMATURE':
            try:
                bpy.ops.object.mode_set(mode=mode)
            except Exception:
                pass

    # Step 1: auto_scale
    log("ARP Step 1/4: auto_scale()", log_lines)
    try:
        _setup(armature)
        result = bpy.ops.arp.auto_scale()
        log(f"  auto_scale result: {result}", log_lines)
    except Exception as exc:
        log(f"  auto_scale failed: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False, None

    # Step 2: guess_markers
    log("ARP Step 2/4: guess_markers()", log_lines)
    try:
        _setup(armature)
        result = bpy.ops.arp.guess_markers()
        log(f"  guess_markers result: {result}", log_lines)
    except Exception as exc:
        log(f"  guess_markers failed: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False, None

    # Record armatures before match_to_rig so we can detect newly created ones
    armatures_before = get_all_armatures()

    # Step 3: match_to_rig
    log("ARP Step 3/4: match_to_rig()", log_lines)
    try:
        _setup(armature)
        result = bpy.ops.arp.match_to_rig()
        log(f"  match_to_rig result: {result}", log_lines)
    except Exception as exc:
        log(f"  match_to_rig failed: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False, None

    # Detect new ARP rig armature — prefer the one with the most bones
    armatures_after = get_all_armatures()
    new_armature_names = armatures_after - armatures_before
    arp_rig = None

    if new_armature_names:
        log(f"  New armature(s) created by match_to_rig: {sorted(new_armature_names)}",
            log_lines)
        best_rig = None
        best_bones = -1
        for name in new_armature_names:
            obj = bpy.data.objects.get(name)
            if obj and obj.type == 'ARMATURE':
                bone_count = len(obj.data.bones)
                log(f"    '{name}': {bone_count} bones", log_lines)
                if bone_count > best_bones:
                    best_rig = obj
                    best_bones = bone_count
        arp_rig = best_rig
        log(f"  Selected ARP rig: '{arp_rig.name}' ({best_bones} bones)", log_lines)
    else:
        log("  No new armature created by match_to_rig; using original", log_lines)
        arp_rig = armature

    # Step 4: bind_to_rig
    log("ARP Step 4/4: bind_to_rig()", log_lines)
    try:
        _setup(arp_rig, extra_selected=[mesh])
        result = bpy.ops.arp.bind_to_rig()
        log(f"  bind_to_rig result: {result}", log_lines)
    except Exception as exc:
        log(f"  bind_to_rig failed: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False, None

    return True, arp_rig


# ---------------------------------------------------------------------------
# FBX EXPORT
# ---------------------------------------------------------------------------

def export_fbx(output_path, arp_rig, mesh, log_lines):
    """
    Export the ARP rig and mesh as FBX for Cascadeur.
    Returns True on success.
    """
    log(f"Exporting FBX to: {output_path}", log_lines)

    # Select only the rig and mesh for export
    select_only(arp_rig)
    mesh.select_set(True)

    try:
        result = bpy.ops.export_scene.fbx(
            filepath=output_path,
            use_selection=True,
            object_types={"ARMATURE", "MESH"},
            add_leaf_bones=False,
            bake_anim=False,
            use_armature_deform_only=True,
            apply_unit_scale=True,
            path_mode="COPY",
            embed_textures=False,
            axis_forward="-Z",
            axis_up="Y",
        )
        if result == {"FINISHED"}:
            log("FBX export succeeded", log_lines)
            return True
        else:
            log(f"FBX export returned: {result}", log_lines, "WARN")
            return True
    except Exception as exc:
        log(f"FBX export exception: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False


# ---------------------------------------------------------------------------
# SINGLE-FILE PIPELINE
# ---------------------------------------------------------------------------

def process_single_vrm(vrm_path, output_dir, log_lines):
    """
    Full pipeline for a single .vrm file.
    Returns True on success, False on failure.
    """
    basename = os.path.splitext(os.path.basename(vrm_path))[0]
    fbx_path = os.path.join(output_dir, f"{basename}.fbx")
    start_time = time.time()

    log(f"{'='*60}", log_lines)
    log(f"Processing: {vrm_path}", log_lines)
    log(f"Output:     {fbx_path}", log_lines)
    log(f"{'='*60}", log_lines)

    # Step 1: Clean scene (safe method, no factory reset)
    clean_scene(log_lines)

    # Step 1b: Ensure addons are still enabled
    vrm_ok, arp_ok = ensure_addons(log_lines)
    if not vrm_ok:
        log("VRM addon could not be enabled. Skipping file.", log_lines, "ERROR")
        return False
    if not arp_ok:
        log("Auto-Rig Pro addon could not be enabled. Skipping file.", log_lines, "ERROR")
        return False

    # Step 2: Runtime guard — refuse to run ARP in background mode
    if bpy.app.background:
        log("ERROR: Running in --background mode. ARP requires UI mode.", log_lines, "ERROR")
        log("This file cannot be processed in headless mode.", log_lines, "ERROR")
        log("Re-run without --headless flag to enable ARP processing.", log_lines, "ERROR")
        return False

    # Step 3: Import VRM
    if not import_vrm(vrm_path, log_lines):
        return False

    # Step 4: Identify main objects
    armature = find_main_armature(log_lines)
    if not armature:
        return False

    mesh = find_main_mesh(log_lines)
    if not mesh:
        return False

    # Step 5: Apply transforms
    apply_transforms(armature, log_lines)
    apply_transforms(mesh, log_lines)

    # Step 6: Run ARP sequence (only in UI mode — guard is inside)
    success, arp_rig = run_arp_sequence(armature, mesh, log_lines)
    if not success:
        return False

    # Step 7: Export FBX
    if not export_fbx(fbx_path, arp_rig, mesh, log_lines):
        return False

    elapsed = time.time() - start_time
    log(f"Completed '{basename}' in {elapsed:.1f}s", log_lines)
    return True


# ---------------------------------------------------------------------------
# MAIN
# ---------------------------------------------------------------------------

def main():
    """
    Entry point. Parse CLI args (or use script-relative defaults), discover
    .vrm files, run pipeline.
    """
    # Parse arguments after '--'
    argv = sys.argv
    separator_idx = None
    for i, arg in enumerate(argv):
        if arg == "--":
            separator_idx = i
            break

    user_args = []
    if separator_idx is not None:
        user_args = argv[separator_idx + 1:]

    # Resolve directories from arguments or script-relative defaults
    if len(user_args) >= 1:
        input_dir = user_args[0]
    else:
        input_dir = os.path.join(SCRIPT_DIR, "vrm_in")
        print(f"No INPUT_DIR argument provided. Using default: {input_dir}")

    if len(user_args) >= 2:
        output_dir = user_args[1]
    else:
        output_dir = os.path.join(SCRIPT_DIR, "fbx_out")
        print(f"No OUTPUT_DIR argument provided. Using default: {output_dir}")

    if len(user_args) >= 3:
        done_dir = user_args[2]
    else:
        done_dir = os.path.join(SCRIPT_DIR, "vrm_done")
        print(f"No DONE_DIR argument provided. Using default: {done_dir}")

    if len(user_args) >= 4:
        failed_dir = user_args[3]
    else:
        failed_dir = os.path.join(SCRIPT_DIR, "vrm_failed")
        print(f"No FAILED_DIR argument provided. Using default: {failed_dir}")

    # Create all required directories (safe if they already exist)
    for dirpath in [input_dir, output_dir, done_dir, failed_dir]:
        ensure_dir(dirpath)
        print(f"Verified folder: {dirpath}")

    # Discover .vrm files
    vrm_files = sorted([
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if f.lower().endswith(".vrm") and os.path.isfile(os.path.join(input_dir, f))
    ])

    if not vrm_files:
        print(f"No .vrm files found in: {input_dir}")
        sys.exit(0)

    print(f"Found {len(vrm_files)} .vrm file(s) to process.")

    # Logging
    log_lines = []
    total_start = time.time()
    success_count = 0
    fail_count = 0

    log(f"Pipeline started", log_lines)
    log(f"Input directory:  {input_dir}", log_lines)
    log(f"Output directory: {output_dir}", log_lines)
    log(f"Done directory:   {done_dir}", log_lines)
    log(f"Failed directory: {failed_dir}", log_lines)
    log(f"Files to process: {len(vrm_files)}", log_lines)
    log(f"Blender version:  {bpy.app.version_string}", log_lines)
    log(f"Background mode:  {bpy.app.background}", log_lines)

    if bpy.app.background:
        log("WARNING: Running in background mode. ARP operators will fail.", log_lines, "WARN")
        log("All files will be moved to the failed folder.", log_lines, "WARN")
        log("Re-run without --headless to process files with ARP.", log_lines, "WARN")

    for idx, vrm_path in enumerate(vrm_files, 1):
        filename = os.path.basename(vrm_path)
        log(f"\n--- File {idx}/{len(vrm_files)}: {filename} ---", log_lines)

        try:
            success = process_single_vrm(vrm_path, output_dir, log_lines)
        except Exception as exc:
            log(f"Unhandled exception processing '{filename}': {exc}", log_lines, "ERROR")
            log(traceback.format_exc(), log_lines, "ERROR")
            success = False

        if success:
            success_count += 1
            dest = os.path.join(done_dir, filename)
            try:
                shutil.move(vrm_path, dest)
                log(f"Moved to done: {dest}", log_lines)
            except Exception as exc:
                log(f"Failed to move '{filename}' to done: {exc}", log_lines, "WARN")
        else:
            fail_count += 1
            dest = os.path.join(failed_dir, filename)
            try:
                shutil.move(vrm_path, dest)
                log(f"Moved to failed: {dest}", log_lines)
            except Exception as exc:
                log(f"Failed to move '{filename}' to failed: {exc}", log_lines, "WARN")

    total_elapsed = time.time() - total_start

    log(f"\n{'='*60}", log_lines)
    log(f"Pipeline complete", log_lines)
    log(f"  Total files:  {len(vrm_files)}", log_lines)
    log(f"  Succeeded:    {success_count}", log_lines)
    log(f"  Failed:       {fail_count}", log_lines)
    log(f"  Total time:   {total_elapsed:.1f}s", log_lines)
    log(f"{'='*60}", log_lines)

    # Write log file
    log_filename = datetime.datetime.now().strftime("vrm_pipeline_%Y%m%d_%H%M%S.log")
    log_path = os.path.join(output_dir, log_filename)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
        print(f"Log written to: {log_path}")
    except Exception as exc:
        print(f"Failed to write log file: {exc}")

    if fail_count > 0:
        sys.exit(2)


if __name__ == "__main__":
    main()
