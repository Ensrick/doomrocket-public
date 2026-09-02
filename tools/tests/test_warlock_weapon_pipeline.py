#!/usr/bin/env python3
"""Deterministic source regressions for Crunch's launcher and rocket.

The weapon used to be the old Dalo placeholder even after the Warlock body art
was updated.  These tests identify the *mesh data*, not merely the stable unit
filenames, and pin the authored set-03/set-04 texture channel contract.  The
small binary-FBX reader is deliberately local and dependency-free: Blender is
not required to prove which mesh was packaged.
"""

from __future__ import annotations

import hashlib
import math
import re
import struct
import subprocess
import sys
import unittest
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

try:
    from PIL import Image
except ImportError as exc:
    raise SystemExit("Pillow is required for Warlock weapon regressions") from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
ART_ROOT = REPO_ROOT.parent / "_warlock_bombardier_art"
CRUNCH_TEXTURES = ART_ROOT / "crunch_textures"
ROCKET_UNIT_DIR = REPO_ROOT / "units" / "rocket"
ROCKET_TEXTURE_DIR = REPO_ROOT / "textures" / "rocket"
BUNDLE_ROOT = REPO_ROOT / "bundleV2"

sys.path.insert(0, str(REPO_ROOT / "tools"))
from splice_bundle_resource import walk as walk_bundle  # noqa: E402
from strip_bundle_resource import murmur64a, read_bundle  # noqa: E402


# Immutable provenance.  The .blend and ZIP are the exact files Crunch sent;
# the two FBXs are the isolated mesh exports derived from that scene.  Shipping
# FBXs acquire attachment nodes, so their whole-file hashes are intentionally
# *not* expected to equal the isolated exports.
SOURCE_SHA256 = {
    "blend": "ab6ebc9ef45cea6e402bbd0415c2d40716824552c2ab514947902d1eac06c1b2",
    "texture_zip": "551852ee9a9fa99995921e4b6b5cf898d4c17b51486e22fe7772d980f92c2187",
    "launcher_fbx": "1682ecd2979ed988c2254dbabfd20e1d2e5c7d4869ad39b3727872f914f9df69",
    "rocket_fbx": "968539eca60f065b90ed5899195f1eb2dfd6ed2b77ed87a8958ca976dcc0e0ea",
    "tube_fbx": "eefa15569e53784077973801f3e02fc1145af1e5014e3d275d4f74a14f2dcdc9",
}

FULL_LAUNCHER_VERTEX_COUNT = 4916
MVP_LAUNCHER_VERTEX_COUNT = 3308
DEFERRED_HOSE_VERTEX_COUNT = 1608
DEFERRED_HOSE_TRIANGLE_COUNT = 3024
MVP_LAUNCHER_TRIANGLE_COUNT = 6094
DEFERRED_HOSE_COMPONENT_SIZES = (180,) * 7 + (122,) * 2 + (26,) * 4

# Decoded RGBA baselines for the authored images.  PNG container metadata or
# recompression may change without weakening the actual pixel assertion.
EXPECTED_RGBA = {
    "wb_weapon_df": "f3deef111b8e80eba59e1c2be1efb0a85baaa3f23616dc6d1486b4848d3d1a6f",
    "wb_weapon_nm": "21021c6045dea9e25424bd891031b5be771454678e436ab2e9cd9467055c1a4f",
    "wb_weapon_e": "9185fd2e492d2daf1f826ee37ff67f4a58deeb6888484a408c636f14902471de",
    "wb_weapon_r": "867c1561aafa6234021ae4d938eb28162c0eb5c2cb9f475e5f9fdbd1a3f421a4",
    "wb_weapon_m": "b39d91cb5bc15a9bc973d72a1d3efc847afe02f77ad45c978a635348ebe455bd",
    "wb_weapon_ao": "49b667da7ac6e6bf74cfb21dbde6551fdad7db06d8dc127d401e1d4956cc9e88",
    "wb_rocket_df": "0f2454d2bfd2f20d52dbe1bbe4abb4582f1dde78ae59af9580cf2c374f460b08",
    "wb_rocket_nm": "26b8f5db6b2e1338f22b1a6b2c8fe52f6736b1e783e4c9a563da42bd92b9cbe7",
    "wb_rocket_e": "c1809da6f7c209278c8d701f4040d98064e8d5dadb28c0294702124c19f36f33",
    "wb_rocket_r": "2b21589b36f6a3fe2395ae5d6354cb4b814895b2550dda7c860369011b2215a5",
    "wb_rocket_m": "191aba7b48c52f2fdfe32a331ca076dd468e98de150017df82cb0ca9a017af29",
    "wb_rocket_ao": "e899520017d02889b68152c1972ae271ea888a160c57549f0ce0799e514d63ed",
}

OLD_DALO_FBX_SHA256 = {
    "pRocketLauncher.fbx": "80caf376ba9210b83ded30587f9d2a3663f6614d4b624513307d06dec0e64d5f",
    "SM_Rocket.fbx": "aff853dc8c420b7fd94f7273166025e1baf49c9828274b05ccd5647ab43294c7",
}

OLD_DALO_FBX_BLOBS = {
    "pRocketLauncher.fbx": "4afd3ff155889b44760ff41500bca7e1bf6ccafa",
    "SM_Rocket.fbx": "445636e36fc62a8aef8883d2f59ed85eaa6707a0",
}

CRUNCH_EXPORT_GEOMETRY = {
    "launcher": (4916, 9118, "c4f65cea8b2546cd5e75ca80c505cf67b0737387f873e14e1007f10d0dd901e3"),
    "rocket": (622, 1240, "ef545765bcbb4b88b075e953630b2142f184abf9cb523abf01932358e11815cd"),
}

# Blender rebuilds the source scene's original polygons (the isolated FBXs
# above are triangulated), but keeps all vertices and surfaces.  Pin the final
# polygon streams as well as comparing a scale/rotation/translation-invariant
# shape profile to Crunch's isolated exports.
SHIPPING_GEOMETRY = {
    "launcher": (3308, 3365, "d5affe35d35fb1698ca1880686e082edb3e2855065d467e5c56c2f2a93150667"),
    "rocket": (622, 672, "6830f43335bfe9fc008137f986af2dc57de44cea3ff16d651ac10faed808876e"),
}

CRUNCH_UV_SHA256 = {
    "launcher": "db3c98bf11a8c4025476e0215ee29c5ecf043833482d87913bb8b16958a7001f",
    "rocket": "a0639c19b8347aac26b54aa283f42fd3e8cb16c07aed56ea6eab824f2d4f79cb",
}

MVP_LAUNCHER_UV = (
    8882,
    "3d3d9b7b73cd4e1009ee0f01ecde6eea926813472197b7ed72d5932ca1879b47",
)

# Local-remapped triangle connectivity of the reviewed retained/deferred
# blocks in Crunch's full isolated launcher export.  This pins the split itself
# while SHIPPING_GEOMETRY pins Blender's retained polygon stream.
CRUNCH_LAUNCHER_SPLIT_TOPOLOGY = {
    "mvp": "42f22bd4b3d2b94699d86491d14cd3bcf99cba1f9423ca7f1fbb2954f5990f82",
    "backpack_tether": "dba54aca8f082877815c5adef336d8302fd1978a306f0c051cdf1beeb79adaed",
}


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def file_sha256(path: Path) -> str:
    return sha256(path.read_bytes())


def rgba(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.convert("RGBA")


@dataclass(frozen=True)
class FbxNode:
    name: str
    properties: tuple[Any, ...]
    children: tuple["FbxNode", ...]

    def descendants(self, name: str | None = None) -> Iterator["FbxNode"]:
        for child in self.children:
            if name is None or child.name == name:
                yield child
            yield from child.descendants(name)

    def child(self, name: str) -> "FbxNode":
        matches = [child for child in self.children if child.name == name]
        if len(matches) != 1:
            raise AssertionError(
                f"FBX node {self.name!r} expected one {name!r} child, got {len(matches)}"
            )
        return matches[0]


class BinaryFbx:
    MAGIC = b"Kaydara FBX Binary  \x00\x1a\x00"

    def __init__(self, path: Path):
        self.path = path
        self.data = path.read_bytes()
        self._parse()

    @classmethod
    def from_bytes(cls, data: bytes, label: str) -> "BinaryFbx":
        """Parse an immutable Git blob without writing a temporary FBX."""
        instance = cls.__new__(cls)
        instance.path = Path(label)
        instance.data = data
        instance._parse()
        return instance

    def _parse(self) -> None:
        if not self.data.startswith(self.MAGIC):
            raise AssertionError(f"{self.path}: expected a binary FBX")
        self.version = struct.unpack_from("<I", self.data, len(self.MAGIC))[0]
        self.wide = self.version >= 7500
        self.null_size = 25 if self.wide else 13
        self.nodes, offset = self._nodes(len(self.MAGIC) + 4, len(self.data))
        if offset > len(self.data):
            raise AssertionError(f"{path}: FBX node table overran file")

    def _uint(self, offset: int) -> tuple[int, int]:
        code = "<Q" if self.wide else "<I"
        size = 8 if self.wide else 4
        return struct.unpack_from(code, self.data, offset)[0], offset + size

    def _property(self, offset: int) -> tuple[Any, int]:
        kind = chr(self.data[offset])
        offset += 1
        scalar = {
            "Y": ("<h", 2),
            "C": ("<?", 1),
            "I": ("<i", 4),
            "F": ("<f", 4),
            "D": ("<d", 8),
            "L": ("<q", 8),
        }
        if kind in scalar:
            code, size = scalar[kind]
            return struct.unpack_from(code, self.data, offset)[0], offset + size
        if kind in "SR":
            size = struct.unpack_from("<I", self.data, offset)[0]
            offset += 4
            raw = self.data[offset : offset + size]
            if kind == "S":
                return raw.decode("utf-8", errors="strict"), offset + size
            return raw, offset + size
        arrays = {
            "f": ("f", 4),
            "d": ("d", 8),
            "l": ("q", 8),
            "i": ("i", 4),
            "b": ("?", 1),
            "c": ("b", 1),
        }
        if kind in arrays:
            count, encoding, byte_count = struct.unpack_from("<III", self.data, offset)
            offset += 12
            raw = self.data[offset : offset + byte_count]
            if encoding == 1:
                raw = zlib.decompress(raw)
            elif encoding != 0:
                raise AssertionError(f"{self.path}: unsupported FBX array encoding {encoding}")
            code, item_size = arrays[kind]
            expected = count * item_size
            if len(raw) != expected:
                raise AssertionError(
                    f"{self.path}: {kind} array expected {expected} bytes, got {len(raw)}"
                )
            return tuple(value[0] for value in struct.iter_unpack("<" + code, raw)), offset + byte_count
        raise AssertionError(f"{self.path}: unsupported FBX property type {kind!r}")

    def _nodes(self, offset: int, limit: int) -> tuple[tuple[FbxNode, ...], int]:
        nodes: list[FbxNode] = []
        while offset + self.null_size <= limit:
            if self.data[offset : offset + self.null_size] == bytes(self.null_size):
                return tuple(nodes), offset + self.null_size
            start = offset
            end_offset, offset = self._uint(offset)
            property_count, offset = self._uint(offset)
            property_bytes, offset = self._uint(offset)
            name_size = self.data[offset]
            offset += 1
            name = self.data[offset : offset + name_size].decode("utf-8", errors="strict")
            offset += name_size
            properties: list[Any] = []
            property_start = offset
            for _ in range(property_count):
                value, offset = self._property(offset)
                properties.append(value)
            if offset - property_start != property_bytes:
                raise AssertionError(
                    f"{self.path}: property length mismatch in {name!r} at {start}"
                )
            children: tuple[FbxNode, ...] = ()
            child_limit = end_offset - self.null_size
            if offset < child_limit:
                children, offset = self._nodes(offset, end_offset)
            if offset < end_offset:
                # Empty child lists still include their null record.
                offset = end_offset
            if offset != end_offset:
                raise AssertionError(
                    f"{self.path}: node {name!r} ended at {offset}, expected {end_offset}"
                )
            nodes.append(FbxNode(name, tuple(properties), children))
        return tuple(nodes), offset

    def descendants(self, name: str | None = None) -> Iterator[FbxNode]:
        for node in self.nodes:
            if name is None or node.name == name:
                yield node
            yield from node.descendants(name)

    def object_nodes(self, kind: str) -> list[FbxNode]:
        return [
            node
            for node in self.descendants(kind)
            if len(node.properties) >= 3 and isinstance(node.properties[0], int)
        ]


def clean_fbx_name(value: str) -> str:
    """Return the artist-visible part of ``Model::foo\x00\x01Model``."""
    value = value.split("\x00", 1)[0]
    # FBX producers disagree on whether the type prefix is ``Model::foo`` or
    # simply ``Modelfoo``; normalize both without stripping legitimate names.
    value = value.split("::", 1)[-1]
    return value.removeprefix("Model::").removeprefix("Model")


def polygon_count(indices: tuple[int, ...]) -> int:
    return sum(index < 0 for index in indices)


def geometry_signature(node: FbxNode) -> tuple[int, int, str]:
    vertices = node.child("Vertices").properties[0]
    polygons = node.child("PolygonVertexIndex").properties[0]
    # Connectivity is invariant under FBX float precision/version changes and
    # sharply distinguishes the 2024 Dalo meshes from Crunch's final meshes.
    topology = struct.pack(f"<{len(polygons)}q", *polygons)
    return len(vertices) // 3, polygon_count(polygons), sha256(topology)


def geometry_manifest(fbx: BinaryFbx) -> dict[str, tuple[int, int, str]]:
    return {
        clean_fbx_name(node.properties[1]): geometry_signature(node)
        for node in fbx.object_nodes("Geometry")
        if node.properties[2] == "Mesh"
    }


def geometry_by_vertex_count(fbx: BinaryFbx, count: int) -> FbxNode:
    matches = [
        node
        for node in fbx.object_nodes("Geometry")
        if node.properties[2] == "Mesh"
        and len(node.child("Vertices").properties[0]) // 3 == count
    ]
    if len(matches) != 1:
        raise AssertionError(f"{fbx.path}: expected one {count}-vertex mesh, got {len(matches)}")
    return matches[0]


def shape_profile(node: FbxNode) -> tuple[float, ...]:
    """Sorted normalized radius squared for every vertex.

    This remains unchanged by the rigid placement and centimetre-to-metre
    conversion applied to the source weapon.  Comparing every element catches
    geometry substitution while tolerating only FBX float round-off.
    """
    values = node.child("Vertices").properties[0]
    points = tuple(zip(values[0::3], values[1::3], values[2::3]))
    return shape_profile_points(points)


def shape_profile_points(points: tuple[Vector3, ...]) -> tuple[float, ...]:
    """Return the rigid-transform-invariant profile for an explicit subset."""
    if not points:
        raise AssertionError("shape profile requires vertices")
    centroid = tuple(
        sum(point[axis] for point in points) / len(points) for axis in range(3)
    )
    radii = [
        sum((point[axis] - centroid[axis]) ** 2 for axis in range(3))
        for point in points
    ]
    mean_radius = sum(radii) / len(radii)
    return tuple(sorted(radius / mean_radius for radius in radii))


def raw_geometry_points(node: FbxNode) -> tuple[Vector3, ...]:
    values = node.child("Vertices").properties[0]
    return tuple(zip(values[0::3], values[1::3], values[2::3]))


def uv_signature(node: FbxNode) -> tuple[int, str]:
    layers = [child for child in node.children if child.name == "LayerElementUV"]
    if len(layers) != 1:
        raise AssertionError(f"{node.properties[1]!r}: expected one UV layer, got {len(layers)}")
    fields = {child.name: child.properties[0] for child in layers[0].children if child.properties}
    if fields.get("Name") != "UVMap":
        raise AssertionError(f"{node.properties[1]!r}: expected UVMap, got {fields.get('Name')!r}")
    if fields.get("MappingInformationType") != "ByPolygonVertex":
        raise AssertionError(f"{node.properties[1]!r}: UVs must map ByPolygonVertex")
    if fields.get("ReferenceInformationType") != "IndexToDirect":
        raise AssertionError(f"{node.properties[1]!r}: UVs must use IndexToDirect")
    values = fields["UV"]
    return len(values), sha256(struct.pack(f"<{len(values)}d", *values))


def uv_sets_by_vertex(
    node: FbxNode, vertex_count: int | None = None
) -> tuple[tuple[tuple[float, float], ...], ...]:
    """Return semantic UV coordinates per retained vertex.

    Blender may compact/reorder the direct UV bank while preserving the same
    vertex-to-UV mapping.  This representation proves the 3,308-vertex MVP is
    derived from Crunch's full launcher instead of blessing unrelated art.
    """
    total_vertices = len(node.child("Vertices").properties[0]) // 3
    vertex_count = total_vertices if vertex_count is None else vertex_count
    if not 0 < vertex_count <= total_vertices:
        raise AssertionError("invalid retained UV vertex count")
    layers = [child for child in node.children if child.name == "LayerElementUV"]
    if len(layers) != 1:
        raise AssertionError(f"{node.properties[1]!r}: expected one UV layer")
    fields = {
        child.name: child.properties[0]
        for child in layers[0].children
        if child.properties
    }
    values = fields["UV"]
    indices = fields["UVIndex"]
    encoded = node.child("PolygonVertexIndex").properties[0]
    if len(indices) != len(encoded):
        raise AssertionError("UV index stream does not match polygon loops")
    result: list[set[tuple[float, float]]] = [set() for _ in range(vertex_count)]
    polygon: list[tuple[int, int]] = []
    for loop, encoded_index in enumerate(encoded):
        vertex = -encoded_index - 1 if encoded_index < 0 else encoded_index
        polygon.append((vertex, loop))
        if encoded_index < 0:
            retained = [vertex < vertex_count for vertex, _loop in polygon]
            if any(retained) and not all(retained):
                raise AssertionError("reviewed launcher split crosses a polygon")
            if all(retained):
                for retained_vertex, retained_loop in polygon:
                    uv_index = indices[retained_loop]
                    result[retained_vertex].add(
                        (values[uv_index * 2], values[uv_index * 2 + 1])
                    )
            polygon = []
    if polygon:
        raise AssertionError("unterminated FBX polygon while mapping UVs")
    return tuple(tuple(sorted(coordinates)) for coordinates in result)


def model_names(fbx: BinaryFbx) -> set[str]:
    return {
        clean_fbx_name(node.properties[1])
        for node in fbx.object_nodes("Model")
    }


def model_node(fbx: BinaryFbx, name: str, kind: str | None = None) -> FbxNode:
    matches = [
        node
        for node in fbx.object_nodes("Model")
        if clean_fbx_name(node.properties[1]) == name
        and (kind is None or node.properties[2] == kind)
    ]
    if len(matches) != 1:
        raise AssertionError(f"{fbx.path}: expected one Model {name!r}/{kind}, got {len(matches)}")
    return matches[0]


def model_parent_ids(fbx: BinaryFbx) -> dict[int, int]:
    result: dict[int, int] = {}
    for connection in fbx.descendants("C"):
        if (
            len(connection.properties) >= 3
            and connection.properties[0] == "OO"
            and isinstance(connection.properties[1], int)
            and isinstance(connection.properties[2], int)
        ):
            result[connection.properties[1]] = connection.properties[2]
    return result


def require_loaded_rocket_actor_hierarchy(
    fbx: BinaryFbx, parents: dict[int, int] | None = None
) -> None:
    """Require the loaded warhead to inherit the launcher's dropped actor.

    VT2's AIInventoryExtension unlinks a death-dropped inventory unit and
    creates only its ``rp_dropped`` actor.  Doomrocket binds that actor to the
    ``pRocketLauncher`` node, so a sibling ``pRocket`` freezes at the unlink
    pose instead of following physics.
    """
    launcher = model_node(fbx, "pRocketLauncher", "Mesh")
    loaded_rocket = model_node(fbx, "pRocket", "Mesh")
    parents = model_parent_ids(fbx) if parents is None else parents
    if parents.get(loaded_rocket.properties[0]) != launcher.properties[0]:
        raise AssertionError(
            "loaded pRocket must be a direct child of actor-owned pRocketLauncher"
        )


def local_translation(node: FbxNode) -> tuple[float, float, float]:
    blocks = [child for child in node.children if child.name == "Properties70"]
    if len(blocks) != 1:
        raise AssertionError(f"Model {node.properties[1]!r} has no unique Properties70")
    translations = [
        child.properties[-3:]
        for child in blocks[0].children
        if child.name == "P" and child.properties[0] == "Lcl Translation"
    ]
    return tuple(translations[0]) if translations else (0.0, 0.0, 0.0)


Matrix4 = tuple[tuple[float, float, float, float], ...]
Vector3 = tuple[float, float, float]


def matrix_multiply(left: Matrix4, right: Matrix4) -> Matrix4:
    return tuple(
        tuple(
            sum(left[row][index] * right[index][column] for index in range(4))
            for column in range(4)
        )
        for row in range(4)
    )


def transform_point(matrix: Matrix4, point: Vector3) -> Vector3:
    value = (*point, 1.0)
    return tuple(
        sum(matrix[row][column] * value[column] for column in range(4))
        for row in range(3)
    )


def identity_matrix() -> Matrix4:
    return tuple(
        tuple(1.0 if row == column else 0.0 for column in range(4))
        for row in range(4)
    )


def property_vector(
    node: FbxNode, name: str, default: Vector3
) -> Vector3:
    blocks = [child for child in node.children if child.name == "Properties70"]
    if len(blocks) != 1:
        raise AssertionError(f"Model {node.properties[1]!r} has no unique Properties70")
    values = [
        child.properties[-3:]
        for child in blocks[0].children
        if child.name == "P" and child.properties[0] == name
    ]
    if len(values) > 1:
        raise AssertionError(f"Model {node.properties[1]!r} repeats {name}")
    return tuple(values[0]) if values else default


def model_local_matrix(node: FbxNode) -> Matrix4:
    """Return the simple FBX TRS used by both reviewed weapon exports.

    The pinned launcher nodes use the default XYZ Euler order and no pivots,
    offsets, pre-rotation, or post-rotation. Reject those features instead of
    silently approximating a future export with different transform semantics.
    """
    properties = {
        child.properties[0]: child.properties
        for block in node.children
        if block.name == "Properties70"
        for child in block.children
        if child.name == "P" and child.properties
    }
    unsupported = {
        "RotationOffset",
        "RotationPivot",
        "PreRotation",
        "PostRotation",
        "ScalingOffset",
        "ScalingPivot",
    }
    for name in unsupported:
        values = properties.get(name)
        if values and any(abs(float(value)) > 1e-8 for value in values[-3:]):
            raise AssertionError(f"{node.properties[1]!r}: unsupported nonzero {name}")
    rotation_order = properties.get("RotationOrder")
    if rotation_order and int(rotation_order[-1]) != 0:
        raise AssertionError(f"{node.properties[1]!r}: expected XYZ Euler order")

    translation = property_vector(node, "Lcl Translation", (0.0, 0.0, 0.0))
    rotation = tuple(
        math.radians(value)
        for value in property_vector(node, "Lcl Rotation", (0.0, 0.0, 0.0))
    )
    scale = property_vector(node, "Lcl Scaling", (1.0, 1.0, 1.0))
    sine = tuple(math.sin(value) for value in rotation)
    cosine = tuple(math.cos(value) for value in rotation)
    sx, sy, sz = sine
    cx, cy, cz = cosine
    translate: Matrix4 = (
        (1.0, 0.0, 0.0, translation[0]),
        (0.0, 1.0, 0.0, translation[1]),
        (0.0, 0.0, 1.0, translation[2]),
        (0.0, 0.0, 0.0, 1.0),
    )
    rotate_x: Matrix4 = (
        (1.0, 0.0, 0.0, 0.0),
        (0.0, cx, -sx, 0.0),
        (0.0, sx, cx, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    rotate_y: Matrix4 = (
        (cy, 0.0, sy, 0.0),
        (0.0, 1.0, 0.0, 0.0),
        (-sy, 0.0, cy, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    rotate_z: Matrix4 = (
        (cz, -sz, 0.0, 0.0),
        (sz, cz, 0.0, 0.0),
        (0.0, 0.0, 1.0, 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    scaling: Matrix4 = (
        (scale[0], 0.0, 0.0, 0.0),
        (0.0, scale[1], 0.0, 0.0),
        (0.0, 0.0, scale[2], 0.0),
        (0.0, 0.0, 0.0, 1.0),
    )
    rotation_matrix = matrix_multiply(
        rotate_z, matrix_multiply(rotate_y, rotate_x)
    )
    return matrix_multiply(translate, matrix_multiply(rotation_matrix, scaling))


def global_axis_matrix(fbx: BinaryFbx) -> Matrix4:
    """Map FBX file coordinates to canonical (right, up, front) axes."""
    settings = {
        child.properties[0]: int(child.properties[-1])
        for block in fbx.descendants("Properties70")
        for child in block.children
        if child.name == "P"
        and child.properties
        and child.properties[0]
        in {
            "UpAxis",
            "UpAxisSign",
            "FrontAxis",
            "FrontAxisSign",
            "CoordAxis",
            "CoordAxisSign",
        }
    }
    required = {
        "UpAxis",
        "UpAxisSign",
        "FrontAxis",
        "FrontAxisSign",
        "CoordAxis",
        "CoordAxisSign",
    }
    if settings.keys() != required:
        raise AssertionError(f"{fbx.path}: incomplete or repeated FBX axis settings")
    rows = [[0.0] * 4 for _ in range(4)]
    rows[0][settings["CoordAxis"]] = settings["CoordAxisSign"]
    rows[1][settings["UpAxis"]] = settings["UpAxisSign"]
    rows[2][settings["FrontAxis"]] = settings["FrontAxisSign"]
    rows[3][3] = 1.0
    return tuple(tuple(row) for row in rows)


def model_world_matrix(fbx: BinaryFbx, node: FbxNode) -> Matrix4:
    models = {model.properties[0]: model for model in fbx.object_nodes("Model")}
    parents = model_parent_ids(fbx)
    chain: list[FbxNode] = []
    current = node
    visited: set[int] = set()
    while True:
        identifier = current.properties[0]
        if identifier in visited:
            raise AssertionError(f"{fbx.path}: cyclic model hierarchy")
        visited.add(identifier)
        chain.append(current)
        parent = parents.get(identifier)
        if parent not in models:
            break
        current = models[parent]
    result = identity_matrix()
    for member in reversed(chain):
        result = matrix_multiply(result, model_local_matrix(member))
    return result


def geometry_model(fbx: BinaryFbx, geometry: FbxNode) -> FbxNode:
    model_ids = {node.properties[0]: node for node in fbx.object_nodes("Model")}
    matches = [
        connection.properties[2]
        for connection in fbx.descendants("C")
        if len(connection.properties) >= 3
        and connection.properties[0] == "OO"
        and connection.properties[1] == geometry.properties[0]
        and connection.properties[2] in model_ids
    ]
    if len(matches) != 1:
        raise AssertionError(f"{fbx.path}: geometry has {len(matches)} model owners")
    return model_ids[matches[0]]


def canonical_geometry_points(fbx: BinaryFbx, vertex_count: int) -> tuple[Vector3, ...]:
    geometry = geometry_by_vertex_count(fbx, vertex_count)
    model = geometry_model(fbx, geometry)
    transform = matrix_multiply(
        global_axis_matrix(fbx), model_world_matrix(fbx, model)
    )
    values = geometry.child("Vertices").properties[0]
    return tuple(
        transform_point(transform, point)
        for point in zip(values[0::3], values[1::3], values[2::3])
    )


def canonical_model_origin(fbx: BinaryFbx, node: FbxNode) -> Vector3:
    """Return an FBX model node's origin in canonical root-space centimetres."""
    transform = matrix_multiply(
        global_axis_matrix(fbx), model_world_matrix(fbx, node)
    )
    return transform_point(transform, (0.0, 0.0, 0.0))


def point_centroid(points: tuple[Vector3, ...]) -> Vector3:
    if not points:
        raise AssertionError("centroid requires at least one point")
    return tuple(
        sum(point[axis] for point in points) / len(points) for axis in range(3)
    )


def directed_cosine(left: Vector3, right: Vector3) -> float:
    """Return the signed cosine between nonzero vectors."""
    left_length = math.sqrt(sum(value * value for value in left))
    right_length = math.sqrt(sum(value * value for value in right))
    if left_length <= 1e-12 or right_length <= 1e-12:
        raise AssertionError("directed orientation requires nonzero vectors")
    return sum(a * b for a, b in zip(left, right)) / (
        left_length * right_length
    )


def normalized_axes(matrix: Matrix4) -> tuple[Vector3, Vector3, Vector3]:
    columns = tuple(tuple(matrix[row][column] for row in range(3)) for column in range(3))
    result = []
    for column in columns:
        length = math.sqrt(sum(value * value for value in column))
        if length <= 1e-12:
            raise AssertionError("transform contains a zero-length axis")
        result.append(tuple(value / length for value in column))
    return tuple(result)


def principal_axis(points: tuple[Vector3, ...]) -> Vector3:
    centroid = tuple(
        sum(point[axis] for point in points) / len(points) for axis in range(3)
    )
    covariance = tuple(
        tuple(
            sum(
                (point[row] - centroid[row]) * (point[column] - centroid[column])
                for point in points
            )
            / len(points)
            for column in range(3)
        )
        for row in range(3)
    )
    vector: Vector3 = (1.0, 1.0, 1.0)
    for _ in range(40):
        product = tuple(
            sum(covariance[row][column] * vector[column] for column in range(3))
            for row in range(3)
        )
        length = math.sqrt(sum(value * value for value in product))
        if length <= 1e-12:
            raise AssertionError("mesh has no stable principal axis")
        vector = tuple(value / length for value in product)
    return vector


def normalized_origin_envelope_gap(points: tuple[Vector3, ...]) -> float:
    """Distance from the unit origin to its mesh AABB, divided by RMS radius."""
    centroid = tuple(
        sum(point[axis] for point in points) / len(points) for axis in range(3)
    )
    rms_radius = math.sqrt(
        sum(
            sum((point[axis] - centroid[axis]) ** 2 for axis in range(3))
            for point in points
        )
        / len(points)
    )
    gaps = []
    for axis in range(3):
        minimum = min(point[axis] for point in points)
        maximum = max(point[axis] for point in points)
        gaps.append(max(minimum, 0.0, -maximum))
    return math.sqrt(sum(gap * gap for gap in gaps)) / rms_radius


Triangle = tuple[int, int, int]


def triangulated_fbx_faces(node: FbxNode) -> tuple[Triangle, ...]:
    """Return deterministic triangle fans from an FBX polygon index stream."""
    encoded = node.child("PolygonVertexIndex").properties[0]
    polygons: list[tuple[int, ...]] = []
    current: list[int] = []
    for value in encoded:
        current.append(-value - 1 if value < 0 else value)
        if value < 0:
            if len(current) < 3:
                raise AssertionError(f"{node.properties[1]!r}: polygon has fewer than 3 vertices")
            polygons.append(tuple(current))
            current = []
    if current:
        raise AssertionError(f"{node.properties[1]!r}: unterminated FBX polygon")
    return tuple(
        (polygon[0], polygon[index], polygon[index + 1])
        for polygon in polygons
        for index in range(1, len(polygon) - 1)
    )


def local_triangle_subset(
    triangles: tuple[Triangle, ...], start: int, end: int
) -> tuple[Triangle, ...]:
    """Select a closed vertex interval and remap it to local indices."""
    if not 0 <= start < end:
        raise AssertionError("invalid triangle subset interval")
    subset = []
    for triangle in triangles:
        inside = [start <= index < end for index in triangle]
        if any(inside) and not all(inside):
            raise AssertionError(
                f"triangle {triangle} crosses reviewed [{start}, {end}) boundary"
            )
        if all(inside):
            subset.append(tuple(index - start for index in triangle))
    return tuple(subset)


def triangle_topology_sha256(triangles: tuple[Triangle, ...]) -> str:
    flat = tuple(index for triangle in triangles for index in triangle)
    return sha256(struct.pack(f"<{len(flat)}q", *flat))


def _dot(left: Vector3, right: Vector3) -> float:
    return sum(a * b for a, b in zip(left, right))


def _subtract(left: Vector3, right: Vector3) -> Vector3:
    return tuple(a - b for a, b in zip(left, right))


def _point_on_segment_distance_squared(start: Vector3, end: Vector3) -> float:
    direction = _subtract(end, start)
    length_squared = _dot(direction, direction)
    if length_squared <= 1e-20:
        return _dot(start, start)
    amount = max(0.0, min(1.0, -_dot(start, direction) / length_squared))
    closest = tuple(start[axis] + amount * direction[axis] for axis in range(3))
    return _dot(closest, closest)


def _triangle_origin_distance_squared(
    first: Vector3, second: Vector3, third: Vector3
) -> float:
    """Exact origin-to-triangle distance, with a degenerate-edge fallback."""
    edge_a = _subtract(second, first)
    edge_b = _subtract(third, first)
    normal = (
        edge_a[1] * edge_b[2] - edge_a[2] * edge_b[1],
        edge_a[2] * edge_b[0] - edge_a[0] * edge_b[2],
        edge_a[0] * edge_b[1] - edge_a[1] * edge_b[0],
    )
    normal_squared = _dot(normal, normal)
    edge_distance = min(
        _point_on_segment_distance_squared(first, second),
        _point_on_segment_distance_squared(second, third),
        _point_on_segment_distance_squared(third, first),
    )
    if normal_squared <= 1e-20:
        return edge_distance

    # Project the origin onto the triangle plane, then use barycentric
    # coordinates to decide whether the projection lies on the face.
    scale = _dot(first, normal) / normal_squared
    projected = tuple(scale * value for value in normal)
    relative = _subtract(projected, first)
    aa = _dot(edge_a, edge_a)
    ab = _dot(edge_a, edge_b)
    bb = _dot(edge_b, edge_b)
    ar = _dot(edge_a, relative)
    br = _dot(edge_b, relative)
    denominator = aa * bb - ab * ab
    if abs(denominator) <= 1e-20:
        return edge_distance
    weight_a = (bb * ar - ab * br) / denominator
    weight_b = (aa * br - ab * ar) / denominator
    if weight_a >= -1e-9 and weight_b >= -1e-9 and weight_a + weight_b <= 1.0 + 1e-9:
        return min(edge_distance, _dot(projected, projected))
    return edge_distance


def origin_surface_proximity(
    points: tuple[Vector3, ...], triangles: tuple[Triangle, ...]
) -> tuple[float, float]:
    """Return absolute and RMS-normalized distance from node 0 to the mesh."""
    if not points or not triangles:
        raise AssertionError("surface proximity requires vertices and triangles")
    for triangle in triangles:
        if min(triangle) < 0 or max(triangle) >= len(points):
            raise AssertionError("triangle index is outside the vertex stream")
    distance = math.sqrt(
        min(
            _triangle_origin_distance_squared(
                points[triangle[0]], points[triangle[1]], points[triangle[2]]
            )
            for triangle in triangles
        )
    )
    centroid = tuple(
        sum(point[axis] for point in points) / len(points) for axis in range(3)
    )
    rms_radius = math.sqrt(
        sum(
            sum((point[axis] - centroid[axis]) ** 2 for axis in range(3))
            for point in points
        )
        / len(points)
    )
    if rms_radius <= 1e-12:
        raise AssertionError("surface proximity mesh has no extent")
    return distance, distance / rms_radius


def connected_vertex_components(
    vertex_count: int, triangles: tuple[Triangle, ...]
) -> tuple[tuple[int, ...], ...]:
    """Group mesh vertices by triangle-edge connectivity."""
    parents = list(range(vertex_count))
    sizes = [1] * vertex_count

    def find(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left: int, right: int) -> None:
        left = find(left)
        right = find(right)
        if left == right:
            return
        if sizes[left] < sizes[right]:
            left, right = right, left
        parents[right] = left
        sizes[left] += sizes[right]

    for triangle in triangles:
        if min(triangle) < 0 or max(triangle) >= vertex_count:
            raise AssertionError("triangle index is outside the vertex stream")
        union(triangle[0], triangle[1])
        union(triangle[1], triangle[2])
        union(triangle[2], triangle[0])
    members: dict[int, list[int]] = {}
    for index in range(vertex_count):
        members.setdefault(find(index), []).append(index)
    return tuple(tuple(component) for component in members.values())


def semantic_grip_cap_centroid(
    points: tuple[Vector3, ...],
    triangles: tuple[Triangle, ...],
    *,
    coordinate_tolerance: float = 1e-9,
    cap_depth: float,
) -> Vector3:
    """Find Crunch's 217-vertex pistol grip and centroid its upper cap.

    Compiled VT2 geometry duplicates vertices at UV seams and hard normals.
    Weld coincident positions only for component identity, while retaining the
    original coordinates for the centroid. The component's authored count is
    therefore stable in both the 4,916-point FBX and compiled vertex streams.
    """
    if coordinate_tolerance <= 0.0 or cap_depth <= 0.0:
        raise AssertionError("semantic grip tolerances must be positive")
    weld_keys = [
        tuple(round(value / coordinate_tolerance) for value in point)
        for point in points
    ]
    representative: dict[tuple[int, int, int], int] = {}
    welded_index: list[int] = []
    welded_points: list[Vector3] = []
    for point, key in zip(points, weld_keys):
        if key not in representative:
            representative[key] = len(welded_points)
            welded_points.append(point)
        welded_index.append(representative[key])
    welded_triangles = tuple(
        tuple(welded_index[index] for index in triangle) for triangle in triangles
    )
    matches = [
        component
        for component in connected_vertex_components(
            len(welded_points), welded_triangles
        )
        if len(component) == 217
    ]
    if len(matches) != 1:
        raise AssertionError(
            f"launcher expected one connected 217-vertex pistol grip, got {len(matches)}"
        )
    grip = matches[0]
    maximum_up = max(welded_points[index][1] for index in grip)
    cap = [
        welded_points[index]
        for index in grip
        if welded_points[index][1] >= maximum_up - cap_depth
    ]
    if not cap:
        raise AssertionError("launcher pistol grip has no upper-cap vertices")
    return tuple(sum(point[axis] for point in cap) / len(cap) for axis in range(3))


def source_points_to_engine(points: tuple[Vector3, ...]) -> tuple[Vector3, ...]:
    """Convert canonical FBX centimetres to VT2 unit-resource coordinates.

    ``canonical_geometry_points`` is ordered (right, up, front). Stingray's
    compiled vertex/world-matrix result is (right, -front, up), in metres.
    """
    return tuple((x / 100.0, -z / 100.0, y / 100.0) for x, y, z in points)


def engine_points_to_source(points: tuple[Vector3, ...]) -> tuple[Vector3, ...]:
    """Convert VT2 unit-resource coordinates to canonical FBX centimetres."""
    return tuple((x * 100.0, z * 100.0, -y * 100.0) for x, y, z in points)


def material_names(fbx: BinaryFbx) -> set[str]:
    return {
        clean_fbx_name(node.properties[1])
        for node in fbx.object_nodes("Material")
    }


def without_comments(source: str) -> str:
    return re.sub(r"//[^\r\n]*", "", source)


def descriptor_field(source: str, name: str) -> str:
    match = re.search(
        rf'\b{re.escape(name)}\s*=\s*(?:"([^"]+)"|([^\s\}}]+))',
        source,
    )
    if not match:
        raise AssertionError(f"texture descriptor has no {name!r} field")
    return match.group(1) or match.group(2)


def named_block(source: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*\{{", source)
    if not match:
        raise AssertionError(f"missing {name} block")
    start = match.end()
    depth = 1
    in_string = False
    escaped = False
    for offset, character in enumerate(source[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                return source[start:offset]
    raise AssertionError(f"unterminated {name} block")


def named_array(source: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}\s*=\s*\[", source)
    if not match:
        raise AssertionError(f"missing {name} array")
    start = match.end()
    depth = 1
    in_string = False
    escaped = False
    for offset, character in enumerate(source[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
            if depth == 0:
                return source[start:offset]
    raise AssertionError(f"unterminated {name} array")


def anonymous_blocks(source: str) -> list[str]:
    """Return top-level anonymous table entries from a named array body."""
    result: list[str] = []
    depth = 0
    start: int | None = None
    in_string = False
    escaped = False
    for offset, character in enumerate(source):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == "{":
            if depth == 0:
                start = offset + 1
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0 and start is not None:
                result.append(source[start:offset])
                start = None
            elif depth < 0:
                raise AssertionError("unbalanced anonymous table")
    if depth != 0:
        raise AssertionError("unterminated anonymous table")
    return result


@dataclass(frozen=True)
class CompiledSceneNode:
    parent_type: int
    parent_index: int
    name_hash: int
    world_transform: Matrix4


@dataclass(frozen=True)
class CompiledMeshGeometry:
    positions: tuple[Vector3, ...]
    triangles: tuple[Triangle, ...]


@dataclass(frozen=True)
class CompiledMeshObject:
    name_hash: int
    node_index: int
    geometry_index: int


@dataclass(frozen=True)
class CompiledUnitStructure:
    nodes: tuple[CompiledSceneNode, ...]
    mesh_node_indices: tuple[int, ...]
    actors: tuple[tuple[int, int], ...]  # (name hash, node hash)
    geometries: tuple[CompiledMeshGeometry, ...]
    meshes: tuple[CompiledMeshObject, ...]


class PackedCursor:
    """Small dependency-free cursor for the VT2 v189 unit prefix."""

    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0

    def skip(self, size: int) -> None:
        if size < 0 or self.offset + size > len(self.payload):
            raise AssertionError("compiled unit prefix overrun")
        self.offset += size

    def u8(self) -> int:
        value = struct.unpack_from("<B", self.payload, self.offset)[0]
        self.skip(1)
        return value

    def u16(self) -> int:
        value = struct.unpack_from("<H", self.payload, self.offset)[0]
        self.skip(2)
        return value

    def u32(self) -> int:
        value = struct.unpack_from("<I", self.payload, self.offset)[0]
        self.skip(4)
        return value

    def take(self, size: int) -> bytes:
        if size < 0 or self.offset + size > len(self.payload):
            raise AssertionError("compiled unit prefix overrun")
        result = self.payload[self.offset : self.offset + size]
        self.offset += size
        return result

    def byte_array(self) -> bytes:
        return self.take(self.u32())

    def u32_array(self) -> None:
        self.skip(self.u32() * 4)


def compiled_unit_structure(payload: bytes) -> CompiledUnitStructure:
    """Parse scene graph, renderables and actors from a VT2 v189 unit.

    This is the same packed prefix consumed by Bitsquid Blender Tools'
    UnitResourceVT2 parser, kept local so this regression runs under ordinary
    Python without importing Blender's ``bpy``/``mathutils`` modules.
    """
    cursor = PackedCursor(payload)
    version = cursor.u32()
    if version != 189:
        raise AssertionError(f"compiled unit version must be 189, got {version}")

    geometries: list[CompiledMeshGeometry] = []
    for _ in range(cursor.u32()):  # MeshGeometryVT2[]
        streams: list[tuple[bytes, int, int, int, int]] = []
        for _ in range(cursor.u32()):  # streams
            data = cursor.byte_array()
            streams.append(
                (data, cursor.u32(), cursor.u32(), cursor.u32(), cursor.u32())
            )  # data, validity, stream type, vertex count, stride
        channels = tuple(
            (cursor.u32(), cursor.u32(), cursor.u32(), cursor.u32(), cursor.u8())
            for _ in range(cursor.u32())
        )  # component, type, set, stream, is_instance
        positions = [channel for channel in channels if channel[0] == 0]
        if len(positions) != 1:
            raise AssertionError(
                f"compiled geometry expected one position channel, got {len(positions)}"
            )
        component, channel_type, _set, stream_index, is_instance = positions[0]
        if component != 0 or channel_type != 17 or is_instance != 0:
            raise AssertionError("compiled positions must be non-instanced Half4")
        if stream_index >= len(streams):
            raise AssertionError("compiled position channel refers to a missing stream")
        position_data, validity, stream_type, vertex_count, stride = streams[stream_index]
        if validity != 0 or stream_type != 0 or stride != 8:
            raise AssertionError("compiled position stream must be static Half4 array data")
        if len(position_data) != vertex_count * stride:
            raise AssertionError("compiled position stream byte count does not match metadata")
        position_points = tuple(
            tuple(float(value) for value in values[:3])
            for values in struct.iter_unpack("<eeee", position_data)
        )
        if any(not math.isfinite(value) for point in position_points for value in point):
            raise AssertionError("compiled position stream contains non-finite coordinates")

        index_validity = cursor.u32()
        index_stream_type = cursor.u32()
        index_format = cursor.u32()
        index_count = cursor.u32()
        index_data = cursor.byte_array()
        if index_validity != 0 or index_stream_type != 0 or index_format not in (0, 1):
            raise AssertionError("compiled index stream has unsupported metadata")
        index_size = 2 if index_format == 0 else 4
        if len(index_data) != index_count * index_size or index_count % 3:
            raise AssertionError("compiled index stream is not a complete triangle list")
        index_code = "H" if index_format == 0 else "I"
        indices = struct.unpack(f"<{index_count}{index_code}", index_data)
        triangles = tuple(
            tuple(indices[offset : offset + 3])
            for offset in range(0, index_count, 3)
        )
        if triangles and max(max(triangle) for triangle in triangles) >= len(position_points):
            raise AssertionError("compiled index stream exceeds its position stream")
        geometries.append(CompiledMeshGeometry(position_points, triangles))
        cursor.skip(cursor.u32() * 16)  # batch ranges
        cursor.skip(28)  # bounding volume
        cursor.skip(cursor.u32() * 4)  # material IDString32s

    for _ in range(cursor.u32()):  # SkinData[]
        cursor.skip(cursor.u32() * 64)  # inverse bind matrices
        cursor.u32_array()  # node indices
        for _ in range(cursor.u32()):
            cursor.u32_array()  # matrix index set

    cursor.byte_array()  # simple animation
    for _ in range(cursor.u32()):  # simple animation groups
        cursor.skip(4)  # name IDString32
        cursor.u32_array()

    node_count = cursor.u32()
    cursor.skip(node_count * 60)  # local rotation, position, scale
    world_transforms = []
    for _ in range(node_count):
        values = struct.unpack("<16f", cursor.take(64))
        # Stingray serializes matrices column-major; the helpers above consume
        # row-major tuples.
        world_transforms.append(
            tuple(
                tuple(values[column * 4 + row] for column in range(4))
                for row in range(4)
            )
        )
    parent_data = [(cursor.u16(), cursor.u16()) for _ in range(node_count)]
    nodes = tuple(
        CompiledSceneNode(parent_type, parent_index, cursor.u32(), world_transform)
        for (parent_type, parent_index), world_transform in zip(
            parent_data, world_transforms
        )
    )

    mesh_node_indices: list[int] = []
    meshes: list[CompiledMeshObject] = []
    for _ in range(cursor.u32()):  # MeshObject[]
        name_hash = cursor.u32()
        node_index = cursor.u32()
        geometry_index = cursor.u32()
        cursor.skip(8)  # skin index, flags
        mesh_node_indices.append(node_index)
        meshes.append(CompiledMeshObject(name_hash, node_index, geometry_index))
        cursor.skip(28)  # bounding volume

    actors: list[tuple[int, int]] = []
    shape_extra_sizes = {0: 4, 1: 12, 2: 8, 3: 0, 4: 0, 5: 21, 6: 12}
    for _ in range(cursor.u32()):  # ActorResource[]
        actor_name = cursor.u32()
        cursor.skip(4)  # actor template
        actor_node = cursor.u32()
        cursor.skip(4)  # mass
        for _ in range(cursor.u32()):
            shape_type = cursor.u32()
            if shape_type not in shape_extra_sizes:
                raise AssertionError(f"unknown compiled actor shape {shape_type}")
            cursor.skip(8 + 64)  # material, template, local matrix
            cursor.byte_array()
            cursor.skip(4 + shape_extra_sizes[shape_type])  # shape node + data
        cursor.skip(24)  # touch/trigger events
        if cursor.u8() not in (0, 1):
            raise AssertionError("compiled actor enabled flag is not boolean")
        actors.append((actor_name, actor_node))

    return CompiledUnitStructure(
        nodes,
        tuple(mesh_node_indices),
        tuple(actors),
        tuple(geometries),
        tuple(meshes),
    )


def idstring32(value: str) -> int:
    return murmur64a(value.encode()) >> 32


def compiled_node_index(structure: CompiledUnitStructure, name: str) -> int:
    expected = idstring32(name)
    matches = [index for index, node in enumerate(structure.nodes) if node.name_hash == expected]
    if len(matches) != 1:
        raise AssertionError(f"compiled unit expected one scene node {name!r}, got {matches}")
    return matches[0]


def compiled_renderable_geometry(
    structure: CompiledUnitStructure, name: str
) -> tuple[tuple[Vector3, ...], tuple[Triangle, ...]]:
    """Return one compiled renderable's vertices in unit-root coordinates."""
    expected = idstring32(name)
    matches = [mesh for mesh in structure.meshes if mesh.name_hash == expected]
    if len(matches) != 1:
        raise AssertionError(f"compiled unit expected one mesh {name!r}, got {len(matches)}")
    mesh = matches[0]
    if not 0 <= mesh.node_index < len(structure.nodes):
        raise AssertionError(f"compiled mesh {name!r} refers to a missing scene node")
    # MeshGeometry indices in UnitResource v189 are one-based; zero is the
    # sentinel for a MeshObject without geometry.
    if not 1 <= mesh.geometry_index <= len(structure.geometries):
        raise AssertionError(f"compiled mesh {name!r} refers to missing geometry")
    geometry = structure.geometries[mesh.geometry_index - 1]
    world = structure.nodes[mesh.node_index].world_transform
    return (
        tuple(transform_point(world, point) for point in geometry.positions),
        geometry.triangles,
    )


def node_inherits(nodes: tuple[CompiledSceneNode, ...], node: int, ancestor: int) -> bool:
    visited: set[int] = set()
    while node not in visited and 0 <= node < len(nodes):
        if node == ancestor:
            return True
        visited.add(node)
        parent = nodes[node]
        if parent.parent_type != 1:  # ParentType.INTERNAL
            return False
        node = parent.parent_index
    return False


def compiled_bundle_resources() -> dict[tuple[int, int], list[tuple[Path, bytes]]]:
    """Index every compiled resource without extracting or mutating bundles."""
    resources: dict[tuple[int, int], list[tuple[Path, bytes]]] = {}
    for bundle in sorted(BUNDLE_ROOT.glob("*.mod_bundle")):
        bundle_format, _, data = read_bundle(bundle)
        _, _, records = walk_bundle(data, bundle_format)
        for record in records:
            for version in record["versions"]:
                start = version["payload_offset"]
                end = start + version["size"]
                resources.setdefault((record["type"], record["name"]), []).append(
                    (bundle, data[start:end])
                )
    return resources


def resource_key(resource_type: str, resource_name: str) -> tuple[int, int]:
    return murmur64a(resource_type.encode()), murmur64a(resource_name.encode())


def compiled_material_pairs(payload: bytes) -> set[tuple[int, int]]:
    """Read the unit's terminal slot->material map using the VT2 v189 layout.

    The complete UnitResource parser established that the final fields are
    default_material_resource:u64, count:u32, then count*(slot:u32,
    material:u64), followed by apex byte array, vehicle count, and skeleton.
    Search from the end for the unique tail that consumes the whole payload;
    this keeps the regression dependency-free while still parsing structure,
    rather than accepting arbitrary hash occurrences in geometry data.
    """
    candidates: list[set[tuple[int, int]]] = []
    for offset in range(max(0, len(payload) - 512), len(payload) - 24):
        count = struct.unpack_from("<I", payload, offset + 8)[0]
        if count > 32:
            continue
        cursor = offset + 12 + count * 12
        if cursor + 16 > len(payload):
            continue
        apex_size = struct.unpack_from("<I", payload, cursor)[0]
        cursor += 4 + apex_size
        if cursor + 12 != len(payload):
            continue
        vehicle_count = struct.unpack_from("<I", payload, cursor)[0]
        if vehicle_count != 0:
            continue
        pairs = {
            struct.unpack_from("<IQ", payload, offset + 12 + index * 12)
            for index in range(count)
        }
        if any(slot == 0 or material == 0 for slot, material in pairs):
            continue
        candidates.append(pairs)
    if len(candidates) != 1:
        raise AssertionError(
            f"compiled unit expected one terminal material table, got {len(candidates)}"
        )
    return candidates[0]


class CrunchWeaponProvenanceTests(unittest.TestCase):
    def test_authoritative_local_sources_have_reviewed_hashes(self) -> None:
        sources = {
            "blend": Path.home() / "Downloads" / "xud4soo5fg7g8qd4.blend",
            "texture_zip": Path.home() / "Downloads" / "zxnu2hjyuovl4rhx.zip",
            "launcher_fbx": ART_ROOT / "warlock_rocketlauncher.fbx",
            "rocket_fbx": ART_ROOT / "warlock_rocket.fbx",
            "tube_fbx": ART_ROOT / "warlock_tube.fbx",
        }
        for name, path in sources.items():
            with self.subTest(source=name):
                if not path.is_file():
                    continue
                self.assertEqual(file_sha256(path), SOURCE_SHA256[name])

    def test_isolated_exports_have_expected_mesh_and_material_identity(self) -> None:
        expected = {
            "launcher_fbx": (ART_ROOT / "warlock_rocketlauncher.fbx", 4916, 9118, "DoomRocket_Weapon"),
            "rocket_fbx": (ART_ROOT / "warlock_rocket.fbx", 622, 1240, "DoomRocket_Rocket"),
        }
        for name, (path, vertex_count, face_count, material) in expected.items():
            with self.subTest(source=name):
                if not path.is_file():
                    continue
                fbx = BinaryFbx(path)
                meshes = geometry_manifest(fbx)
                self.assertEqual(len(meshes), 1)
                signature = next(iter(meshes.values()))
                self.assertEqual(signature[:2], (vertex_count, face_count))
                self.assertEqual(signature, CRUNCH_EXPORT_GEOMETRY["launcher" if name == "launcher_fbx" else "rocket"])
                self.assertEqual(material_names(fbx), {material})

    def test_unrigged_short_conduit_is_distinct_and_deferred(self) -> None:
        """Do not confuse the weapon-local conduit with the backpack tether."""
        path = ART_ROOT / "warlock_tube.fbx"
        if not path.is_file():
            self.skipTest("Crunch isolated tube export is not present")
        tube = BinaryFbx(path)
        self.assertEqual(
            set(geometry_manifest(tube).values()),
            {(198, 384, "a4ff8a9513a796f6735c5167a65f9ae345883581bfdaf7a287db21b4eef0359f")},
        )
        self.assertEqual(material_names(tube), {"DoomRocket_Pipe"})
        self.assertNotIn("SM_Skaven_WarlockBombardier_Tube", model_names(BinaryFbx(ROCKET_UNIT_DIR / "pRocketLauncher.fbx")))

    def test_full_launcher_has_exact_closed_mvp_and_backpack_tether_split(self) -> None:
        """Pin the source cut that removes only the deferred two-metre tether."""
        path = ART_ROOT / "warlock_rocketlauncher.fbx"
        if not path.is_file():
            self.skipTest("Crunch isolated launcher export is not present")
        source = BinaryFbx(path)
        geometry = geometry_by_vertex_count(source, FULL_LAUNCHER_VERTEX_COUNT)
        triangles = triangulated_fbx_faces(geometry)
        mvp = local_triangle_subset(triangles, 0, MVP_LAUNCHER_VERTEX_COUNT)
        tether = local_triangle_subset(
            triangles, MVP_LAUNCHER_VERTEX_COUNT, FULL_LAUNCHER_VERTEX_COUNT
        )
        self.assertEqual(len(mvp), MVP_LAUNCHER_TRIANGLE_COUNT)
        self.assertEqual(len(tether), DEFERRED_HOSE_TRIANGLE_COUNT)
        self.assertEqual(
            triangle_topology_sha256(mvp),
            CRUNCH_LAUNCHER_SPLIT_TOPOLOGY["mvp"],
        )
        self.assertEqual(
            triangle_topology_sha256(tether),
            CRUNCH_LAUNCHER_SPLIT_TOPOLOGY["backpack_tether"],
        )
        self.assertEqual(
            tuple(
                sorted(
                    map(
                        len,
                        connected_vertex_components(
                            DEFERRED_HOSE_VERTEX_COUNT, tether
                        ),
                    ),
                    reverse=True,
                )
            ),
            DEFERRED_HOSE_COMPONENT_SIZES,
        )

    def test_exporter_pins_crunch_source_and_immutable_legacy_blobs(self) -> None:
        source = (REPO_ROOT / "tools" / "prepare_warlock_weapon_fbx.py").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            f'SOURCE_SHA256 = "{SOURCE_SHA256["blend"].upper()}"',
            source,
        )
        expected = {
            "4afd3ff155889b44760ff41500bca7e1bf6ccafa": OLD_DALO_FBX_SHA256[
                "pRocketLauncher.fbx"
            ],
            "445636e36fc62a8aef8883d2f59ed85eaa6707a0": OLD_DALO_FBX_SHA256[
                "SM_Rocket.fbx"
            ],
        }
        for blob, expected_sha in expected.items():
            with self.subTest(blob=blob):
                self.assertIn(f'"blob": "{blob}"', source)
                self.assertIn(f'"sha256": "{expected_sha.upper()}"', source)
                payload = subprocess.run(
                    ["git", "-C", str(REPO_ROOT), "cat-file", "blob", blob],
                    check=True,
                    capture_output=True,
                ).stdout
                self.assertEqual(sha256(payload), expected_sha)
        self.assertIn("legacy launcher input must not be overwritten", source)
        self.assertIn("legacy projectile input must not be overwritten", source)
        self.assertIn("loaded_rocket.parent = launcher", source)
        self.assertIn("MVP_LAUNCHER_VERTEX_COUNT = 3308", source)
        self.assertIn("DEFERRED_HOSE_VERTEX_COUNT = 1608", source)
        self.assertIn('SOURCE_TUBE = "SM_Skaven_WarlockBombardier_Tube"', source)
        self.assertIn("require_deferred_tube_contract(source_tube)", source)
        for contract in (
            "source.parent is not None",
            "source.modifiers",
            "source.vertex_groups",
            "source.constraints",
            "source.animation_data is not None",
            "source.data.shape_keys is not None",
            "source.rigid_body is not None",
            "source.rigid_body_constraint is not None",
        ):
            with self.subTest(deferred_tube_contract=contract):
                self.assertIn(contract, source)


class CrunchWeaponFbxTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.launcher = BinaryFbx(ROCKET_UNIT_DIR / "pRocketLauncher.fbx")
        cls.projectile = BinaryFbx(ROCKET_UNIT_DIR / "SM_Rocket.fbx")
        legacy_blob = OLD_DALO_FBX_BLOBS["pRocketLauncher.fbx"]
        legacy_payload = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "cat-file", "blob", legacy_blob],
            check=True,
            capture_output=True,
        ).stdout
        if sha256(legacy_payload) != OLD_DALO_FBX_SHA256["pRocketLauncher.fbx"]:
            raise AssertionError("known-good launcher Git blob failed its SHA-256 pin")
        cls.legacy_launcher = BinaryFbx.from_bytes(
            legacy_payload, f"git-blob-{legacy_blob}.fbx"
        )

    def test_launcher_contains_crunch_launcher_and_loaded_rocket_meshes(self) -> None:
        signatures = set(geometry_manifest(self.launcher).values())
        self.assertEqual(signatures, set(SHIPPING_GEOMETRY.values()))

    def test_standalone_projectile_is_crunch_rocket_mesh(self) -> None:
        signatures = list(geometry_manifest(self.projectile).values())
        self.assertEqual(len(signatures), 1)
        self.assertEqual(signatures[0], SHIPPING_GEOMETRY["rocket"])

    @unittest.skipUnless(ART_ROOT.is_dir(), "Crunch isolated mesh exports are not present")
    def test_shipping_shapes_match_crunch_exports_after_rigid_placement(self) -> None:
        sources = {
            "launcher": BinaryFbx(ART_ROOT / "warlock_rocketlauncher.fbx"),
            "rocket": BinaryFbx(ART_ROOT / "warlock_rocket.fbx"),
        }
        shipping = {
            "launcher": (self.launcher, MVP_LAUNCHER_VERTEX_COUNT),
            "rocket_loaded": (self.launcher, 622),
            "rocket_projectile": (self.projectile, 622),
        }
        for name, (fbx, count) in shipping.items():
            source_name = "launcher" if name == "launcher" else "rocket"
            if source_name == "launcher":
                full_source = geometry_by_vertex_count(
                    sources[source_name], FULL_LAUNCHER_VERTEX_COUNT
                )
                expected = shape_profile_points(
                    raw_geometry_points(full_source)[:MVP_LAUNCHER_VERTEX_COUNT]
                )
            else:
                expected = shape_profile(
                    geometry_by_vertex_count(sources[source_name], count)
                )
            actual = shape_profile(geometry_by_vertex_count(fbx, count))
            self.assertEqual(len(actual), len(expected))
            self.assertLess(
                max(abs(left - right) for left, right in zip(actual, expected)),
                2e-6,
                f"{name}: vertex shape differs from Crunch's authoritative mesh",
            )

    def test_crunch_uv_coordinate_banks_are_preserved_exactly(self) -> None:
        launcher_geometry = geometry_by_vertex_count(
            self.launcher, MVP_LAUNCHER_VERTEX_COUNT
        )
        launcher_uv = uv_signature(launcher_geometry)
        loaded_uv = uv_signature(geometry_by_vertex_count(self.launcher, 622))
        projectile_uv = uv_signature(geometry_by_vertex_count(self.projectile, 622))
        self.assertEqual(launcher_uv, MVP_LAUNCHER_UV)
        self.assertEqual(loaded_uv, (1744, CRUNCH_UV_SHA256["rocket"]))
        self.assertEqual(projectile_uv, loaded_uv)

        source_path = ART_ROOT / "warlock_rocketlauncher.fbx"
        if source_path.is_file():
            source_geometry = geometry_by_vertex_count(
                BinaryFbx(source_path), FULL_LAUNCHER_VERTEX_COUNT
            )
            self.assertEqual(
                uv_sets_by_vertex(
                    source_geometry, MVP_LAUNCHER_VERTEX_COUNT
                ),
                uv_sets_by_vertex(launcher_geometry),
                "MVP launcher UV mapping is not the retained subset of Crunch art",
            )

    def test_launcher_preserves_all_runtime_attachment_nodes(self) -> None:
        required = {"root_point", "handle", "p_fx", "a_barrel"}
        self.assertEqual(required - model_names(self.launcher), set())

    def test_raw_fbx_model_names_exactly_match_runtime_string_contracts(self) -> None:
        launcher_models = [
            (clean_fbx_name(node.properties[1]), node.properties[2])
            for node in self.launcher.object_nodes("Model")
        ]
        self.assertEqual(
            {name for name, kind in launcher_models if kind == "Mesh"},
            {"pRocketLauncher", "pRocket"},
        )
        self.assertIn(("root_point", "Null"), launcher_models)
        for bone in ("root_point", "handle", "p_fx", "a_barrel"):
            self.assertIn((bone, "LimbNode"), launcher_models)
        projectile_models = [
            (clean_fbx_name(node.properties[1]), node.properties[2])
            for node in self.projectile.object_nodes("Model")
        ]
        self.assertEqual(projectile_models, [("pRocket", "Mesh")])
        for name, _kind in launcher_models + projectile_models:
            self.assertNotRegex(name, r"\.\d{3}$")

    def test_runtime_renderable_and_actor_node_names_are_exact(self) -> None:
        launcher_names = model_names(self.launcher)
        projectile_names = model_names(self.projectile)
        self.assertEqual({"pRocketLauncher", "pRocket"} - launcher_names, set())
        self.assertIn("pRocket", projectile_names)
        model_node(self.launcher, "root_point", "Null")
        model_node(self.launcher, "pRocketLauncher", "Mesh")
        model_node(self.launcher, "pRocket", "Mesh")
        model_node(self.projectile, "pRocket", "Mesh")
        # A Blender collision suffix changes the Stingray node name and leaves
        # the .unit renderable/.physics actor pointing at nothing.
        for name in launcher_names | projectile_names:
            self.assertNotRegex(name, r"^(?:pRocketLauncher|pRocket|root_point)\.\d+$")

    def test_attachment_node_rest_transforms_are_preserved(self) -> None:
        expected = {
            "root_point": (0.0, 0.0, 0.0),
            "handle": (0.0, -0.42, 0.05),
            "p_fx": (0.0, 0.85, 0.06),
            "a_barrel": (0.17, 0.40, 0.06),
        }
        for name, translation in expected.items():
            with self.subTest(node=name):
                actual = local_translation(model_node(self.launcher, name, "LimbNode"))
                for actual_axis, expected_axis in zip(actual, translation):
                    self.assertAlmostEqual(actual_axis, expected_axis, places=5)

    def test_weapon_root_frame_matches_known_good_after_axis_normalization(self) -> None:
        """Maya Y-up and Blender Z-up metadata may differ, not the runtime frame."""
        expected_root = model_node(self.legacy_launcher, "root_point", "Null")
        actual_root = model_node(self.launcher, "root_point", "Null")
        expected = normalized_axes(
            matrix_multiply(
                global_axis_matrix(self.legacy_launcher),
                model_world_matrix(self.legacy_launcher, expected_root),
            )
        )
        actual = normalized_axes(
            matrix_multiply(
                global_axis_matrix(self.launcher),
                model_world_matrix(self.launcher, actual_root),
            )
        )
        for axis, (expected_vector, actual_vector) in enumerate(zip(expected, actual)):
            with self.subTest(axis=axis):
                self.assertLess(
                    max(
                        abs(expected_value - actual_value)
                        for expected_value, actual_value in zip(
                            expected_vector, actual_vector
                        )
                    ),
                    2e-5,
                )

    def test_launcher_attachment_origin_remains_inside_effective_mesh_envelope(self) -> None:
        """Catch a rigid mesh baked away from node 0 even when its nodes survive."""
        expected = canonical_geometry_points(self.legacy_launcher, 1586)
        actual = canonical_geometry_points(
            self.launcher, MVP_LAUNCHER_VERTEX_COUNT
        )
        expected_gap = normalized_origin_envelope_gap(expected)
        actual_gap = normalized_origin_envelope_gap(actual)
        self.assertLess(expected_gap, 1e-6, "known-good attachment origin left its mesh")
        self.assertLessEqual(
            actual_gap,
            expected_gap + 0.05,
            "launcher is baked away from the attachment origin: "
            f"normalized envelope gap={actual_gap:.6f}, allowed={expected_gap + 0.05:.6f}",
        )

    def test_launcher_grip_surface_stays_near_known_good_attachment_origin(self) -> None:
        """An AABB containing node 0 is insufficient when the mesh surrounds empty space."""
        expected_geometry = geometry_by_vertex_count(self.legacy_launcher, 1586)
        actual_geometry = geometry_by_vertex_count(
            self.launcher, MVP_LAUNCHER_VERTEX_COUNT
        )
        expected = origin_surface_proximity(
            canonical_geometry_points(self.legacy_launcher, 1586),
            triangulated_fbx_faces(expected_geometry),
        )
        actual = origin_surface_proximity(
            canonical_geometry_points(self.launcher, MVP_LAUNCHER_VERTEX_COUNT),
            triangulated_fbx_faces(actual_geometry),
        )
        self.assertLessEqual(
            expected[0],
            1.5,
            f"known-good launcher surface moved {expected[0]:.3f} cm from node 0",
        )
        self.assertLessEqual(
            actual[0],
            5.0,
            "launcher grip surface is too far from its attachment origin: "
            f"distance={actual[0]:.3f} cm, normalized={actual[1]:.6f}",
        )
        self.assertLessEqual(
            actual[1],
            0.08,
            "launcher grip surface proximity exceeds the normalized root-space limit: "
            f"distance={actual[0]:.3f} cm, normalized={actual[1]:.6f}",
        )

    def test_launcher_semantic_pistol_grip_is_calibrated_to_attachment_origin(self) -> None:
        """Prevent a stock or decorative surface from satisfying the proximity gate."""
        geometry = geometry_by_vertex_count(
            self.launcher, MVP_LAUNCHER_VERTEX_COUNT
        )
        centroid = semantic_grip_cap_centroid(
            canonical_geometry_points(self.launcher, MVP_LAUNCHER_VERTEX_COUNT),
            triangulated_fbx_faces(geometry),
            coordinate_tolerance=1e-6,
            cap_depth=1.0,
        )
        expected = (0.000002565, 1.108044386, 0.0)
        for axis, (actual, target) in enumerate(zip(centroid, expected)):
            with self.subTest(axis=axis):
                self.assertAlmostEqual(
                    actual,
                    target,
                    delta=0.1,
                    msg=(
                        "semantic pistol-grip cap is not calibrated to the "
                        f"known-good attachment landmark: actual={centroid} cm, "
                        f"expected={expected} cm"
                    ),
                )
    def test_launcher_effective_long_axis_matches_known_good_attachment_axis(self) -> None:
        """Catch a 90-degree DCC-axis bake without requiring identical geometry."""
        expected = principal_axis(
            canonical_geometry_points(self.legacy_launcher, 1586)
        )
        actual = principal_axis(
            canonical_geometry_points(self.launcher, MVP_LAUNCHER_VERTEX_COUNT)
        )
        alignment = abs(sum(left * right for left, right in zip(expected, actual)))
        self.assertGreaterEqual(
            alignment,
            0.85,
            "launcher principal axis diverged from known-good attachment frame: "
            f"abs(dot)={alignment:.6f}, required>=0.850000",
        )

    def test_loaded_warhead_points_toward_the_legacy_muzzle_direction(self) -> None:
        """Use a signed landmark so a 180-degree mesh flip cannot pass abs(axis)."""
        root = canonical_model_origin(
            self.launcher, model_node(self.launcher, "root_point", "Null")
        )
        muzzle = canonical_model_origin(
            self.launcher, model_node(self.launcher, "p_fx", "LimbNode")
        )
        rocket_centroid = point_centroid(
            canonical_geometry_points(self.launcher, 622)
        )
        muzzle_direction = _subtract(muzzle, root)
        rocket_direction = _subtract(rocket_centroid, root)
        expected_muzzle = (0.0, 5.999980, -85.000015)
        for axis, (actual, expected) in enumerate(
            zip(muzzle_direction, expected_muzzle)
        ):
            with self.subTest(metric="p_fx", axis=axis):
                self.assertAlmostEqual(actual, expected, delta=0.001)
        alignment = directed_cosine(muzzle_direction, rocket_direction)
        self.assertGreaterEqual(
            alignment,
            0.9,
            "loaded pRocket points away from the legacy p_fx muzzle direction: "
            f"signed cosine={alignment:.6f}, required>=0.900000",
        )

    def test_loaded_warhead_is_rigid_child_of_actor_owned_launcher(self) -> None:
        require_loaded_rocket_actor_hierarchy(self.launcher)

    def test_hierarchy_guard_rejects_historical_sibling_warhead(self) -> None:
        launcher = model_node(self.launcher, "pRocketLauncher", "Mesh")
        loaded_rocket = model_node(self.launcher, "pRocket", "Mesh")
        root = model_node(self.launcher, "root_point", "Null")
        parents = model_parent_ids(self.launcher)
        self.assertEqual(parents[loaded_rocket.properties[0]], launcher.properties[0])

        # Recreate the v0.1.53 failure in memory: both meshes are siblings under
        # root_point, while rp_dropped drives only pRocketLauncher.
        historical_sibling = dict(parents)
        historical_sibling[loaded_rocket.properties[0]] = root.properties[0]
        with self.assertRaisesRegex(AssertionError, "direct child of actor-owned"):
            require_loaded_rocket_actor_hierarchy(self.launcher, historical_sibling)

    def test_launcher_and_attachment_nodes_keep_one_weapon_root(self) -> None:
        root = model_node(self.launcher, "root_point", "Null")
        parents = model_parent_ids(self.launcher)
        for name, kind in (
            ("pRocketLauncher", "Mesh"),
            ("root_point", "LimbNode"),
            ("handle", "LimbNode"),
            ("p_fx", "LimbNode"),
            ("a_barrel", "LimbNode"),
        ):
            with self.subTest(node=name, kind=kind):
                node = model_node(self.launcher, name, kind)
                self.assertEqual(parents.get(node.properties[0]), root.properties[0])

    def test_fbx_material_identities_are_final_not_lambert(self) -> None:
        self.assertEqual(
            material_names(self.launcher),
            {"DoomRocket_Weapon", "DoomRocket_Rocket"},
        )
        self.assertEqual(material_names(self.projectile), {"DoomRocket_Rocket"})
        for fbx in (self.launcher, self.projectile):
            for material in material_names(fbx):
                self.assertNotRegex(material, r"(?i)^lambert\d*$")

    def test_whole_files_are_not_the_old_dalo_placeholders(self) -> None:
        for filename, rejected in OLD_DALO_FBX_SHA256.items():
            with self.subTest(fbx=filename):
                self.assertNotEqual(file_sha256(ROCKET_UNIT_DIR / filename), rejected)


class CrunchWeaponTextureTests(unittest.TestCase):
    # These names form the runtime contract; descriptors and materials must not
    # silently fall back to body set-01/02 or the old solid-color placeholders.
    TARGETS = {
        "weapon": ("03", (1024, 1024)),
        "rocket": ("04", (512, 512)),
    }

    def test_committed_adapters_match_authored_set_03_and_04_pixels(self) -> None:
        for target, (index, size) in self.TARGETS.items():
            source_dir = CRUNCH_TEXTURES / str(size[0])
            prefix = "T_Skaven_WarlockBombardier_"
            paths = {
                "df": source_dir / f"{prefix}BC_{index}.png",
                "nm": source_dir / f"{prefix}NR_{index}.png",
                "mase": source_dir / f"{prefix}MASE_{index}.png",
                "fix": source_dir / f"{prefix}MASE_{index}_Fix.png",
            }
            output = {
                suffix: ROCKET_TEXTURE_DIR / f"wb_{target}_{suffix}.png"
                for suffix in ("df", "nm", "e", "r", "m", "ao")
            }
            for path in output.values():
                self.assertTrue(path.is_file(), f"missing runtime texture {path}")
            for path in output.values():
                self.assertEqual(rgba(path).size, size)
                self.assertEqual(
                    sha256(rgba(path).tobytes()),
                    EXPECTED_RGBA[path.stem],
                    f"{path.name}: decoded pixels differ from the reviewed Crunch master",
                )
            if all(path.is_file() for path in paths.values()):
                self.assertEqual(rgba(output["df"]).tobytes(), rgba(paths["df"]).tobytes())
                self.assertEqual(rgba(output["nm"]).tobytes(), rgba(paths["nm"]).tobytes())
            self.assertFalse(
                (ROCKET_TEXTURE_DIR / f"wb_{target}_ma.png").exists(),
                "packed prop map is not consumed by the standard material",
            )

    def test_texture_descriptors_preserve_color_space_and_alpha_channels(self) -> None:
        expected_srgb = {
            "df": "true",
            "nm": "false",
            "e": "true",
            "r": "false",
            "m": "false",
            "ao": "false",
        }
        for target in self.TARGETS:
            for suffix, srgb in expected_srgb.items():
                with self.subTest(texture=f"{target}_{suffix}"):
                    path = ROCKET_TEXTURE_DIR / f"wb_{target}_{suffix}.texture"
                    source = path.read_text(encoding="utf-8")
                    filenames = re.findall(r'\bfilename\s*=\s*"([^"]+)"', source)
                    self.assertEqual(filenames, [f"textures/rocket/wb_{target}_{suffix}"])
                    self.assertEqual(descriptor_field(source, "format"), "BC7")
                    self.assertEqual(descriptor_field(source, "srgb"), srgb)
                    self.assertEqual(descriptor_field(source, "apply_processing"), "true")
                    self.assertEqual(
                        descriptor_field(source, "enable_cut_alpha_threshold"),
                        "false",
                    )
                    self.assertEqual(descriptor_field(source, "streamable"), "true")

    @unittest.skipUnless(
        CRUNCH_TEXTURES.is_dir(),
        "Crunch authored texture masters are not present",
    )
    def test_split_scalar_maps_are_exact_authored_channels(self) -> None:
        channels = {"r": ("nm", "A"), "m": ("fix", "R"), "ao": ("fix", "G")}
        for target, (index, size) in self.TARGETS.items():
            source_dir = CRUNCH_TEXTURES / str(size[0])
            prefix = "T_Skaven_WarlockBombardier_"
            sources = {
                "nm": rgba(source_dir / f"{prefix}NR_{index}.png"),
                "fix": rgba(source_dir / f"{prefix}MASE_{index}_Fix.png"),
            }
            for suffix, (source_name, channel) in channels.items():
                with self.subTest(texture=f"{target}_{suffix}"):
                    expected = sources[source_name].getchannel(channel)
                    actual = rgba(ROCKET_TEXTURE_DIR / f"wb_{target}_{suffix}.png")
                    for output_channel in "RGB":
                        self.assertEqual(actual.getchannel(output_channel).tobytes(), expected.tobytes())
            emissive = rgba(source_dir / f"{prefix}E_{index}.png").convert("RGB")
            self.assertEqual(
                rgba(ROCKET_TEXTURE_DIR / f"wb_{target}_e.png").convert("RGB").tobytes(),
                emissive.tobytes(),
            )


class CrunchWeaponUnitContractTests(unittest.TestCase):
    EXPECTED = {
        "pRocketLauncher.unit": {
            "slots": {"DoomRocket_Weapon", "DoomRocket_Rocket"},
            "renderables": {"pRocketLauncher", "pRocket"},
        },
        "SM_Rocket.unit": {
            "slots": {"DoomRocket_Rocket"},
            "renderables": {"pRocket"},
        },
    }

    def test_unit_material_slots_cover_every_final_fbx_slot(self) -> None:
        for filename, expected in self.EXPECTED.items():
            with self.subTest(unit=filename):
                source = without_comments((ROCKET_UNIT_DIR / filename).read_text(encoding="utf-8"))
                materials = dict(re.findall(r'(\w+)\s*=\s*"([^"]+)"', named_block(source, "materials")))
                slots = set(re.findall(r'\bslot\d+\s*=\s*"([^"]+)"', named_block(source, "mat_slots")))
                renderables = set(re.findall(r"(?m)^\s*(\w+)\s*=\s*\{", named_block(source, "renderables")))
                self.assertEqual(slots, expected["slots"])
                self.assertEqual(slots - materials.keys(), set())
                self.assertEqual(renderables, expected["renderables"])
                for slot, material in materials.items():
                    self.assertNotRegex(slot, r"(?i)^lambert\d*$")
                    self.assertRegex(material, r"^materials/rocket/")
                    self.assertTrue((REPO_ROOT / f"{material}.material").is_file())

    def test_rigid_materials_bind_every_authored_sampler(self) -> None:
        materials = {
            "materials/rocket/rocket_neutral.material": "weapon",
            "materials/rocket/rocket_red.material": "rocket",
        }
        for relative, target in materials.items():
            with self.subTest(material=relative):
                source = without_comments((REPO_ROOT / relative).read_text(encoding="utf-8"))
                self.assertRegex(
                    source,
                    r'(?m)^\s*parent_material\s*=\s*"core/stingray_renderer/shader_import/standard"',
                )
                block = named_block(source, "textures")
                bindings = dict(re.findall(r'(\w+)\s*=\s*"([^"]+)"', block))
                self.assertEqual(
                    bindings,
                    {
                        "color_map": f"textures/rocket/wb_{target}_df",
                        "normal_map": f"textures/rocket/wb_{target}_nm",
                        "roughness_map": f"textures/rocket/wb_{target}_r",
                        "metallic_map": f"textures/rocket/wb_{target}_m",
                        "ao_map": f"textures/rocket/wb_{target}_ao",
                        "emissive_map": f"textures/rocket/wb_{target}_e",
                    },
                )
                variables = named_block(source, "variables")
                # These are the exact controls exported by the VT2 SDK's
                # core/stingray_renderer/shader_import/standard parent.  A
                # bound sampler with its use flag left at zero renders as the
                # fallback scalar/color and recreates the placeholder bug.
                for variable in (
                    "use_color_map",
                    "use_normal_map",
                    "use_roughness_map",
                    "use_metallic_map",
                    "use_ao_map",
                    "use_emissive_map",
                ):
                    with self.subTest(material=relative, variable=variable):
                        block = named_block(variables, variable)
                        self.assertEqual(descriptor_field(block, "type"), "scalar")
                        self.assertEqual(descriptor_field(block, "value"), "1")

    def test_units_have_no_lambert_or_old_placeholder_references(self) -> None:
        # The two historical material *paths* were safely repurposed; reject
        # the actual placeholder mechanisms rather than their filenames.
        rejected = re.compile(r"(?i)lambert\d*|textures/default_(?:col|normal)")
        for filename in self.EXPECTED:
            with self.subTest(unit=filename):
                source = without_comments((ROCKET_UNIT_DIR / filename).read_text(encoding="utf-8"))
                self.assertIsNone(rejected.search(source))

    def test_projectile_unit_and_physics_keep_the_runtime_pRocket_contract(self) -> None:
        unit = without_comments((ROCKET_UNIT_DIR / "SM_Rocket.unit").read_text(encoding="utf-8"))
        physics = without_comments((ROCKET_UNIT_DIR / "SM_Rocket.physics").read_text(encoding="utf-8"))
        self.assertIn('unit_template = "explosive_pickup_projectile_unit"', unit)
        self.assertEqual(set(re.findall(r'\b(?:node|shape)\s*=\s*"([^"]+)"', physics)), {"pRocket"})
        self.assertIn('name = "throw"', physics)
        self.assertIn('template = "projectile_physics"', physics)
        self.assertIn('template = "projectile"', physics)

    def test_launcher_physics_keeps_exact_final_mesh_node(self) -> None:
        physics = without_comments(
            (ROCKET_UNIT_DIR / "pRocketLauncher.physics").read_text(encoding="utf-8")
        )
        self.assertEqual(
            set(re.findall(r'\b(?:node|shape)\s*=\s*"([^"]+)"', physics)),
            {"pRocketLauncher"},
        )
        self.assertIn('name = "rp_dropped"', physics)
        self.assertIn('template = "pickup"', physics)

    def test_death_drop_actor_drives_every_launcher_renderable(self) -> None:
        inventory = without_comments((
            REPO_ROOT / "scripts" / "mods" / "doomrocket" / "breeds" /
            "skaven_doomrocket_inventory.lua"
        ).read_text(encoding="utf-8"))
        weapon_item = named_block(inventory, "rocket_glaive_1")
        self.assertRegex(named_block(weapon_item, "drop_reasons"), r"\bdeath\s*=\s*true\b")

        physics = without_comments(
            (ROCKET_UNIT_DIR / "pRocketLauncher.physics").read_text(encoding="utf-8")
        )
        actor_matches = [
            block for block in anonymous_blocks(named_array(physics, "actors"))
            if re.search(r'\bname\s*=\s*"rp_dropped"', block)
        ]
        self.assertEqual(len(actor_matches), 1)
        actor_nodes = re.findall(r'\bnode\s*=\s*"([^"]+)"', actor_matches[0])
        self.assertEqual(actor_nodes, ["pRocketLauncher"])

        unit = without_comments(
            (ROCKET_UNIT_DIR / "pRocketLauncher.unit").read_text(encoding="utf-8")
        )
        renderables = set(re.findall(
            r"(?m)^\s*(\w+)\s*=\s*\{", named_block(unit, "renderables")
        ))
        self.assertEqual(renderables, {"pRocketLauncher", "pRocket"})
        launcher_fbx = BinaryFbx(ROCKET_UNIT_DIR / "pRocketLauncher.fbx")
        require_loaded_rocket_actor_hierarchy(launcher_fbx)
        parents = model_parent_ids(launcher_fbx)
        actor = model_node(launcher_fbx, actor_nodes[0], "Mesh")
        for renderable in renderables:
            node = model_node(launcher_fbx, renderable, "Mesh")
            current = node.properties[0]
            visited: set[int] = set()
            while current != actor.properties[0] and current not in visited:
                visited.add(current)
                current = parents.get(current, -1)
            self.assertEqual(
                current, actor.properties[0],
                f"{renderable} does not inherit the only death-drop actor",
            )

    def test_behavior_and_network_paths_stay_on_stable_units(self) -> None:
        inventory = (
            REPO_ROOT / "scripts" / "mods" / "doomrocket" / "breeds" / "skaven_doomrocket_inventory.lua"
        ).read_text(encoding="utf-8")
        launch = (
            REPO_ROOT / "scripts" / "mods" / "doomrocket" / "behavior" / "nodes" /
            "skaven_doomrocket" / "bt_doomrocket_launch_action.lua"
        ).read_text(encoding="utf-8")
        bootstrap = (
            REPO_ROOT / "scripts" / "mods" / "doomrocket" / "doomrocket.lua"
        ).read_text(encoding="utf-8")
        self.assertIn('unit_name = "units/rocket/pRocketLauncher"', inventory)
        self.assertIn('local unit_name = "units/rocket/SM_Rocket"', launch)
        self.assertIn('"units/rocket/SM_Rocket"', bootstrap)


@unittest.skipUnless(BUNDLE_ROOT.is_dir(), "compiled bundleV2 is not present")
class CrunchWeaponCompiledBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.resources = compiled_bundle_resources()

    def require_one(self, resource_type: str, resource_name: str) -> bytes:
        hits = self.resources.get(resource_key(resource_type, resource_name), [])
        self.assertEqual(
            len(hits),
            1,
            f"compiled {resource_type} {resource_name} must occur exactly once",
        )
        payload = hits[0][1]
        self.assertGreater(len(payload), 0)
        return payload

    def test_all_final_weapon_resources_are_compiled_exactly_once(self) -> None:
        expected = [
            ("unit", "units/rocket/pRocketLauncher"),
            ("unit", "units/rocket/SM_Rocket"),
            ("material", "materials/rocket/rocket_neutral"),
            ("material", "materials/rocket/rocket_red"),
        ]
        for target in ("weapon", "rocket"):
            for suffix in ("df", "nm", "e", "r", "m", "ao"):
                expected.append(("texture", f"textures/rocket/wb_{target}_{suffix}"))
        for resource_type, resource_name in expected:
            with self.subTest(type=resource_type, name=resource_name):
                self.require_one(resource_type, resource_name)

    def test_compiled_unit_material_tables_match_final_mesh_slots(self) -> None:
        launcher = self.require_one("unit", "units/rocket/pRocketLauncher")
        projectile = self.require_one("unit", "units/rocket/SM_Rocket")
        weapon_pair = (
            murmur64a(b"DoomRocket_Weapon") >> 32,
            murmur64a(b"materials/rocket/rocket_neutral"),
        )
        rocket_pair = (
            murmur64a(b"DoomRocket_Rocket") >> 32,
            murmur64a(b"materials/rocket/rocket_red"),
        )
        self.assertEqual(compiled_material_pairs(launcher), {weapon_pair, rocket_pair})
        self.assertEqual(compiled_material_pairs(projectile), {rocket_pair})

        for payload in (launcher, projectile):
            for old_slot in ("lambert2", "lambert3", "lambert4"):
                old_short = murmur64a(old_slot.encode()) >> 32
                self.assertNotIn(struct.pack("<I", old_short), payload)

    def test_compiled_loaded_warhead_inherits_rp_dropped_actor(self) -> None:
        launcher = self.require_one("unit", "units/rocket/pRocketLauncher")
        structure = compiled_unit_structure(launcher)
        launcher_node = compiled_node_index(structure, "pRocketLauncher")
        rocket_node = compiled_node_index(structure, "pRocket")
        self.assertEqual(
            structure.nodes[rocket_node].parent_index,
            launcher_node,
            "compiled loaded pRocket must be a direct child of pRocketLauncher",
        )
        self.assertEqual(structure.nodes[rocket_node].parent_type, 1)
        self.assertEqual(set(structure.mesh_node_indices), {launcher_node, rocket_node})
        rp_dropped = [
            node_hash for name_hash, node_hash in structure.actors
            if name_hash == idstring32("rp_dropped")
        ]
        self.assertEqual(rp_dropped, [idstring32("pRocketLauncher")])
        for renderable_node in structure.mesh_node_indices:
            self.assertTrue(node_inherits(structure.nodes, renderable_node, launcher_node))

    def test_compiled_loaded_warhead_points_toward_p_fx(self) -> None:
        """Preserve the source's signed muzzle direction through compilation."""
        payload = self.require_one("unit", "units/rocket/pRocketLauncher")
        structure = compiled_unit_structure(payload)
        root_node = structure.nodes[compiled_node_index(structure, "root_point")]
        muzzle_node = structure.nodes[compiled_node_index(structure, "p_fx")]
        root = transform_point(root_node.world_transform, (0.0, 0.0, 0.0))
        muzzle = transform_point(muzzle_node.world_transform, (0.0, 0.0, 0.0))
        rocket_points, _triangles = compiled_renderable_geometry(
            structure, "pRocket"
        )
        alignment = directed_cosine(
            _subtract(muzzle, root),
            _subtract(point_centroid(rocket_points), root),
        )
        self.assertGreaterEqual(
            alignment,
            0.9,
            "compiled loaded pRocket points away from p_fx: "
            f"signed cosine={alignment:.6f}, required>=0.900000",
        )

    def test_compiled_launcher_geometry_matches_final_source_root_space(self) -> None:
        """Reject a stale bundle even when the corrected source FBX tests pass."""
        payload = self.require_one("unit", "units/rocket/pRocketLauncher")
        structure = compiled_unit_structure(payload)
        actual_points, actual_triangles = compiled_renderable_geometry(
            structure, "pRocketLauncher"
        )

        source = BinaryFbx(ROCKET_UNIT_DIR / "pRocketLauncher.fbx")
        source_geometry = geometry_by_vertex_count(
            source, MVP_LAUNCHER_VERTEX_COUNT
        )
        expected_points = source_points_to_engine(
            canonical_geometry_points(source, MVP_LAUNCHER_VERTEX_COUNT)
        )
        expected_triangles = triangulated_fbx_faces(source_geometry)

        expected_bounds = tuple(
            (min(point[axis] for point in expected_points),
             max(point[axis] for point in expected_points))
            for axis in range(3)
        )
        actual_bounds = tuple(
            (min(point[axis] for point in actual_points),
             max(point[axis] for point in actual_points))
            for axis in range(3)
        )
        for axis, (expected, actual) in enumerate(zip(expected_bounds, actual_bounds)):
            with self.subTest(metric="bounds", axis=axis):
                self.assertLessEqual(
                    max(abs(left - right) for left, right in zip(expected, actual)),
                    0.005,
                    "compiled launcher bounds do not match the final source FBX "
                    f"(axis={axis}, source={expected}, compiled={actual})",
                )

        expected_axis = principal_axis(expected_points)
        actual_axis = principal_axis(actual_points)
        alignment = abs(sum(
            left * right for left, right in zip(expected_axis, actual_axis)
        ))
        self.assertGreaterEqual(
            alignment,
            0.98,
            "compiled launcher orientation does not match the final source FBX: "
            f"abs(dot)={alignment:.6f}",
        )

        expected_proximity = origin_surface_proximity(
            expected_points, expected_triangles
        )
        actual_proximity = origin_surface_proximity(actual_points, actual_triangles)
        self.assertLessEqual(
            abs(expected_proximity[0] - actual_proximity[0]),
            0.005,
            "compiled launcher grip distance does not match the final source FBX: "
            f"source={expected_proximity[0]:.6f} m, "
            f"compiled={actual_proximity[0]:.6f} m",
        )
        self.assertLessEqual(
            actual_proximity[0],
            0.05,
            "compiled launcher grip surface is more than 5 cm from node 0: "
            f"distance={actual_proximity[0]:.6f} m, "
            f"normalized={actual_proximity[1]:.6f}",
        )
        self.assertLessEqual(
            actual_proximity[1],
            0.08,
            "compiled launcher grip surface exceeds the normalized root-space limit: "
            f"distance={actual_proximity[0]:.6f} m, "
            f"normalized={actual_proximity[1]:.6f}",
        )

        compiled_grip = semantic_grip_cap_centroid(
            engine_points_to_source(actual_points),
            actual_triangles,
            coordinate_tolerance=0.025,
            cap_depth=1.0,
        )
        expected_grip = (0.000002565, 1.108044386, 0.0)
        for axis, (actual, expected) in enumerate(
            zip(compiled_grip, expected_grip)
        ):
            with self.subTest(metric="semantic_grip", axis=axis):
                self.assertAlmostEqual(
                    actual,
                    expected,
                    delta=0.1,
                    msg=(
                        "compiled pistol-grip cap is not at the known-good "
                        f"attachment landmark: actual={compiled_grip} cm, "
                        f"expected={expected_grip} cm"
                    ),
                )


if __name__ == "__main__":
    unittest.main(verbosity=2)
