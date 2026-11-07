"""Malformed or executable bytecode must not satisfy the compiled manifest gate."""
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "animation_rig"))
import compiled_lua_table as c


def uleb(value):
    data = bytearray()
    while value >= 128:
        data.append((value & 127) | 128)
        value >>= 7
    data.append(value)
    return bytes(data)


def scalar(value):
    if value is None:
        return b"\0"
    if type(value) is bool:
        return bytes([2 if value else 1])
    if type(value) is str:
        raw = value.encode()
        return uleb(5 + len(raw)) + raw
    if type(value) is int:
        return b"\3" + uleb(value & 0xffffffff)
    low, high = struct.unpack("<II", struct.pack("<d", value))
    return b"\4" + uleb(low) + uleb(high)


def template(value):
    array = max((key for key in value if type(key) is int and key >= 0), default=-1) + 1
    hashes = [(key, item) for key, item in value.items() if type(key) is not int or key < 0]
    return (uleb(array) + uleb(len(hashes)) +
            b"".join(scalar(value.get(key)) for key in range(array)) +
            b"".join(scalar(key) + scalar(item) for key, item in hashes))


def ad(opcode, a, d=0):
    return opcode | a << 8 | d << 16


def abc(opcode, a, b, x):
    return opcode | a << 8 | x << 16 | b << 24


def payload(constants, instructions, *, source=c.SOURCE_NAME, flags=0,
            proto_flags=2, params=0, upvalues=0, numeric_constants=0, frames=4):
    kgc = b"".join((b"\1" + template(value)) if type(value) is dict else
                   uleb(5 + len(value.encode())) + value.encode()
                   for value in reversed(constants))
    proto = (bytes([proto_flags, params, frames, upvalues]) + uleb(len(constants)) +
             uleb(numeric_constants) + uleb(len(instructions)) + b"\0" +
             b"".join(struct.pack("<I", word) for word in instructions) + kgc)
    raw = b"\x1bLJ\2" + uleb(flags) + uleb(len(source.encode())) + source.encode() + uleb(len(proto)) + proto + b"\0"
    return struct.pack("<III", len(raw), 2, 0) + raw


def fixture():
    constants = [{"schema": 1, "enabled": False, "scale": 0.25, "signed": -7},
                 "profiles", "localized", {"owner": "legacy"}, "channels",
                 {1: "root", 2: "j_hips"}, "steps"]
    code = [ad(53, 0, 0), ad(52, 1), ad(53, 2, 3), ad(39, 3, 2),
            abc(60, 2, 1, 3), abc(61, 1, 0, 1), ad(53, 1, 5),
            abc(61, 1, 0, 4), ad(52, 1), ad(53, 2, 3),
            abc(62, 2, 1, 1), abc(61, 1, 0, 6), ad(76, 0, 2)]
    expected = {"schema": 1, "enabled": False, "scale": 0.25, "signed": -7,
                "profiles": {"localized": {"owner": "legacy"}},
                "channels": ["root", "j_hips"], "steps": [{"owner": "legacy"}]}
    return constants, code, expected


class CompiledLuaTable(unittest.TestCase):
    def test_all_observed_constructor_opcodes_and_full_manifest(self):
        constants, code, expected = fixture()
        proof = c.verify_manifest(payload(constants, code), expected)
        self.assertEqual(proof["instructions"], len(code))
        self.assertEqual(set(proof["opcode_counts"]), set(c.OPCODES.values()))
        self.assertFalse(proof["native_or_lua_bytecode_execution"])
        self.assertFalse(proof["bytecode_modified"])

    def test_stale_owner_rejected_even_with_same_other_fields(self):
        constants, code, expected = fixture()
        expected["profiles"]["localized"]["owner"] = "authored"
        with self.assertRaises(ValueError): c.verify_manifest(payload(constants, code), expected)

    def test_boolean_cannot_satisfy_numeric_field(self):
        for boolean, number in ((True, 1), (False, 0)):
            with self.subTest(boolean=boolean), self.assertRaises(ValueError):
                c.verify_manifest(payload([{"schema": boolean}], [ad(53, 0), ad(76, 0, 2)]), {"schema": number})
            with self.subTest(number=number), self.assertRaises(ValueError):
                c.verify_manifest(payload([{"schema": number}], [ad(53, 0), ad(76, 0, 2)]), {"schema": boolean})

    def test_utf8_string_and_false_template_values_preserved(self):
        expected = {"étiquette": "Arnaud's rig", "enabled": False}
        c.verify_manifest(payload([expected], [ad(53, 0), ad(76, 0, 2)]), expected)

    def test_missing_or_extra_field_rejected(self):
        constants, code, expected = fixture()
        for changed in ({key: value for key, value in expected.items() if key != "channels"},
                        dict(expected, extra="wrong")):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                c.verify_manifest(payload(constants, code), changed)

    def test_calls_branches_globals_and_varargs_rejected(self):
        for opcode in (18, 54, 55, 65, 67, 71, 72, 88):
            with self.subTest(opcode=opcode), self.assertRaises(ValueError):
                c.verify_manifest(payload([{}], [ad(opcode, 0), ad(76, 0, 2)]), {})

    def test_fr2_flags_not_adapted(self):
        with self.assertRaises(ValueError): c.verify_manifest(payload([{}], [ad(53, 0), ad(76, 0, 2)], flags=8), {})

    def test_source_identity_must_match(self):
        with self.assertRaises(ValueError): c.verify_manifest(payload([{}], [ad(53, 0), ad(76, 0, 2)], source="@other.lua"), {})

    def test_upvalues_params_and_numeric_register_constants_rejected(self):
        for options in ({"upvalues": 1}, {"params": 1}, {"numeric_constants": 1}, {"proto_flags": 3}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                c.verify_manifest(payload([{}], [ad(53, 0), ad(76, 0, 2)], **options), {})

    def test_out_of_range_constants_and_uninitialized_registers_rejected(self):
        for code in ([ad(53, 0, 1), ad(76, 0, 2)], [ad(76, 0, 2)],
                     [ad(53, 4), ad(76, 0, 2)], [ad(53, 0), abc(61, 0, 1, 0), ad(76, 0, 2)]):
            with self.subTest(code=code), self.assertRaises(ValueError):
                c.verify_manifest(payload([{}], code), {})

    def test_wrong_template_or_key_constant_type_rejected(self):
        for constants, code in ((["text"], [ad(53, 0), ad(76, 0, 2)]),
                                ([{}], [ad(39, 0), ad(76, 0, 2)]),
                                ([{}], [ad(53, 0), abc(61, 0, 0, 0), ad(76, 0, 2)])):
            with self.subTest(code=code), self.assertRaises(ValueError):
                c.verify_manifest(payload(constants, code), {})

    def test_table_copy_allocation_is_bounded_before_copy(self):
        constants = [{"a": 1, "b": 2, "c": 3, "d": 4}]
        code = [ad(53, 0)] * 4 + [ad(76, 0, 2)]
        with patch.object(c, "MAX_ITEMS", 16), self.assertRaisesRegex(ValueError, "construction budget"):
            c.verify_manifest(payload(constants, code), constants[0])

    def test_native_tnew_exponential_hash_capacity_is_bounded(self):
        with self.assertRaisesRegex(ValueError, "construction budget"):
            c.verify_manifest(payload([{}], [ad(52, 0, 31 << 11), ad(76, 0, 2)]), {})

    def test_sparse_nil_template_copy_capacity_is_bounded(self):
        # All eight array slots deserialize to NIL, so the logical dict is
        # empty; TDUP still allocates/copies those native slots each time.
        constants = [{7: None}]
        code = [ad(53, 0)] * 3 + [ad(76, 0, 2)]
        with patch.object(c, "MAX_ITEMS", 24), self.assertRaisesRegex(ValueError, "construction budget"):
            c.verify_manifest(payload(constants, code), {})

    def test_nested_comparison_budget_is_bounded(self):
        actual, expected = {}, {}
        for _ in range(c.MAX_DEPTH + 2):
            actual, expected = {"next": actual}, {"next": expected}
        with self.assertRaisesRegex(ValueError, "nesting budget"):
            c.compare_tables(actual, expected)

    def test_return_must_be_single_final_instruction(self):
        for code in ([ad(53, 0)], [ad(53, 0), ad(76, 0, 1)],
                     [ad(53, 0), ad(76, 0, 2), ad(53, 0)]):
            with self.subTest(code=code), self.assertRaises(ValueError):
                c.verify_manifest(payload([{}], code), {})

    def test_nonfinite_template_value_rejected(self):
        with self.assertRaises(ValueError): c.verify_manifest(payload([{"value": float("nan")}], [ad(53, 0), ad(76, 0, 2)]), {"value": 1})

    def test_cycles_rejected(self):
        cyclic = {}; cyclic["self"] = cyclic
        with self.assertRaises(ValueError): c.compare_tables(cyclic, {"self": {}})

    def test_truncation_trailing_data_and_second_prototype_rejected(self):
        raw = payload([{}], [ad(53, 0), ad(76, 0, 2)])
        for changed in (raw[:-1], raw + b"\0", raw[:-1] + b"\1\0\0"):
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                c.verify_manifest(changed, {})

    def test_invalid_or_noncanonical_uleb_rejected(self):
        for encoded in (b"\xff\xff\xff\xff\x1f", b"\x80\0", b"\x80"):
            with self.subTest(encoded=encoded), self.assertRaises(ValueError): c.Reader(encoded).uleb()


if __name__ == "__main__": unittest.main()
