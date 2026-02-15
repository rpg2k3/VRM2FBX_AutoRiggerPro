"""
dump_ops.py
===========
Diagnostic script that prints all Blender operators matching pipeline-relevant
keywords, plus addon version info. Run this to verify your addons are installed
and their operators are registered correctly.

Usage:
    "D:\\DevTools\\blender 4.1\\blender-4.1.1-windows-x64\\blender.exe" --background --python dump_ops.py
"""

import bpy
import sys
import addon_utils

KEYWORDS = ["vrm", "arp", "export", "fbx"]


def dump_matching_operators():
    """Print all bpy.ops entries whose full path contains any keyword."""
    print("=" * 70)
    print("OPERATOR DUMP")
    print(f"Keywords: {KEYWORDS}")
    print("=" * 70)

    matches = {}
    for keyword in KEYWORDS:
        matches[keyword] = []

    # Walk all operator categories
    for category_name in dir(bpy.ops):
        if category_name.startswith("_"):
            continue
        category = getattr(bpy.ops, category_name, None)
        if category is None:
            continue
        for op_name in dir(category):
            if op_name.startswith("_"):
                continue
            full_name = f"bpy.ops.{category_name}.{op_name}"
            full_lower = full_name.lower()
            for keyword in KEYWORDS:
                if keyword.lower() in full_lower:
                    matches[keyword].append(full_name)

    total = 0
    for keyword in KEYWORDS:
        ops = sorted(set(matches[keyword]))
        print(f"\n--- Operators matching '{keyword}' ({len(ops)} found) ---")
        for op in ops:
            print(f"  {op}")
        total += len(ops)

    print(f"\nTotal matching operators: {total}")


def dump_addon_info():
    """Print version info for installed addons relevant to the pipeline."""
    print("\n" + "=" * 70)
    print("ADDON INFO")
    print("=" * 70)

    target_keywords = ["vrm", "auto_rig", "rig_tools", "auto-rig"]

    for mod in addon_utils.modules():
        mod_name = mod.__name__.lower()
        bl_info = getattr(mod, "bl_info", {})

        # Check module name
        is_relevant = any(kw in mod_name for kw in target_keywords)

        # Check bl_info name field
        addon_display_name = bl_info.get("name", "")
        if not is_relevant:
            is_relevant = any(kw in addon_display_name.lower() for kw in target_keywords)

        if is_relevant:
            version = bl_info.get("version", "unknown")
            author = bl_info.get("author", "unknown")
            description = bl_info.get("description", "")
            is_enabled = addon_utils.check(mod.__name__)[0]

            print(f"\n  Module:      {mod.__name__}")
            print(f"  Name:        {addon_display_name}")
            print(f"  Version:     {version}")
            print(f"  Author:      {author}")
            print(f"  Enabled:     {is_enabled}")
            print(f"  Description: {description}")

    print(f"\n  Blender:     {bpy.app.version_string}")
    print(f"  Build:       {bpy.app.build_hash.decode('utf-8', errors='replace')}")


def main():
    print(f"\nBlender {bpy.app.version_string}")
    print(f"Python {sys.version}\n")

    dump_addon_info()
    dump_matching_operators()

    print("\n" + "=" * 70)
    print("DUMP COMPLETE")
    print("=" * 70)


if __name__ == "__main__":
    main()
