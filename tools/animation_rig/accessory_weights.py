"""Opt-in skin correction for the Warlock animation authoring candidate.

The shipping FBX supplies dormant accessory bones but no usable cloth/belt
weights. This profile makes the existing lower coat and belt respond to those
existing channels without changing geometry, rest transforms, or hierarchy.
It is deliberately not applied to the published mod. Exporting these controls
requires a reviewed candidate body FBX with these weights as well as its clips.
"""

from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path


PROFILE = "localized-v1"
EXPECTED_VERTEX_COUNT = 29123
# Audited on the shipping FBX using Blender 5.2's importer. The masks were
# rendered in four views before selection: component 0 is continuous cloth;
# component 5 is the waist belt; components 58/91 are its front buckle pieces.
# The separate rigid thigh plates and underlying trousers are excluded.
COMPONENT_CONTRACT = {
    "garment": (2683, "0be5f5a15d481b32790cec6824eedc7369669ae9569e1f0d15cc30ec3505d8fa"),
    "belt": (594, "1505909eb60ac86761f90538519ec8f63a5f153fd2093b8e247f71eb7473de47"),
    "buckle": (115, "1bf54651ca1687bce88cfd72a298aaff384b914edcdcdfdfdd0e56d0386d1613"),
    "buckle_trim": (40, "da5b685eaefd171b057c4ebe5e112fcb90017be163c3764450254219cf265e1c"),
}
COAT_BONES = ("j_whip_parent", "j_whip_dynamic")
BELT_BONES = tuple("j_loot_sack_component%d" % n for n in range(1, 6))


def _index_digest(indices):
    return hashlib.sha256(",".join(map(str, sorted(indices))).encode("ascii")).hexdigest()


def _components(mesh):
    parents = list(range(len(mesh.data.vertices)))

    def find(n):
        while parents[n] != n:
            parents[n] = parents[parents[n]]
            n = parents[n]
        return n

    for edge in mesh.data.edges:
        a, b = find(edge.vertices[0]), find(edge.vertices[1])
        parents[b] = a
    parts = defaultdict(list)
    for vertex in mesh.data.vertices:
        parts[find(vertex.index)].append(vertex.index)
    signatures = {(len(v), _index_digest(v)): v for v in parts.values()}
    result = {}
    for label, signature in COMPONENT_CONTRACT.items():
        if signature not in signatures:
            raise ValueError("Shipping component contract differs: " + label)
        result[label] = signatures[signature]
    return result


def _weights(mesh):
    names = {g.index: g.name for g in mesh.vertex_groups}
    return {
        v.index: {names[g.group]: float(g.weight) for g in v.groups if g.weight > 0}
        for v in mesh.data.vertices
    }


def _digest(rows, indices):
    payload = [[i, sorted(rows[i].items())] for i in sorted(indices)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def _smoothstep(value):
    value = min(1.0, max(0.0, value))
    return value * value * (3.0 - 2.0 * value)


def _blend_weights(original, corrective, strength):
    """Keep the corrective share exact and retain at most four skin influences."""
    corrective = {name: weight for name, weight in corrective.items() if weight > 1e-5}
    total = sum(corrective.values())
    corrective = {name: weight / total * strength for name, weight in corrective.items()}
    slots = 4 - len(corrective)
    base = sorted(original.items(), key=lambda item: (-item[1], item[0]))[:slots]
    base_sum = sum(weight for _, weight in base)
    if base_sum <= 0:
        raise ValueError("Selected accessory vertex has no original positive skin weights")
    result = {name: weight / base_sum * (1.0 - strength) for name, weight in base}
    for name, weight in corrective.items():
        result[name] = result.get(name, 0.0) + weight
    total = sum(result.values())
    return {name: value / total for name, value in result.items() if value > 0}


def _bounds(points):
    return {
        "min": [min(p[i] for p in points) for i in range(3)],
        "max": [max(p[i] for p in points) for i in range(3)],
    }


def apply_accessory_weights(mesh, game_armature, report_path=None, profile=PROFILE):
    """Apply the opt-in profile once and return its complete mask/weight record.

    Call immediately after importing the shipping FBX, before changing mesh
    object transforms, and after clearing imported pose matrix bases to identity.
    ``game_armature`` is the preserved GAME armature.
    The animator rig must make belt channels follow ``j_hips`` at neutral;
    their original skeleton parent remains ``j_loot_sack``. The second coat
    channel must receive an independent evaluated pose despite being a child
    of the first. Bake those evaluated transforms into the unchanged skeleton.
    """
    if profile != PROFILE:
        raise ValueError("Unknown accessory skin profile: " + str(profile))
    if mesh.get("warlock_accessory_skin_profile"):
        raise ValueError("Accessory skin profile is already applied; import a fresh shipping FBX")
    if mesh.type != "MESH" or game_armature.type != "ARMATURE":
        raise TypeError("Expected mesh and GAME armature objects")
    if len(mesh.data.vertices) != EXPECTED_VERTEX_COUNT:
        raise ValueError("Accessory masks require the exact 29,123-vertex shipping body")
    if not mesh.data.materials or not mesh.data.materials[0].name.startswith("DoomRocket_Armor"):
        raise ValueError("Expected shipping Armor material in slot zero")
    for name in COAT_BONES + BELT_BONES + ("j_hips",):
        if name not in game_armature.data.bones:
            raise ValueError("GAME skeleton is missing " + name)
    pose_error = max(
        abs(b.matrix_basis[r][c] - (1.0 if r == c else 0.0))
        for b in game_armature.pose.bones for r in range(4) for c in range(4)
    )
    if pose_error > 1e-5:
        raise ValueError("Clear imported GAME pose matrix bases to identity before applying accessory skin")

    components = _components(mesh)
    positions = {v.index: tuple(mesh.matrix_world @ v.co) for v in mesh.data.vertices}
    before = _weights(mesh)
    dormant = set(COAT_BONES + BELT_BONES)
    if any(dormant.intersection(row) for row in before.values()):
        raise ValueError("A dormant correction channel is already weighted; manual review required")
    component_vertices = {i for values in components.values() for i in values}
    for polygon in mesh.data.polygons:
        if polygon.vertices[0] in component_vertices and polygon.material_index != 0:
            raise ValueError("Accessory mask touches a non-Armor material")
    garment_bounds = _bounds([positions[i] for i in components["garment"]])
    # Meter-space limits fail closed on scale/axis drift before any skin changes.
    if not (0.23 < garment_bounds["min"][2] < 0.25 and 1.40 < garment_bounds["max"][2] < 1.43):
        raise ValueError("Shipping garment meter-space bounds differ; check FBX import axes/scale")

    planned = {}
    areas = {}
    # Hanging cloth only: full response below 0.46 m; smoothly pinned by 0.82 m.
    # Two overlapping sides leave the original gait contribution at >= 10%.
    for index in components["garment"]:
        x, _, z = positions[index]
        strength = 0.90 * _smoothstep((0.82 - z) / 0.36)
        if strength <= 1e-5:
            continue
        right = _smoothstep((x + 0.08) / 0.16)
        planned[index] = _blend_weights(before[index], {COAT_BONES[0]: 1 - right, COAT_BONES[1]: right}, strength)
        areas[index] = "lower_coat"

    # Correction handles follow the belt surface clockwise from front center.
    anchors = ((0.0, 0.025), (-0.23, -0.08), (0.23, -0.08), (-0.17, -0.35), (0.17, -0.35))
    for index in components["belt"]:
        x, y, _ = positions[index]
        closest = sorted(range(5), key=lambda n: (x - anchors[n][0]) ** 2 + (y - anchors[n][1]) ** 2)[:2]
        weights = {
            BELT_BONES[n]: math.exp(-((x - anchors[n][0]) ** 2 + (y - anchors[n][1]) ** 2) / 0.018)
            for n in closest
        }
        planned[index] = _blend_weights(before[index], weights, 0.82)
        areas[index] = "waist_belt"
    # Buckle pieces stay rigid on a single front-center correction channel.
    # The remainder follows their original pelvis skin influence.
    for label in ("buckle", "buckle_trim"):
        for index in components[label]:
            planned[index] = _blend_weights(before[index], {BELT_BONES[0]: 1.0}, 0.82)
            areas[index] = label

    affected = sorted(planned)
    unaffected = set(before) - set(affected)
    outside_before = _digest(before, unaffected)
    for index, row in planned.items():
        for name in before[index]:
            mesh.vertex_groups[name].remove([index])
        for name, value in row.items():
            group = mesh.vertex_groups.get(name) or mesh.vertex_groups.new(name=name)
            group.add([index], value, "REPLACE")
    after = _weights(mesh)
    outside_after = _digest(after, unaffected)
    if outside_before != outside_after:
        raise AssertionError("Accessory profile changed weights outside its explicit mask")
    max_influences = max(len(after[i]) for i in affected)
    normalization_error = max(abs(sum(after[i].values()) - 1.0) for i in affected)
    if max_influences > 4 or normalization_error > 1e-6:
        raise AssertionError("Corrective weights violate the four-influence normalized skin contract")

    controls = []
    labels = ("Coat left", "Coat right", "Belt front", "Belt left", "Belt right", "Belt back left", "Belt back right")
    for name, label in zip(COAT_BONES + BELT_BONES, labels):
        selected = [i for i in affected if after[i].get(name, 0.0) > 0.0]
        total = sum(after[i][name] for i in selected)
        centroid = [sum(positions[i][a] * after[i][name] for i in selected) / total for a in range(3)]
        controls.append({
            "bone": name,
            "control": "CTRL-" + label.lower().replace(" ", "-"),
            "center": centroid,
            "follow_bone": "j_hips",
            "kind": "cloth" if name in COAT_BONES else "belt",
            "label": label,
            "category": "cloth" if name in COAT_BONES else "belt",
            "control_position_world": centroid,
            "rest_pivot_world": list(game_armature.matrix_world @ game_armature.data.bones[name].head_local),
            "baseline_parent": "j_hips",
            "translation_only": name in BELT_BONES,
            "weighted_vertex_indices": selected,
            "weighted_vertices": len(selected),
            "weight_sum": total,
        })
    report = {
        "schema": 1,
        "profile": PROFILE,
        "source_mesh": mesh.name,
        "requires_candidate_body_export": True,
        "published_body_unchanged": True,
        "geometry_and_skeleton_unchanged": True,
        "neutral_pose_requirement": "Belt and coat channels follow the pelvis with independent evaluated control deltas; keep the GAME hierarchy unchanged.",
        "engine_boundary": "Export reviewed candidate body weights and baked existing bone tracks together. Clips alone cannot add cloth/belt deformation to the current shipping body.",
        "selection_evidence": "Four-view material masks: continuous Armor garment below world Z 0.82 m, main waist belt, front buckle and trim. Excludes rigid thigh plates, trousers, torso, head, limbs, and backpack.",
        "component_masks": {label: {"vertex_indices": indices, "bounds_world": _bounds([positions[i] for i in indices])} for label, indices in components.items()},
        "affected_vertices": len(affected),
        "unaffected_vertices": len(unaffected),
        "outside_mask_unchanged": outside_before == outside_after,
        "outside_mask_weights_sha256": outside_after,
        "max_affected_influences": max_influences,
        "max_affected_normalization_error": normalization_error,
        "controls": controls,
        "changes": [{"vertex": i, "area": areas[i], "world_rest_position": positions[i], "before": before[i], "after": after[i]} for i in affected],
    }
    mesh["warlock_accessory_skin_profile"] = PROFILE
    if report_path is not None:
        path = Path(report_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report

