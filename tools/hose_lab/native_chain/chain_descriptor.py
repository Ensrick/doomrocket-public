"""Read the verified single-chain/constant-expression subset of a compiled VT2 ASM.

Locates one uniquely named chain envelope inside the containing resource. This
does not parse the complete state machine or execute its expression bytecode.
Unknown/truncated envelopes and non-finite or non-constant expressions fail closed.
"""
import hashlib
import math
import struct

LINK_EXPRESSIONS = (("constraint_rotation", 12), ("mass", 16), ("length", 20),
                    ("damping", 24), ("constraint_damping", 28),
                    ("torsion_coef", 32), ("constraint_angle", 36))


def parse_single_chain(payload: bytes, debug_name: str = "hose_probe") -> dict:
    name = debug_name.encode("ascii")
    if not name or len(name) >= 31 or b"\0" in name:
        raise ValueError("Native chain debug name must contain 1..30 non-NUL ASCII bytes")
    marker = struct.pack("<III", 1, 8, 3) + name + b"\0" * (32 - len(name))
    start = payload.find(marker)
    if start < 4 or payload.find(marker, start + 1) >= 0:
        raise ValueError("Exactly one identified single-chain envelope is required")
    length = struct.unpack_from("<I", payload, start - 4)[0]
    if length < 56 or length > len(payload) - start:
        raise ValueError("Truncated chain envelope")
    blob = payload[start:start + length]

    def u32(offset):
        return struct.unpack_from("<I", blob, offset)[0]

    count = u32(52)
    if not 2 <= count <= 256 or length != 140 + 96 * count:
        raise ValueError("Unreviewed chain size or expression layout")
    expression_start = 116 + 40 * count

    def expression(index):
        offset = expression_start + 4 * index
        if index % 2 or offset + 8 > length or u32(offset + 4) != 0x7FA00000:
            raise ValueError("Only the proven constant+END expression layout is accepted")
        value = struct.unpack_from("<f", blob, offset)[0]
        if not math.isfinite(value):
            raise ValueError("Non-finite expression constant")
        return value

    result = {
        "sha256": hashlib.sha256(blob).hexdigest(), "bytes": length, "type": u32(8),
        "debug_name": debug_name, "enabled": u32(44), "debug_draw": u32(48),
        "link_count": count, "gravity": expression(u32(56)),
        "global_damping": expression(u32(60)), "vector_field_multiplier": expression(u32(64)),
        "collision_type": u32(68), "collision_bone": u32(72), "links": [], "_blob": blob,
    }
    for i in range(count):
        offset = 116 + 40 * i
        row = {"bone_index": u32(offset), "constraint_type": u32(offset + 4),
               "constraint_torsion_spring": u32(offset + 8)}
        row.update((key, expression(u32(offset + relative))) for key, relative in LINK_EXPRESSIONS)
        result["links"].append(row)
    return result
