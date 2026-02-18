"""
vrm_to_fbx_batch.py
====================
Blender script that batch-converts .vrm files into .fbx (with embedded
textures/skins), .glb, .dae and .obj files. Uses Auto-Rig Pro when
available and context allows; otherwise falls back to conversion-only
export (VRM armature + mesh as-is).

Usage (called by run_vrm_to_fbx.bat):
    blender.exe [--background] --python vrm_to_fbx_batch.py -- INPUT_DIR OUTPUT_DIR DONE_DIR FAILED_DIR [--headless]

With --headless (or --background), ARP is skipped; fallback export still runs.
All four formats (.fbx, .glb, .dae, .obj) are written to the output directory for each VRM file.
"""

import bpy
import sys
import os
import shutil
import traceback
import datetime
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


def timestamp():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(msg, log_lines, level="INFO"):
    line = f"[{timestamp()}] [{level}] {msg}"
    print(line, flush=True)
    log_lines.append(line)


def ensure_dir(path):
    """Create directory and any parents; no error if exists."""
    os.makedirs(path, exist_ok=True)


def safe_name(path_or_name):
    """Base filename without extension; spaces -> underscores; only [a-zA-Z0-9_-]."""
    base = os.path.splitext(os.path.basename(path_or_name or ""))[0]
    base = (base or "export").replace(" ", "_")
    return "".join(c for c in base if c.isalnum() or c in "_-") or "export"


def enable_addon_safe(addon_module, log_lines):
    try:
        bpy.ops.preferences.addon_enable(module=addon_module)
        log(f"Addon enabled: {addon_module}", log_lines)
        return True
    except Exception as exc:
        log(f"Failed to enable addon '{addon_module}': {exc}", log_lines, "ERROR")
        return False


def find_addon_module(keyword, log_lines):
    import addon_utils
    for mod in addon_utils.modules():
        if keyword.lower() in mod.__name__.lower():
            log(f"Found addon module: {mod.__name__}", log_lines)
            return mod.__name__
    return None


def get_arp_bl_info_min_blender(log_lines):
    """Return (major, minor, patch) minimum Blender from ARP bl_info, or None if unknown."""
    try:
        import addon_utils
        for mod in addon_utils.modules():
            if "arp" in mod.__name__.lower() or "auto_rig" in mod.__name__.lower() or "rig_tools" in mod.__name__.lower():
                if hasattr(mod, "bl_info"):
                    info = mod.bl_info
                    ver = info.get("blender") or info.get("version")
                    if isinstance(ver, (list, tuple)) and len(ver) >= 2:
                        return (int(ver[0]), int(ver[1]), int(ver[2]) if len(ver) > 2 else 0)
    except Exception as exc:
        log(f"Could not read ARP bl_info: {exc}", log_lines, "WARN")
    return None


def check_arp_version_compat(log_lines):
    """If ARP declares min Blender > current, return False (use fallback)."""
    current = bpy.app.version
    current_tuple = (current[0], current[1], current[2] if len(current) > 2 else 0)
    arp_min = get_arp_bl_info_min_blender(log_lines)
    if arp_min is None:
        return True
    if arp_min[0] > current_tuple[0] or (arp_min[0] == current_tuple[0] and arp_min[1] > current_tuple[1]):
        log(f"WARNING: Auto-Rig Pro reports minimum Blender {arp_min[0]}.{arp_min[1]}; current is {current_tuple[0]}.{current_tuple[1]}.", log_lines, "WARN")
        log("WARNING: Skipping ARP; using conversion-only export for this run.", log_lines, "WARN")
        return False
    return True


# ---------------------------------------------------------------------------
# VIEW_3D CONTEXT OVERRIDE
# ---------------------------------------------------------------------------

def get_view3d_override_full(log_lines):
    """
    Build a full context override dict for VIEW_3D including:
    window, screen, area, region, scene, view_layer, space_data, region_data.
    Returns (override_dict, ok_bool). Logs reason on failure.
    """
    for window in bpy.context.window_manager.windows:
        screen = window.screen
        for area in screen.areas:
            if area.type != "VIEW_3D":
                continue
            region = None
            for r in area.regions:
                if r.type == "WINDOW":
                    region = r
                    break
            if region is None:
                log("VIEW_3D area has no WINDOW region", log_lines, "ERROR")
                continue
            space_data = None
            for sp in area.spaces:
                if sp.type == "VIEW_3D":
                    space_data = sp
                    break
            if space_data is None and area.spaces.active:
                space_data = area.spaces.active
            region_data = getattr(space_data, "region_3d", None) if space_data else None
            override = {
                "window": window,
                "screen": screen,
                "area": area,
                "region": region,
                "scene": bpy.context.scene,
                "view_layer": bpy.context.view_layer,
            }
            if space_data is not None:
                override["space_data"] = space_data
            if region_data is not None:
                override["region_data"] = region_data
            log("Found VIEW_3D area for context override (full dict)", log_lines)
            return override, True
    log("No VIEW_3D area found for context override", log_lines, "ERROR")
    return None, False


# ---------------------------------------------------------------------------
# SCENE MANAGEMENT
# ---------------------------------------------------------------------------

def clean_scene(log_lines):
    """Remove all objects, deselect, OBJECT mode, purge orphans. No read_factory_settings."""
    log("Cleaning scene (safe method, no factory reset)", log_lines)
    if bpy.context.mode != "OBJECT":
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    for obj in bpy.data.objects:
        obj.hide_set(False)
        obj.hide_select = False
        obj.select_set(True)
    try:
        bpy.ops.object.delete(use_global=True)
    except Exception:
        pass
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    scene = bpy.context.scene
    for coll in list(scene.collection.children):
        scene.collection.children.unlink(coll)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for _ in range(3):
        try:
            bpy.ops.outliner.orphans_purge(do_local_ids=True, do_linked_ids=True, do_recursive=True)
        except Exception:
            pass
    for obj in bpy.context.view_layer.objects:
        obj.select_set(False)
    try:
        bpy.ops.object.mode_set(mode="OBJECT")
    except Exception:
        pass
    log("Scene cleaned", log_lines)


def ensure_addons(log_lines):
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
    if not hasattr(bpy.ops.import_scene, "vrm"):
        log("Operator bpy.ops.import_scene.vrm not found. Is VRM addon enabled?", log_lines, "ERROR")
        return False
    try:
        result = bpy.ops.import_scene.vrm(filepath=filepath)
        if result == {"FINISHED"}:
            log("VRM import succeeded", log_lines)
            return True
        log(f"VRM import returned: {result}", log_lines, "WARN")
        return True
    except Exception as exc:
        log(f"VRM import exception: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        return False


def find_main_armature(log_lines):
    best = None
    best_bones = -1
    for obj in bpy.data.objects:
        if obj.type == "ARMATURE":
            n = len(obj.data.bones)
            if n > best_bones:
                best = obj
                best_bones = n
    if best:
        log(f"Main armature: '{best.name}' ({best_bones} bones)", log_lines)
    else:
        log("No armature found in scene", log_lines, "ERROR")
    return best


def find_main_mesh(log_lines):
    best = None
    best_verts = -1
    for obj in bpy.data.objects:
        if obj.type == "MESH":
            n = len(obj.data.vertices)
            if n > best_verts:
                best = obj
                best_verts = n
    if best:
        log(f"Main mesh: '{best.name}' ({best_verts} verts)", log_lines)
    else:
        log("No mesh found in scene", log_lines, "ERROR")
    return best


def find_all_meshes(log_lines):
    """Return list of all MESH objects in the scene (for rigged multi-export)."""
    meshes = [obj for obj in bpy.data.objects if obj.type == "MESH"]
    log(f"Found {len(meshes)} mesh(es): {[m.name for m in meshes]}", log_lines)
    return meshes


def select_only(obj):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def set_selection(active_obj, selected_objs, mode="OBJECT", log_lines=None):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for o in selected_objs:
        if o is not None:
            o.select_set(True)
    if active_obj is not None:
        bpy.context.view_layer.objects.active = active_obj
    if bpy.context.mode != mode:
        try:
            bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass


def apply_transforms(obj, log_lines):
    log(f"Applying transforms to '{obj.name}'", log_lines)
    select_only(obj)
    try:
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    except Exception as exc:
        log(f"transform_apply failed for '{obj.name}': {exc}", log_lines, "WARN")


def get_all_armatures():
    return {obj.name for obj in bpy.data.objects if obj.type == "ARMATURE"}


# ---------------------------------------------------------------------------
# ARP OPERATOR CALL WITH MULTIPLE STRATEGIES
# ---------------------------------------------------------------------------

def call_arp_op(op_name, op_func, override, armature, mesh, log_lines):
    """
    Try multiple strategies for an ARP operator (e.g. auto_scale):
    1) active=armature, selected=[armature]
    2) active=armature, selected=[armature, mesh]
    3) active=mesh, selected=[mesh, armature]
    4) OBJECT mode then POSE mode retry for armature
    Returns True if the operator succeeded.
    """
    strategies = [
        ("armature active, [armature]", [armature], armature, "OBJECT"),
        ("armature active, [armature, mesh]", [armature, mesh], armature, "OBJECT"),
        ("mesh active, [mesh, armature]", [mesh, armature], mesh, "OBJECT"),
        ("armature active, [armature], POSE", [armature], armature, "POSE"),
    ]
    for desc, selected, active, mode in strategies:
        try:
            with bpy.context.temp_override(**override):
                set_selection(active, selected, mode=mode, log_lines=log_lines)
                active_name = active.name if active else ""
                active_type = active.type if active else ""
                sel_names = [o.name for o in selected if o]
                log(f"  Attempt: {desc} | active={active_name} ({active_type}) selected={sel_names} mode={mode}", log_lines)
                result = op_func()
                log(f"  {op_name} result: {result}", log_lines)
                if result == {"FINISHED"}:
                    return True
        except Exception as exc:
            log(f"  {op_name} failed: {exc}", log_lines, "ERROR")
            log(traceback.format_exc(), log_lines, "ERROR")
    return False


# ---------------------------------------------------------------------------
# AUTO-RIG PRO SEQUENCE
# ---------------------------------------------------------------------------

def run_arp_sequence(armature, mesh, override, log_lines):
    """
    Run ARP: auto_scale -> guess_markers -> match_to_rig -> bind_to_rig.
    Returns (success: bool, arp_rig: Object or None).
    """
    arp_ops = {
        "auto_scale": getattr(bpy.ops.arp, "auto_scale", None),
        "guess_markers": getattr(bpy.ops.arp, "guess_markers", None),
        "match_to_rig": getattr(bpy.ops.arp, "match_to_rig", None),
        "bind_to_rig": getattr(bpy.ops.arp, "bind_to_rig", None),
    }
    missing = [n for n, op in arp_ops.items() if op is None]
    if missing:
        log(f"Missing ARP operators: {missing}", log_lines, "ERROR")
        return False, None

    log("ARP Step 1/4: auto_scale()", log_lines)
    if not call_arp_op("auto_scale", arp_ops["auto_scale"], override, armature, mesh, log_lines):
        return False, None

    log("ARP Step 2/4: guess_markers()", log_lines)
    try:
        with bpy.context.temp_override(**override):
            set_selection(armature, [armature], "OBJECT", log_lines)
            result = bpy.ops.arp.guess_markers()
            log(f"  guess_markers result: {result}", log_lines)
            if result != {"FINISHED"}:
                return False, None
    except Exception as exc:
        log(f"  guess_markers failed: {exc}", log_lines, "ERROR")
        return False, None

    armatures_before = get_all_armatures()
    log("ARP Step 3/4: match_to_rig()", log_lines)
    try:
        with bpy.context.temp_override(**override):
            set_selection(armature, [armature], "OBJECT", log_lines)
            result = bpy.ops.arp.match_to_rig()
            log(f"  match_to_rig result: {result}", log_lines)
            if result != {"FINISHED"}:
                return False, None
    except Exception as exc:
        log(f"  match_to_rig failed: {exc}", log_lines, "ERROR")
        return False, None

    armatures_after = get_all_armatures()
    new_names = armatures_after - armatures_before
    arp_rig = None
    if new_names:
        best_rig = None
        best_bones = -1
        for name in new_names:
            obj = bpy.data.objects.get(name)
            if obj and obj.type == "ARMATURE":
                n = len(obj.data.bones)
                if n > best_bones:
                    best_rig = obj
                    best_bones = n
        arp_rig = best_rig
        if arp_rig:
            log(f"  ARP rig: '{arp_rig.name}' ({best_bones} bones)", log_lines)
    if arp_rig is None:
        arp_rig = armature
        log("  Using original armature as rig", log_lines)

    log("ARP Step 4/4: bind_to_rig()", log_lines)
    try:
        with bpy.context.temp_override(**override):
            set_selection(arp_rig, [arp_rig, mesh], "OBJECT", log_lines)
            result = bpy.ops.arp.bind_to_rig()
            log(f"  bind_to_rig result: {result}", log_lines)
            if result != {"FINISHED"}:
                return False, None
    except Exception as exc:
        log(f"  bind_to_rig failed: {exc}", log_lines, "ERROR")
        return False, None

    return True, arp_rig


# ---------------------------------------------------------------------------
# EXPORT HELPERS: SELECTION, NORMALS, MATERIALS
# ---------------------------------------------------------------------------

def prepare_selection_for_export(armature_obj, mesh_objs, log_lines):
    """
    Deselect all, select armature + all meshes, set active=armature.
    Uses only direct API (no bpy.ops) so it works in timer/deferred context.
    Caller should run bpy.ops.object.mode_set(mode='OBJECT') inside a context override if needed.
    """
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    for obj in [armature_obj] + list(mesh_objs):
        if obj is not None and obj.name in bpy.data.objects:
            bpy.data.objects[obj.name].select_set(True)
    bpy.context.view_layer.objects.active = armature_obj
    sel_names = [armature_obj.name] + [m.name for m in mesh_objs]
    log(f"Selection set: active={armature_obj.name}, selected={sel_names}", log_lines)


def recalc_normals_outside(mesh_objs, log_lines, override=None):
    """
    For each mesh: EDIT mode, select all, recalc normals outside, OBJECT mode.
    If override is provided, run bpy.ops inside temp_override so it works in timer context.
    """
    def _run():
        for obj in mesh_objs:
            if not obj or obj.type != "MESH":
                continue
            try:
                for o in bpy.context.view_layer.objects:
                    o.select_set(False)
                obj.select_set(True)
                bpy.context.view_layer.objects.active = obj
                bpy.ops.object.mode_set(mode="EDIT")
                bpy.ops.mesh.select_all(action="SELECT")
                bpy.ops.mesh.normals_make_consistent(inside=False)
                bpy.ops.object.mode_set(mode="OBJECT")
                log(f"  Recalculated normals (outside) for: {obj.name}", log_lines)
            except Exception as exc:
                log(f"  normals_make_consistent failed for '{obj.name}': {exc}", log_lines, "WARN")
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    if override:
        with bpy.context.temp_override(**override):
            _run()
    else:
        _run()


def prepare_materials_for_export(mesh_objects, mode, log_lines, override=None):
    """
    Export prep used ONLY for GLB/OBJ/DAE (not FBX).
    mode: "GLB" | "OBJ" | "DAE"
    Ensures Principled BSDF, color space, transparency defaults (GLB), normals.
    """
    if not mesh_objects:
        return
    log(f"prepare_materials_for_export: mode={mode}", log_lines)

    # 1) Try VRM addon conversion operator if available
    if hasattr(bpy.ops.vrm, "convert_mtoon1_to_bsdf_principled"):
        try:
            if override:
                with bpy.context.temp_override(**override):
                    bpy.ops.vrm.convert_mtoon1_to_bsdf_principled()
            else:
                bpy.ops.vrm.convert_mtoon1_to_bsdf_principled()
            log("  VRM convert_mtoon1_to_bsdf_principled() called", log_lines)
        except Exception as exc:
            log(f"  VRM convert operator (non-fatal): {exc}", log_lines, "WARN")

    materials_done = set()
    for obj in mesh_objects:
        if not obj or obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat or id(mat) in materials_done:
                if mat:
                    mat.use_backface_culling = False
                continue
            materials_done.add(id(mat))
            mat.use_backface_culling = False

            if not mat.use_nodes or not getattr(mat, "node_tree", None):
                continue

            # If still MToon/VRM, rebuild to Principled programmatically
            if _is_vrm_mtoon_material(mat):
                try:
                    new_mat = _material_to_principled_for_glb(mat, log_lines)
                    if new_mat:
                        new_mat.use_backface_culling = False
                        slot.material = new_mat
                        mat = new_mat
                except Exception as exc:
                    log(f"  Skip Principled conversion for '{mat.name}': {exc}", log_lines, "WARN")
                    continue

            # 2) Fix color space in current material
            ntree = mat.node_tree
            if ntree:
                for node in ntree.nodes:
                    if node.type != "TEX_IMAGE" or not node.image:
                        continue
                    img = node.image
                    try:
                        cs = getattr(img, "colorspace_settings", None)
                        if cs is not None:
                            if hasattr(cs, "name"):
                                # Check if this texture is connected to Normal/Metallic/Roughness
                                is_noncolor = False
                                for link in ntree.links:
                                    if link.from_node == node:
                                        to_sock = link.to_socket
                                        if to_sock and (to_sock.name in ("Normal", "Metallic", "Roughness", "Alpha") or "normal" in (to_sock.name or "").lower() or "bump" in (to_sock.name or "").lower()):
                                            is_noncolor = True
                                            break
                                if is_noncolor or "normal" in (img.name or "").lower() or "nrm" in (img.name or "").lower():
                                    cs.name = "Non-Color"
                                else:
                                    cs.name = "sRGB"
                    except Exception as exc:
                        log(f"  colorspace for '{img.name}' (non-fatal): {exc}", log_lines, "WARN")

            # 3) Transparency defaults for GLB
            if mode == "GLB":
                name_low = (mat.name or "").lower()
                if any(x in name_low for x in ("face", "eyelash", "eye", "hair")):
                    mat.blend_method = "CLIP"
                    mat.alpha_threshold = 0.5
                else:
                    mat.blend_method = "OPAQUE"

    # 4) Normals fix
    recalc_normals_outside(mesh_objects, log_lines, override=override)
    log("prepare_materials_for_export: done", log_lines)


def _is_vrm_mtoon_material(mat):
    """Return True if material looks like VRM/MToon (node group or name)."""
    if not mat or not mat.use_nodes:
        return False
    for node in mat.node_tree.nodes:
        if node.type == "GROUP":
            if node.node_tree and ("mtoon" in node.node_tree.name.lower() or "vrm" in node.node_tree.name.lower()):
                return True
        if "mtoon" in (node.name or "").lower() or "vrm" in (node.name or "").lower():
            return True
    return "mtoon" in (mat.name or "").lower() or "vrm" in (mat.name or "").lower()


def _collect_images_from_tree(ntree, visited=None):
    """Recursively collect (main_images list, normal_images list) from ntree and any group nodes."""
    if visited is None:
        visited = set()
    if ntree is None or id(ntree) in visited:
        return [], []
    visited.add(id(ntree))
    main_list = []
    normal_list = []
    for node in ntree.nodes:
        if node.type == "TEX_IMAGE" and node.image:
            name_low = (node.image.name or "").lower()
            if "normal" in name_low or "nrm" in name_low:
                normal_list.append(node.image)
            else:
                main_list.append((node.image, bool(node.outputs.get("Alpha"))))
        if node.type == "GROUP" and node.node_tree:
            m, n = _collect_images_from_tree(node.node_tree, visited)
            main_list.extend(m)
            normal_list.extend(n)
    return main_list, normal_list


def _find_lit_or_base_color_image(ntree, visited=None):
    """
    Follow links from shader output to find TEX_IMAGE connected to Lit/Base Color.
    Returns (image, has_alpha) or (None, False). Prefers MToon "Lit" or "Base Color" input.
    """
    if visited is None:
        visited = set()
    if ntree is None or id(ntree) in visited:
        return None, False
    visited.add(id(ntree))
    out_node = None
    for n in ntree.nodes:
        if n.type == "OUTPUT_MATERIAL":
            out_node = n
            break
    surf = out_node.inputs.get("Surface") if out_node else None
    if not surf or not surf.links:
        return None, False
    shader_node = surf.links[0].from_node
    if shader_node.type == "TEX_IMAGE" and shader_node.image:
        return shader_node.image, bool(shader_node.outputs.get("Alpha"))
    if shader_node.type == "BSDF_PRINCIPLED":
        base_in = shader_node.inputs.get("Base Color")
        if base_in and base_in.links:
            n = base_in.links[0].from_node
            if n.type == "TEX_IMAGE" and n.image:
                return n.image, bool(n.outputs.get("Alpha"))
    if shader_node.type == "GROUP" and shader_node.node_tree:
        grp = shader_node.node_tree
        for gout in grp.nodes:
            if gout.type != "GROUP_OUTPUT":
                continue
            for inp in gout.inputs:
                name_low = (inp.name or "").lower()
                if "lit" in name_low or ("base" in name_low and "color" in name_low) or name_low == "color":
                    for link in grp.links:
                        if link.to_socket != inp:
                            continue
                        n = link.from_node
                        if n.type == "TEX_IMAGE" and n.image:
                            return n.image, bool(n.outputs.get("Alpha"))
                        if n.type == "GROUP" and n.node_tree:
                            img, alpha = _find_lit_or_base_color_image(n.node_tree, visited)
                            if img:
                                return img, alpha
            for inp in gout.inputs:
                for link in grp.links:
                    if link.to_socket != inp:
                        continue
                    n = link.from_node
                    if n.type == "TEX_IMAGE" and n.image:
                        return n.image, bool(n.outputs.get("Alpha"))
            break
    return None, False


def _find_base_color_and_normal_images(orig_mat):
    """
    Find (base_color_image, has_alpha, normal_image). Prefers image linked to Lit/Base Color.
    Falls back to first non-normal TEX_IMAGE in tree (including inside groups).
    """
    if not orig_mat or not orig_mat.use_nodes or not getattr(orig_mat, "node_tree", None):
        return None, False, None
    ntree = orig_mat.node_tree
    main_image, has_alpha = _find_lit_or_base_color_image(ntree)
    normal_image = None
    main_list, normal_list = _collect_images_from_tree(ntree)
    if not main_image and main_list:
        main_image, has_alpha = main_list[0]
    if normal_list:
        normal_image = normal_list[0]
    return main_image, has_alpha, normal_image


def _material_to_principled_for_glb(orig_mat, log_lines):
    """
    Create a duplicate material with Principled BSDF from VRM/MToon.
    Uses link-following to find the correct base color (and normal) per material.
    """
    if not orig_mat or not orig_mat.use_nodes:
        return None
    name = f"{orig_mat.name}_glb_principled"
    if name in bpy.data.materials:
        return bpy.data.materials[name]
    main_image, has_alpha, normal_image = _find_base_color_and_normal_images(orig_mat)
    if not main_image:
        for node in orig_mat.node_tree.nodes:
            if node.type == "TEX_IMAGE" and node.image:
                name_low = (node.image.name or "").lower()
                if "normal" not in name_low and "nrm" not in name_low:
                    main_image = node.image
                    has_alpha = bool(node.outputs.get("Alpha"))
                    break
    new_mat = bpy.data.materials.new(name=name)
    new_mat.use_nodes = True
    nodes = new_mat.node_tree.nodes
    links = new_mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    principled = nodes.new("ShaderNodeBsdfPrincipled")
    principled.location = (0, 0)
    links.new(principled.outputs["BSDF"], out.inputs["Surface"])

    if main_image:
        img_node = nodes.new("ShaderNodeTexImage")
        img_node.image = main_image
        links.new(img_node.outputs["Color"], principled.inputs["Base Color"])
        if has_alpha:
            links.new(img_node.outputs["Alpha"], principled.inputs["Alpha"])
            new_mat.blend_method = "HASHED"
            new_mat.shadow_method = "HASHED"
    if normal_image:
        norm_node = nodes.new("ShaderNodeNormalMap")
        img_norm = nodes.new("ShaderNodeTexImage")
        img_norm.image = normal_image
        links.new(img_norm.outputs["Color"], norm_node.inputs["Color"])
        links.new(norm_node.outputs["Normal"], principled.inputs["Normal"])

    log(f"  Created Principled material for GLB: {new_mat.name} (from {orig_mat.name}, tex={getattr(main_image, 'name', None)})", log_lines)
    return new_mat


def ensure_principled_and_double_sided_for_glb(mesh_objs, log_lines):
    """
    For GLB: ensure each mesh has Principled-based materials and double-sided.
    Converts VRM/MToon materials to Principled (duplicate). Sets use_backface_culling=False.
    """
    materials_processed = set()
    for obj in mesh_objs:
        if not obj or obj.type != "MESH":
            continue
        for slot in obj.material_slots:
            mat = slot.material
            if not mat or id(mat) in materials_processed:
                if mat:
                    mat.use_backface_culling = False
                continue
            materials_processed.add(id(mat))
            mat.use_backface_culling = False
            if _is_vrm_mtoon_material(mat):
                try:
                    new_mat = _material_to_principled_for_glb(mat, log_lines)
                    if new_mat:
                        new_mat.use_backface_culling = False
                        slot.material = new_mat
                except Exception as exc:
                    log(f"  Skip Principled conversion for '{mat.name}': {exc}", log_lines, "WARN")
    log("Materials prepared for GLB (double-sided, Principled where needed)", log_lines)


def _verify_export(path, log_lines, format_name):
    """Return True if path exists and size > 0. Log success or failure."""
    if not path:
        log(f"{format_name}: no path given", log_lines, "ERROR")
        return False
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            log(f"{format_name}: SUCCESS -> {path} ({os.path.getsize(path)} bytes)", log_lines)
            return True
        log(f"{format_name}: FAILED (file missing or empty) -> {path}", log_lines, "ERROR")
        return False
    except Exception as exc:
        log(f"{format_name}: FAILED -> {path} | {exc}", log_lines, "ERROR")
        return False


# ---------------------------------------------------------------------------
# MULTI-FORMAT EXPORT: export_all_formats
# ---------------------------------------------------------------------------

def _run_with_override(override, func, *args, **kwargs):
    """Run func() inside temp_override if override is not None."""
    if override:
        with bpy.context.temp_override(**override):
            return func(*args, **kwargs)
    return func(*args, **kwargs)


def export_all_formats(armature_obj, mesh_objs, model_name, out_dir, log_lines):
    """
    Export rigged model (armature + all meshes) to FBX, GLB, DAE, OBJ.
    Uses per-model subfolders: out_dir/fbx/<model_name>, glb/<model_name>, dae/<model_name>, obj/<model_name>.
    Returns dict format -> (success: bool, path_or_error: str).
    Writes <model_name>_export_report.txt into out_dir.
    """
    model = model_name or safe_name("export")
    fbx_dir = os.path.join(out_dir, "fbx", model)
    glb_dir = os.path.join(out_dir, "glb", model)
    dae_dir = os.path.join(out_dir, "dae", model)
    obj_dir = os.path.join(out_dir, "obj", model)
    ensure_dir(fbx_dir)
    ensure_dir(glb_dir)
    ensure_dir(dae_dir)
    ensure_dir(obj_dir)

    report = {}
    mesh_list = list(mesh_objs) if mesh_objs else []
    override, have_override = get_view3d_override_full(log_lines) if not bpy.app.background else (None, False)
    if not have_override:
        log("No VIEW_3D override (background?); export ops may still run with current context", log_lines, "WARN")

    def _selection_and_mode():
        prepare_selection_for_export(armature_obj, mesh_list, log_lines)
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception as exc:
            log(f"mode_set OBJECT (non-fatal): {exc}", log_lines, "WARN")

    # ----- FBX -----
    prepare_selection_for_export(armature_obj, mesh_list, log_lines)
    if have_override:
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
    else:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    fbx_path = os.path.join(fbx_dir, f"{model}.fbx")
    log(f"Exporting FBX to: {fbx_path}", log_lines)
    try:
        if have_override:
            with bpy.context.temp_override(**override):
                result = bpy.ops.export_scene.fbx(
                    filepath=fbx_path,
                    use_selection=True,
                    object_types={"ARMATURE", "MESH"},
                    add_leaf_bones=False,
                    bake_anim=False,
                    use_armature_deform_only=True,
                    apply_unit_scale=True,
                    path_mode="COPY",
                    embed_textures=True,
                    axis_forward="-Z",
                    axis_up="Y",
                )
        else:
            result = bpy.ops.export_scene.fbx(
                filepath=fbx_path,
                use_selection=True,
                object_types={"ARMATURE", "MESH"},
                add_leaf_bones=False,
                bake_anim=False,
                use_armature_deform_only=True,
                apply_unit_scale=True,
                path_mode="COPY",
                embed_textures=True,
                axis_forward="-Z",
                axis_up="Y",
            )
        if result == {"FINISHED"}:
            report["FBX"] = (_verify_export(fbx_path, log_lines, "FBX"), fbx_path)
        else:
            log(f"FBX export returned: {result}", log_lines, "ERROR")
            report["FBX"] = (False, f"operator returned {result}")
    except Exception as exc:
        log(f"FBX export exception: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        report["FBX"] = (False, str(exc))

    # ----- GLB: prep (Principled, colorspace, alpha) + pack + export -----
    prepare_materials_for_export(mesh_list, "GLB", log_lines, override=override if have_override else None)
    prepare_selection_for_export(armature_obj, mesh_list, log_lines)
    if have_override:
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
    else:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    try:
        bpy.ops.file.pack_all()
        log("  Packed all images for GLB embed", log_lines)
    except Exception as exc:
        log(f"  pack_all (non-fatal): {exc}", log_lines, "WARN")
    glb_path = os.path.join(glb_dir, f"{model}.glb")
    log(f"Exporting GLB to: {glb_path}", log_lines)
    try:
        kwargs = dict(
            filepath=glb_path,
            use_selection=True,
            export_format="GLB",
            export_apply=True,
            export_texcoords=True,
            export_normals=True,
            export_tangents=True,
            export_materials="EXPORT",
            export_colors=True,
            export_yup=True,
            export_animations=False,
            export_skins=True,
            export_morph=True,
            export_image_format="AUTO",
        )
        try:
            if "export_keep_originals" in (getattr(bpy.ops.export_scene.gltf, "keywords", None) or []):
                kwargs["export_keep_originals"] = False
        except Exception:
            pass
        export_gltf = lambda: bpy.ops.export_scene.gltf(**kwargs)
        result = _run_with_override(override if have_override else None, export_gltf)
        if result == {"FINISHED"}:
            ok = os.path.isfile(glb_path) and os.path.getsize(glb_path) > 0
            report["GLB"] = (ok, glb_path)
            if ok:
                log(f"GLB export: OK {glb_path}", log_lines)
            else:
                log(f"GLB export: FAIL (file missing or empty) {glb_path}", log_lines, "ERROR")
        else:
            log(f"GLB export: FAIL operator returned {result}", log_lines, "ERROR")
            report["GLB"] = (False, f"operator returned {result}")
    except Exception as exc:
        log(f"GLB export: FAIL {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        report["GLB"] = (False, str(exc))

    # ----- DAE -----
    prepare_materials_for_export(mesh_list, "DAE", log_lines, override=override if have_override else None)
    prepare_selection_for_export(armature_obj, mesh_list, log_lines)
    if have_override:
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
    else:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    dae_path = os.path.join(dae_dir, f"{model}.dae")
    log(f"Exporting DAE to: {dae_path}", log_lines)
    dae_warnings = []
    try:
        if not hasattr(bpy.ops.wm, "collada_export"):
            log("DAE: bpy.ops.wm.collada_export not available", log_lines, "ERROR")
            report["DAE"] = (False, "Collada exporter not available")
        else:
            prev_cwd = os.getcwd()
            try:
                os.chdir(dae_dir)
                def _dae_export():
                    return bpy.ops.wm.collada_export(
                        filepath=dae_path,
                        selected=True,
                        apply_modifiers=True,
                        include_armatures=True,
                        include_children=True,
                        deform_bones_only=True,
                    )
                result = _run_with_override(override if have_override else None, _dae_export)
                if result == {"FINISHED"}:
                    report["DAE"] = (_verify_export(dae_path, log_lines, "DAE"), dae_path)
                else:
                    log(f"DAE export returned: {result}", log_lines, "ERROR")
                    report["DAE"] = (False, f"operator returned {result}")
            finally:
                try:
                    os.chdir(prev_cwd)
                except Exception as e:
                    dae_warnings.append(f"Could not restore cwd: {e}")
    except Exception as exc:
        log(f"DAE export exception: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
        report["DAE"] = (False, str(exc))
        dae_warnings.append(str(exc))

    # ----- OBJ -----
    prepare_materials_for_export(mesh_list, "OBJ", log_lines, override=override if have_override else None)
    prepare_selection_for_export(armature_obj, mesh_list, log_lines)
    if have_override:
        with bpy.context.temp_override(**override):
            bpy.ops.object.mode_set(mode="OBJECT")
    else:
        try:
            bpy.ops.object.mode_set(mode="OBJECT")
        except Exception:
            pass
    obj_path = os.path.join(obj_dir, f"{model}.obj")
    mtl_path = os.path.join(obj_dir, f"{model}.mtl")
    log(f"Exporting OBJ to: {obj_path}", log_lines)
    obj_ok = False
    obj_error = ""
    obj_textures_copied = 0
    obj_missing_textures = []
    try:
        if hasattr(bpy.ops.wm, "obj_export"):
            def _obj_export():
                return bpy.ops.wm.obj_export(
                    filepath=obj_path,
                    export_selected_objects=True,
                    apply_modifiers=True,
                    export_materials=True,
                    export_uv=True,
                    export_normals=True,
                    path_mode="COPY",
                    forward_axis="NEGATIVE_Z",
                    up_axis="Y",
                )
            result = _run_with_override(override if have_override else None, _obj_export)
            if result == {"FINISHED"}:
                obj_ok = _verify_export(obj_path, log_lines, "OBJ")
                obj_textures_copied, obj_missing_textures = _parse_mtl_copy_textures_and_rewrite(obj_dir, mtl_path, log_lines)
                report["OBJ"] = (obj_ok, obj_path)
            else:
                obj_error = f"operator returned {result}"
        else:
            def _obj_export_legacy():
                return bpy.ops.export_scene.obj(
                    filepath=obj_path,
                    use_selection=True,
                    use_materials=True,
                    path_mode="COPY",
                    axis_forward="-Z",
                    axis_up="Y",
                )
            result = _run_with_override(override if have_override else None, _obj_export_legacy)
            if result == {"FINISHED"}:
                obj_ok = _verify_export(obj_path, log_lines, "OBJ")
                obj_textures_copied, obj_missing_textures = _parse_mtl_copy_textures_and_rewrite(obj_dir, mtl_path, log_lines)
                report["OBJ"] = (obj_ok, obj_path)
            else:
                obj_error = f"operator returned {result}"
    except Exception as exc:
        obj_error = str(exc)
        log(f"OBJ export exception: {exc}", log_lines, "ERROR")
        log(traceback.format_exc(), log_lines, "ERROR")
    if "OBJ" not in report:
        report["OBJ"] = (obj_ok, obj_path if obj_ok else (obj_error or "export failed"))
    if obj_ok:
        log(f"OBJ export: OK {obj_path}, textures copied: {obj_textures_copied}", log_lines)
    else:
        log(f"OBJ export: FAIL {obj_error or obj_path}", log_lines, "ERROR")
    if obj_missing_textures:
        log(f"OBJ missing textures: {obj_missing_textures}", log_lines, "WARN")

    # ----- Export report file -----
    def _texture_extensions():
        return (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff", ".exr")
    def _list_texture_files_in_dir(d, recursive=False):
        if not os.path.isdir(d):
            return []
        exts = _texture_extensions()
        out = []
        for name in os.listdir(d):
            path = os.path.join(d, name)
            if os.path.isfile(path) and name.lower().endswith(exts):
                out.append(name)
            elif recursive and os.path.isdir(path):
                for sub in _list_texture_files_in_dir(path, True):
                    out.append(os.path.join(name, sub))
        return sorted(out)
    obj_texture_files = _list_texture_files_in_dir(obj_dir)
    dae_texture_files = _list_texture_files_in_dir(dae_dir, recursive=True)
    report_path = os.path.join(out_dir, f"{model}_export_report.txt")
    lines = [
        f"Export report: {model}",
        f"Generated: {timestamp()}",
        "",
        "Directories used:",
        f"  FBX: {fbx_dir}",
        f"  GLB: {glb_dir}",
        f"  DAE: {dae_dir}",
        f"  OBJ: {obj_dir}",
        "",
    ]
    for fmt, (ok, path_or_err) in report.items():
        status = "SUCCESS" if ok else "FAILED"
        lines.append(f"  {fmt}: {status} -> {path_or_err}")
    lines.append("")
    lines.append("OBJ texture files:")
    for f in obj_texture_files:
        lines.append(f"  {f}")
    if not obj_texture_files:
        lines.append("  (none)")
    lines.append("")
    lines.append("DAE texture files:")
    for f in dae_texture_files:
        lines.append(f"  {f}")
    if not dae_texture_files:
        lines.append("  (none)")
    if dae_warnings:
        lines.append("")
        lines.append("Warnings:")
        for w in dae_warnings:
            lines.append(f"  {w}")
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        log(f"Export report written: {report_path}", log_lines)
    except Exception as exc:
        log(f"Could not write export report: {exc}", log_lines, "WARN")

    return report


def _unpack_images_to_folder(dest_folder, log_lines):
    """
    Unpack all packed images to dest_folder so they exist as files (for OBJ .mtl).
    Temporarily sets bpy.data.filepath so unpack writes into dest_folder.
    """
    try:
        original_filepath = bpy.data.filepath
        bpy.data.filepath = os.path.join(dest_folder, "_temp_unpack.blend")
        bpy.ops.file.unpack_all(method="WRITE_LOCAL")
        log(f"  Unpacked images to {dest_folder}", log_lines)
    except Exception as exc:
        log(f"  unpack_all (non-fatal): {exc}", log_lines, "WARN")
    finally:
        try:
            bpy.data.filepath = original_filepath
        except NameError:
            pass


def _save_packed_images_to_folder(dest_folder, log_lines):
    """Save packed (in-memory) images to dest_folder so OBJ .mtl can reference them."""
    for img in bpy.data.images:
        if img.type != "IMAGE" or not img.has_data:
            continue
        name = (img.name or "image").replace(" ", "_")
        if not name:
            continue
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
            name = name + ".png"
        path = os.path.join(dest_folder, os.path.basename(name))
        try:
            img.save_render(path)
            log(f"  Saved texture: {path}", log_lines)
        except Exception as exc:
            log(f"  save_render '{name}' (non-fatal): {exc}", log_lines, "WARN")


def _resolve_blender_image_for_mtl(mtl_path_value, obj_folder=None):
    """
    Resolve MTL map path to a source file path.
    mtl_path_value: path as written in .mtl. obj_folder: folder containing .mtl (for relative resolve).
    Returns (absolute_path, None) if found, ("PACKED", img) if packed, (None, display_name) if missing.
    """
    raw = (mtl_path_value or "").strip().replace("\\", "/")
    if not raw:
        return None, mtl_path_value
    base = os.path.basename(raw)
    # 1) If absolute and exists, use it
    if os.path.isabs(raw):
        if os.path.isfile(raw):
            return os.path.normpath(raw), None
        return None, raw
    # 2) Relative path: try relative to obj_folder (MTL dir)
    if obj_folder:
        rel_path = os.path.normpath(os.path.join(obj_folder, raw))
        if os.path.isfile(rel_path):
            return os.path.abspath(rel_path), None
    # 3) Match Blender image by filepath_raw, filepath, or name
    for img in getattr(bpy.data, "images", []):
        if img.type != "IMAGE":
            continue
        fp = getattr(img, "filepath_raw", None) or getattr(img, "filepath", None)
        if not fp:
            if (img.name or "").strip() and (base == (img.name or "").strip() or os.path.basename(img.name or "") == base):
                return "PACKED", img
            continue
        ab = bpy.path.abspath(fp)
        if ab and os.path.isfile(ab) and (os.path.basename(ab) == base or ab.endswith(raw) or raw in ab.replace("\\", "/")):
            return ab, None
        if (img.name or "").strip() and (base == (img.name or "").strip() or os.path.basename(img.name or "") == base):
            if ab and os.path.isfile(ab):
                return ab, None
            return "PACKED", img
    return None, raw


def _parse_mtl_copy_textures_and_rewrite(obj_folder, mtl_path, log_lines):
    """
    Parse .mtl, for each map_Kd/map_Ks/map_Bump/map_d/map_Ka copy texture into obj_folder,
    rewrite line to filename only. Ensure unique filenames.
    Returns (num_copied, list_of_missing_paths).
    """
    if not os.path.isfile(mtl_path):
        return 0, []
    map_prefixes = ("map_Kd", "map_Ks", "map_Bump", "map_d", "map_Ka", "map_Ns", "map_Ke", "map_refl")
    try:
        with open(mtl_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except Exception as exc:
        log(f"  Could not read MTL {mtl_path}: {exc}", log_lines, "WARN")
        return 0, []

    used_filenames = set()
    new_lines = []
    copied = 0
    missing = []

    def unique_filename(base):
        base = base or "tex.png"
        if base not in used_filenames:
            used_filenames.add(base)
            return base
        stem, ext = os.path.splitext(base)
        for i in range(1, 9999):
            cand = f"{stem}__{i}{ext}"
            if cand not in used_filenames:
                used_filenames.add(cand)
                return cand
        return base

    for line in lines:
        stripped = line.rstrip("\n\r")
        rest = stripped.lstrip()
        if not rest:
            new_lines.append(line)
            continue
        parts = rest.split(None, 1)
        key = parts[0] if parts else ""
        if key in map_prefixes and len(parts) >= 2:
            path_value = parts[1].strip()
            src_ab, miss = _resolve_blender_image_for_mtl(path_value, obj_folder)
            if miss is not None and src_ab is None:
                missing.append(path_value)
                new_lines.append(line)
                continue
            if src_ab == "PACKED":
                img = miss
                base = (img.name or "image").replace(" ", "_")
                if not base.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):
                    base = base + ".png"
                base = os.path.basename(base)
                base = unique_filename(base)
                dst = os.path.join(obj_folder, base)
                try:
                    img.save_render(dst)
                    copied += 1
                    log(f"  Copied texture (packed): {base}", log_lines)
                except Exception as exc:
                    log(f"  Could not save packed image '{base}': {exc}", log_lines, "WARN")
                    missing.append(path_value)
                new_lines.append(f"{key} {base}\n")
                continue
            if src_ab and os.path.isfile(src_ab):
                base = unique_filename(os.path.basename(src_ab))
                dst = os.path.join(obj_folder, base)
                if os.path.abspath(src_ab) != os.path.abspath(dst):
                    try:
                        shutil.copy2(src_ab, dst)
                        copied += 1
                        log(f"  Copied texture: {base}", log_lines)
                    except Exception as exc:
                        log(f"  Could not copy '{base}': {exc}", log_lines, "WARN")
                        missing.append(path_value)
                new_lines.append(f"{key} {base}\n")
            else:
                new_lines.append(line)
        else:
            new_lines.append(line)

    # Save packed images that might be referenced by materials but not yet on disk
    _save_packed_images_to_folder(obj_folder, log_lines)

    try:
        with open(mtl_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as exc:
        log(f"  Could not rewrite MTL {mtl_path}: {exc}", log_lines, "WARN")

    return copied, missing


def _copy_textures_to_folder(dest_folder, log_lines):
    """Copy image textures that exist on disk into dest_folder; save packed images to folder."""
    for img in bpy.data.images:
        if img.type != "IMAGE":
            continue
        fp = getattr(img, "filepath", None) or getattr(img, "filepath_raw", None)
        if not fp:
            continue
        src = bpy.path.abspath(fp)
        if not src or not os.path.isfile(src):
            continue
        base = os.path.basename(src) or (img.name or "image") + ".png"
        dst = os.path.join(dest_folder, base)
        if os.path.abspath(src) != os.path.abspath(dst):
            try:
                shutil.copy2(src, dst)
            except Exception as exc:
                log(f"  Could not copy texture '{base}': {exc}", log_lines, "WARN")
    _save_packed_images_to_folder(dest_folder, log_lines)


def conversion_only_export(output_dir, model_name, armature, mesh_objs, log_lines):
    """Export VRM armature + meshes as-is (no ARP) via export_all_formats. Success = FBX ok."""
    log("Attempting conversion-only export (no ARP)", log_lines)
    meshes = list(mesh_objs) if mesh_objs else [mesh_objs] if isinstance(mesh_objs, bpy.types.Object) else []
    if not meshes and isinstance(mesh_objs, bpy.types.Object) and mesh_objs.type == "MESH":
        meshes = [mesh_objs]
    if not meshes:
        meshes = [m for m in bpy.data.objects if m.type == "MESH"]
    report = export_all_formats(armature, meshes, model_name, output_dir, log_lines)
    fbx_ok = report.get("FBX", (False, ""))[0]
    return fbx_ok


# ---------------------------------------------------------------------------
# SINGLE-FILE PIPELINE
# ---------------------------------------------------------------------------

def process_single_vrm(vrm_path, output_dir, done_dir, failed_dir, log_lines, skip_arp, headless):
    """
    Full pipeline for one .vrm file.
    Exports rigged model (armature + all meshes) to per-model subfolders:
    output_dir/fbx/<model>, output_dir/glb/<model>, output_dir/dae/<model>, output_dir/obj/<model>.
    Returns ("arp" | "fallback" | "failed", message).
    """
    model_name = safe_name(vrm_path)
    log(f"{'='*60}", log_lines)
    log(f"Processing: {vrm_path}", log_lines)
    log(f"Output dir: {output_dir} (per-model: fbx/{model_name}, glb/{model_name}, dae/{model_name}, obj/{model_name})", log_lines)
    log(f"{'='*60}", log_lines)

    clean_scene(log_lines)
    vrm_ok, arp_ok = ensure_addons(log_lines)
    if not vrm_ok:
        log("VRM addon could not be enabled. Skipping file.", log_lines, "ERROR")
        return "failed", "VRM addon missing"

    if not import_vrm(vrm_path, log_lines):
        return "failed", "VRM import failed"

    armature = find_main_armature(log_lines)
    all_meshes = find_all_meshes(log_lines)
    if not armature:
        return "failed", "No armature"
    if not all_meshes:
        return "failed", "No meshes"

    for obj in [armature] + all_meshes:
        apply_transforms(obj, log_lines)

    try_arp = not skip_arp and not headless and not bpy.app.background
    arp_success = False
    arp_rig = None
    main_mesh = find_main_mesh(log_lines)

    if try_arp and main_mesh:
        override, ok = get_view3d_override_full(log_lines)
        if ok:
            arp_success, arp_rig = run_arp_sequence(armature, main_mesh, override, log_lines)
        else:
            log("Cannot run ARP: no valid VIEW_3D override", log_lines, "WARN")
        if arp_rig is None:
            arp_rig = armature

    if not arp_success:
        arp_rig = armature

    # Re-collect meshes after ARP (bind may affect mesh set)
    mesh_list = find_all_meshes(log_lines)

    if arp_success:
        report = export_all_formats(arp_rig, mesh_list, model_name, output_dir, log_lines)
        fbx_ok = report.get("FBX", (False, ""))[0]
        if not fbx_ok:
            log("ARP succeeded but FBX export failed; trying conversion-only", log_lines, "WARN")
            fbx_ok = conversion_only_export(output_dir, model_name, armature, mesh_list, log_lines)
        if fbx_ok:
            return "arp", "ARP succeeded"
        return "failed", "ARP and conversion-only export failed"
    else:
        if conversion_only_export(output_dir, model_name, armature, mesh_list, log_lines):
            log("ARP failed, but conversion-only export succeeded", log_lines)
            return "fallback", "Conversion-only succeeded"
        return "failed", "ARP and conversion-only export failed"


# ---------------------------------------------------------------------------
# PIPELINE RUNNER
# ---------------------------------------------------------------------------

def run_pipeline(input_dir, output_dir, done_dir, failed_dir, headless=False):
    vrm_files = sorted([
        os.path.join(input_dir, f)
        for f in os.listdir(input_dir)
        if f.lower().endswith(".vrm") and os.path.isfile(os.path.join(input_dir, f))
    ])

    if not vrm_files:
        print("No .vrm files found in: " + input_dir)
        bpy.ops.wm.quit_blender()
        return

    log_lines = []
    log(f"Pipeline started. Files: {len(vrm_files)}", log_lines)
    log(f"Input: {input_dir}", log_lines)
    log(f"Output: {output_dir}", log_lines)
    log(f"Done: {done_dir}", log_lines)
    log(f"Failed: {failed_dir}", log_lines)
    log(f"Blender: {bpy.app.version_string}", log_lines)
    log(f"Background: {bpy.app.background}", log_lines)
    log(f"Headless flag: {headless}", log_lines)

    skip_arp = not check_arp_version_compat(log_lines)
    if headless or bpy.app.background:
        log("Headless/background: ARP will be skipped; conversion-only export will be used when possible.", log_lines, "WARN")

    arp_success_count = 0
    fallback_success_count = 0
    failed_count = 0

    for idx, vrm_path in enumerate(vrm_files, 1):
        filename = os.path.basename(vrm_path)
        log(f"\n--- File {idx}/{len(vrm_files)}: {filename} ---", log_lines)
        try:
            status, msg = process_single_vrm(
                vrm_path, output_dir, done_dir, failed_dir,
                log_lines, skip_arp=skip_arp, headless=headless
            )
            if status == "arp":
                arp_success_count += 1
                dest = os.path.join(done_dir, filename)
                shutil.move(vrm_path, dest)
                log(f"Moved to done: {dest}", log_lines)
            elif status == "fallback":
                fallback_success_count += 1
                dest = os.path.join(done_dir, filename)
                shutil.move(vrm_path, dest)
                log(f"Moved to done (fallback): {dest}", log_lines)
            else:
                failed_count += 1
                dest = os.path.join(failed_dir, filename)
                try:
                    shutil.move(vrm_path, dest)
                    log(f"Moved to failed: {dest}", log_lines)
                except Exception as exc:
                    log(f"Failed to move to failed: {exc}", log_lines, "WARN")
        except Exception as exc:
            log(f"Unhandled exception: {exc}", log_lines, "ERROR")
            log(traceback.format_exc(), log_lines, "ERROR")
            failed_count += 1
            try:
                shutil.move(vrm_path, os.path.join(failed_dir, filename))
            except Exception:
                pass

    total = len(vrm_files)
    log(f"\n{'='*60}", log_lines)
    log("Pipeline complete - Summary", log_lines)
    log(f"  total:          {total}", log_lines)
    log(f"  arp_success:    {arp_success_count}", log_lines)
    log(f"  fallback_success: {fallback_success_count}", log_lines)
    log(f"  failed:         {failed_count}", log_lines)
    log(f"{'='*60}", log_lines)

    log_filename = datetime.datetime.now().strftime("vrm_pipeline_%Y%m%d_%H%M%S.log")
    log_path = os.path.join(output_dir, log_filename)
    try:
        with open(log_path, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines))
        print(f"Log written to: {log_path}")
    except Exception as exc:
        print(f"Failed to write log: {exc}")

    exit_code = 2 if failed_count > 0 else 0
    print(f"Quitting Blender with exit code: {exit_code}", flush=True)
    os._exit(exit_code)


def main():
    argv = sys.argv
    separator_idx = None
    for i, arg in enumerate(argv):
        if arg == "--":
            separator_idx = i
            break
    user_args = []
    if separator_idx is not None:
        user_args = argv[separator_idx + 1:]

    headless = "--headless" in user_args
    user_args = [a for a in user_args if a != "--headless"]

    if len(user_args) >= 1:
        input_dir = user_args[0]
    else:
        input_dir = os.path.join(SCRIPT_DIR, "vrm_in")
    if len(user_args) >= 2:
        output_dir = user_args[1]
    else:
        output_dir = os.path.join(SCRIPT_DIR, "fbx_out")
    if len(user_args) >= 3:
        done_dir = user_args[2]
    else:
        done_dir = os.path.join(SCRIPT_DIR, "vrm_done")
    if len(user_args) >= 4:
        failed_dir = user_args[3]
    else:
        failed_dir = os.path.join(SCRIPT_DIR, "vrm_failed")

    for d in [input_dir, output_dir, done_dir, failed_dir]:
        ensure_dir(d)

    def _deferred():
        run_pipeline(input_dir, output_dir, done_dir, failed_dir, headless=headless)
        return None

    bpy.app.timers.register(_deferred, first_interval=0.5)


if __name__ == "__main__":
    main()
