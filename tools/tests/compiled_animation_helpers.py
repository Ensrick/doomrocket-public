"""Independent readers for compiled skeleton names and animation keys."""
import struct, math
from test_warlock_weapon_pipeline import PackedCursor, murmur64a

def array(cursor, stride):
    return cursor.take(cursor.u32() * stride)


def words(cursor):
    data = array(cursor, 4)
    return tuple(value[0] for value in struct.iter_unpack("<I", data))


def count(cursor, maximum=4096):
    value = cursor.u32()
    if value > maximum:
        raise AssertionError("Unreasonable compiled animation record count")
    return value


def compiled_bones(payload):
    c = PackedCursor(payload)
    bone_count, lod_count = count(c), count(c)
    hashes = struct.unpack(f"<{bone_count}I", c.take(bone_count * 4))
    c.take(lod_count * 4)
    names = c.take(len(payload) - c.offset).split(b"\0")
    if names[-1:] == [b""]:
        names.pop()
    decoded = tuple(name.decode("ascii") for name in names)
    if len(decoded) != bone_count or tuple(murmur64a(n.encode()) >> 32 for n in decoded) != hashes:
        raise AssertionError("Compiled bone names/order do not match their hashes")
    return decoded


def compiled_reference_positions(payload, reference_index, include_times=False):
    """Read the reference's initial position and every position key.

VT2 interleaved animations use an explicit initial pose and tagged packed or
unpacked keys. Other channels are consumed without decoding rotations. Reject
unknown/truncated streams rather than skipping bytes until a guessed marker.
    """
    c = PackedCursor(payload)
    if c.u32() != 0:
        raise AssertionError("Expected VT2 interleaved animation header")
    bones = count(c, 1024)
    duration, size = struct.unpack("<fI", c.take(8))
    if not 0 <= reference_index < bones or not math.isfinite(duration) or duration <= 0:
        raise AssertionError("Invalid animation reference or duration")
    if size != len(payload):
        raise AssertionError("Animation header size does not match payload")
    array(c, 8)  # beat times

    def packed_vector():
        return tuple(v * (20 / 65536) - 10 for v in struct.unpack("<3H", c.take(6)))

    def vector():
        return struct.unpack("<3f", c.take(12))

    sync_type = c.u16()
    if sync_type not in (1, 7):
        raise AssertionError("Unknown animation initial pose encoding")
    positions = []
    times = []
    for bone in range(bones):
        if sync_type == 1:
            position = packed_vector()
            c.skip(10)  # packed rotation + scale
        else:
            position = vector()
            c.skip(28)  # quaternion + scale
        if bone == reference_index:
            positions.append(position)
            times.append(0.)
    ended = False
    while c.offset < len(payload):
        tag = c.u16()
        kind = tag & 0xC000
        if kind:
            combined = tag << 16 | c.u16()
            bone = combined >> 20 & 0x3FF
            time = (combined & 0xFFFFF) * .001
            if bone >= bones:
                raise AssertionError("Packed key references a foreign bone")
            if kind == 0x8000:
                position = packed_vector()
                if bone == reference_index:
                    positions.append(position)
                    times.append(time)
            else:
                c.skip(4 if kind == 0xC000 else 6)
        elif tag in (4, 5, 6):
            bone = c.u16()
            time = struct.unpack("<f", c.take(4))[0]
            if bone >= bones:
                raise AssertionError("Unpacked key references a foreign bone")
            if tag == 4:
                position = vector()
                if bone == reference_index:
                    positions.append(position)
                    times.append(time)
            else:
                c.skip(16 if tag == 5 else 12)
        elif tag == 2:
            c.skip(8)  # trigger
        elif tag == 3:
            ended = True
            break
        else:
            raise AssertionError(f"Unknown interleaved animation item {tag}")
    if not ended or c.offset != len(payload) or not positions:
        raise AssertionError("Animation is incomplete or contains trailing bytes")
    if not all(math.isfinite(value) for position in positions for value in position):
        raise AssertionError("Animation contains nonfinite reference positions")
    if not all(math.isfinite(t) and t >= 0 for t in times) or times != sorted(times):
        raise AssertionError("Animation contains invalid position key times")
    return tuple(zip(times, positions)) if include_times else tuple(positions)
