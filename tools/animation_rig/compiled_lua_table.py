"""Decode the SDK's generated manifest without executing or adapting bytecode.

This is deliberately not a general Lua interpreter. It accepts one current
LuaJIT v2 prototype containing only the seven observed table-construction
opcodes, and compares its returned data with the complete JSON manifest.

Primary format/semantics: LuaJIT src/lj_bcdump.h, lj_bcread.c, lj_bc.h and
vm_x64.dasc. The local primary-source copy is OpenEnroth/thirdparty/luajit/src.
The GC64/FR2 compatibility bit is preserved; no header or instructions change.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import struct

SOURCE_NAME = "@scripts/mods/doomrocket/utils/doomrocket_animation_manifest.lua"
MAX_PAYLOAD = 16 * 1024 * 1024
MAX_ITEMS = 100_000
MAX_DEPTH = 64
OPCODES = {39: "KSTR", 52: "TNEW", 53: "TDUP", 60: "TSETV",
           61: "TSETS", 62: "TSETB", 76: "RET1"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Reader:
    def __init__(self, data):
        self.data, self.offset = data, 0

    def take(self, count):
        require(0 <= count <= len(self.data) - self.offset, "Truncated LuaJIT bytecode")
        start = self.offset
        self.offset += count
        return self.data[start:self.offset]

    def byte(self):
        return self.take(1)[0]

    def uleb(self):
        value = 0
        for index in range(5):
            byte = self.byte()
            require(index < 4 or byte <= 15, "LuaJIT ULEB128 exceeds 32 bits")
            value |= (byte & 127) << (7 * index)
            if byte < 128:
                require(index == 0 or byte != 0, "Noncanonical LuaJIT ULEB128")
                return value
        raise ValueError("Unterminated LuaJIT ULEB128")

    def string(self, count):
        return self.take(count).decode("utf-8", errors="strict")


class Decoder:
    def __init__(self):
        self.constant_entries = 0
        self.writes = 0
        self.constructed_entries = 0
        self.tables_created = 0
        self.constant_native_slots = 0
        self.constructed_native_slots = 0
        self.template_slots = {}
        self.opcode_counts = {}

    def scalar(self, reader):
        kind = reader.uleb()
        if kind >= 5:
            return reader.string(kind - 5)
        if kind == 0:
            return None
        if kind == 1:
            return False
        if kind == 2:
            return True
        if kind == 3:
            value = reader.uleb()
            return value if value < 0x80000000 else value - 0x100000000
        low, high = reader.uleb(), reader.uleb()
        value = struct.unpack("<d", struct.pack("<II", low, high))[0]
        require(math.isfinite(value), "Nonfinite LuaJIT table number")
        return value

    @staticmethod
    def key(value):
        # The trusted JSON producer uses strings and integer array indices.
        require(type(value) in (str, int), "Unsupported manifest table key")
        return value

    def table(self, reader):
        arrays, hashes = reader.uleb(), reader.uleb()
        self.constant_entries += arrays + 2 * hashes
        require(self.constant_entries <= MAX_ITEMS, "Manifest constant table budget exceeded")
        # lj_bcread.c/lj_tab.h round a nonzero hash size to at least two
        # slots. Keep NIL-filled array capacity, which a Python dict omits.
        capacity = arrays + ((1 << max(1, (hashes - 1).bit_length())) if hashes else 0)
        self.constant_native_slots += 1 + capacity
        require(self.constant_native_slots <= MAX_ITEMS,
                "Manifest constant table allocation budget exceeded")
        result, seen = {}, set()
        for index in range(arrays):
            value = self.scalar(reader)
            if value is not None:
                result[index] = value
                seen.add(index)
        for _ in range(hashes):
            key, value = self.key(self.scalar(reader)), self.scalar(reader)
            require(key not in seen, "Duplicate manifest template key")
            seen.add(key)
            if value is not None:
                result[key] = value
        self.template_slots[id(result)] = capacity
        return result

    def decode(self, payload, source_name):
        require(12 <= len(payload) <= MAX_PAYLOAD, "Unsupported SDK Lua payload size")
        length, version, reserved = struct.unpack_from("<III", payload)
        require((version, reserved) == (2, 0) and length == len(payload) - 12,
                "Unsupported SDK Lua container header or length")
        outer = Reader(payload[12:])
        require(outer.take(4) == b"\x1bLJ\x02", "Expected LuaJIT bytecode version 2")
        flags = outer.uleb()
        require(flags == 0, "Expected unchanged SDK LuaJIT frame-format flags 0")
        chunk_name = outer.string(outer.uleb())
        require(chunk_name == source_name, "Compiled Lua source identity differs")
        proto = Reader(outer.take(outer.uleb()))
        require(outer.byte() == 0 and outer.offset == len(outer.data),
                "Expected exactly one LuaJIT prototype and exact EOF")
        proto_flags, params, frames, upvalues = (proto.byte() for _ in range(4))
        require(proto_flags == 2 and params == 0 and upvalues == 0 and 0 < frames <= 255,
                "Manifest must have one argument-free, upvalue-free constructor prototype")
        gc_count, number_count, instruction_count = (proto.uleb() for _ in range(3))
        require(0 < gc_count <= MAX_ITEMS and number_count == 0 and
                0 < instruction_count <= MAX_ITEMS,
                "Unsupported manifest constant or instruction inventory")
        debug_length = proto.uleb()
        if debug_length:
            proto.uleb()  # First source line.
            proto.uleb()  # Number of source lines.
        instructions = [struct.unpack("<I", proto.take(4))[0]
                        for _ in range(instruction_count)]
        constants = []
        for _ in range(gc_count):
            kind = proto.uleb()
            if kind >= 5:
                constants.append(proto.string(kind - 5))
            elif kind == 1:
                constants.append(self.table(proto))
            else:
                raise ValueError("Child prototypes and FFI constants are forbidden")
        proto.take(debug_length)
        require(proto.offset == len(proto.data), "Unlisted LuaJIT prototype data")

        unset = object()
        registers = [unset] * frames

        def register(index):
            require(index < frames and registers[index] is not unset,
                    "Uninitialized or out-of-range manifest register")
            return registers[index]

        def constant(index, kind):
            require(index < len(constants), "Manifest constant index out of range")
            value = constants[-1 - index]  # GC constants precede k in reverse index order.
            require(type(value) is kind, "Manifest constant has the wrong type")
            return value

        def assign(table, key, value):
            require(type(table) is dict, "Manifest assignment destination is not a table")
            key = self.key(key)
            require(value is not None, "Manifest constructor cannot assign nil")
            self.writes += 1
            require(self.writes <= MAX_ITEMS, "Manifest assignment budget exceeded")
            if key not in table:
                self.constructed_entries += 1
                require(self.constructed_entries <= MAX_ITEMS, "Manifest construction budget exceeded")
                self.constructed_native_slots += 1
                require(self.constructed_native_slots <= MAX_ITEMS, "Manifest construction budget exceeded")
            table[key] = value

        def new_table(template=None, capacity=0):
            self.tables_created += 1
            self.constructed_entries += 1 + (len(template) if template is not None else 0)
            require(self.constructed_entries <= MAX_ITEMS, "Manifest construction budget exceeded")
            self.constructed_native_slots += 1 + (
                self.template_slots[id(template)] if template is not None else capacity)
            require(self.constructed_native_slots <= MAX_ITEMS, "Manifest construction budget exceeded")
            return template.copy() if template is not None else {}

        result = None
        for index, instruction in enumerate(instructions):
            opcode, a = instruction & 255, (instruction >> 8) & 255
            b, c, d = instruction >> 24, (instruction >> 16) & 255, instruction >> 16
            require(opcode in OPCODES and a < frames, "Unsupported manifest opcode or register")
            name = OPCODES[opcode]
            self.opcode_counts[name] = self.opcode_counts.get(name, 0) + 1
            if name == "KSTR":
                registers[a] = constant(d, str)
            elif name == "TNEW":
                # vm_x64.dasc: low 11 bits are array slots (0x7ff means
                # 0x801); high five bits encode a power-of-two hash size.
                arrays, hash_bits = d & 0x7ff, d >> 11
                capacity = (0x801 if arrays == 0x7ff else arrays) + (
                    (1 << hash_bits) if hash_bits else 0)
                registers[a] = new_table(capacity=capacity)
            elif name == "TDUP":
                registers[a] = new_table(constant(d, dict))
            elif name == "TSETV":
                assign(register(b), register(c), register(a))
            elif name == "TSETS":
                assign(register(b), constant(c, str), register(a))
            elif name == "TSETB":
                assign(register(b), c, register(a))
            else:
                require(index == len(instructions) - 1 and d == 2,
                        "Manifest must end with exactly one single-value return")
                result = register(a)
                require(type(result) is dict, "Manifest does not return a table")
        require(result is not None, "Manifest has no final table return")
        return result, {"schema": 1, "status": "compiled-lua-pure-table-decoded",
            "container_version": version, "bytecode_version": 2, "bytecode_flags": flags,
            "source_name": chunk_name, "prototype_count": 1, "frame_slots": frames,
            "gc_constants": gc_count, "numeric_constants": number_count,
            "constant_entries": self.constant_entries, "instructions": instruction_count,
            "opcode_counts": self.opcode_counts, "table_assignments": self.writes,
            "tables_created": self.tables_created, "constructed_entries": self.constructed_entries,
            "constant_native_table_slots": self.constant_native_slots,
            "constructed_native_table_slots": self.constructed_native_slots,
            "debug_bytes": debug_length, "compiled_lua_sha256": hashlib.sha256(payload).hexdigest(),
            "native_or_lua_bytecode_execution": False, "bytecode_modified": False}


def compare_tables(actual, expected):
    active = set()
    visited_entries = 0

    def compare(value, reference, depth, label):
        nonlocal visited_entries
        require(depth <= MAX_DEPTH, "Manifest nesting budget exceeded")
        if type(reference) in (dict, list):
            require(type(value) is dict, "Compiled manifest table differs at " + label)
            require(id(value) not in active, "Compiled manifest contains a cycle")
            keys = set(reference) if type(reference) is dict else set(range(1, len(reference) + 1))
            require(set(value) == keys, "Compiled manifest keys differ at " + label)
            active.add(id(value))
            visited_entries += len(keys)
            require(visited_entries <= MAX_ITEMS, "Manifest comparison budget exceeded")
            for key in keys:
                item = reference[key] if type(reference) is dict else reference[key - 1]
                compare(value[key], item, depth + 1, label + "/" + str(key))
            active.remove(id(value))
        elif type(reference) in (int, float):
            require(type(value) in (int, float) and math.isfinite(reference) and
                    math.isfinite(value) and value == reference,
                    "Compiled manifest number differs at " + label)
        else:
            require(type(reference) in (str, bool) and type(value) is type(reference) and value == reference,
                    "Compiled manifest scalar differs at " + label)

    compare(actual, expected, 0, "root")
    return visited_entries


def verify_manifest(payload, manifest, source_name=SOURCE_NAME):
    decoded, proof = Decoder().decode(payload, source_name)
    proof["manifest_entries_compared"] = compare_tables(decoded, manifest)
    proof["status"] = "compiled-lua-manifest-semantics-passed"
    proof["manifest_json_sha256"] = hashlib.sha256(
        json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                   allow_nan=False).encode()).hexdigest()
    return proof


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiled-lua", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--source-name", default=SOURCE_NAME)
    args = parser.parse_args()
    print(json.dumps(verify_manifest(args.compiled_lua.read_bytes(),
        json.loads(args.manifest.read_text(encoding="utf-8")), args.source_name), indent=2))
