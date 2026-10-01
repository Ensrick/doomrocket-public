"""SDK-independent decoder and fixture-generation checks (synthetic bytes only)."""
import copy
import struct
import unittest

from chain_descriptor import LINK_EXPRESSIONS, parse_single_chain
from generate_fixtures import CASES, REPO, checked_output, load_base, make_cases, render_case


def synthetic_resource() -> bytearray:
    count = 3
    blob = bytearray(140 + 96 * count)
    put = lambda offset, value: struct.pack_into("<I", blob, offset, value)
    put(0, 1); put(4, 8); put(8, 3)
    blob[12:22] = b"hose_probe"
    put(44, 1); put(52, count)
    for offset, index in ((56, 0), (60, 2), (64, 4)):
        put(offset, index)
    next_index = 6
    for i in range(count):
        offset = 116 + i * 40
        put(offset, i + 1)
        for _, relative in LINK_EXPRESSIONS:
            put(offset + relative, next_index)
            next_index += 2
    expression_start = 116 + 40 * count
    for index in range(0, next_index, 2):
        struct.pack_into("<fI", blob, expression_start + index * 4, 1.0, 0x7FA00000)
    return bytearray(b"TEST" + struct.pack("<I", len(blob)) + blob)


class DecoderTests(unittest.TestCase):
    def test_valid_synthetic_chain(self):
        result = parse_single_chain(synthetic_resource())
        self.assertEqual(result["link_count"], 3)
        self.assertEqual([row["bone_index"] for row in result["links"]], [1, 2, 3])
        self.assertEqual(result["links"][2]["mass"], 1)

    def test_every_truncated_prefix_fails_closed(self):
        resource = synthetic_resource()
        for length in range(len(resource)):
            with self.subTest(length=length), self.assertRaises(ValueError):
                parse_single_chain(resource[:length])

    def test_unknown_header_type_size_count_or_duplicate(self):
        for blob_offset, value in ((0, 2), (4, 16), (8, 9), (52, 1), (52, 257)):
            with self.subTest(offset=blob_offset, value=value):
                data = synthetic_resource()
                struct.pack_into("<I", data, 8 + blob_offset, value)
                with self.assertRaises(ValueError): parse_single_chain(data)
        with self.assertRaises(ValueError):
            parse_single_chain(synthetic_resource() * 2)
        data = synthetic_resource()
        struct.pack_into("<I", data, 4, 1)
        with self.assertRaises(ValueError): parse_single_chain(data)

    def test_unknown_expression_bad_index_or_nonfinite_value(self):
        for offset, value in ((56, 1), (56, 0xFFFFFFFF), (240, 0), (236, 0x7FC00000)):
            with self.subTest(offset=offset):
                data = synthetic_resource()
                struct.pack_into("<I", data, 8 + offset, value)
                with self.assertRaises(ValueError): parse_single_chain(data)

    def test_invalid_name(self):
        for name in ("", "x" * 31, "bad\0name", "wrong"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                parse_single_chain(synthetic_resource(), name)


class FixtureTests(unittest.TestCase):
    def test_nine_independent_cases_leave_base_unchanged(self):
        base = load_base()
        original = copy.deepcopy(base)
        cases = make_cases(base)
        self.assertEqual(tuple(cases), CASES)
        self.assertEqual(base, original)
        cases["base"]["constraints"]["hose"]["link_0"]["mass"] = "999"
        self.assertEqual(cases["flags"]["constraints"]["hose"]["link_0"]["mass"], "2.5")
        self.assertEqual(base, original)

    def test_mutations_keep_int_and_expression_types_deliberate(self):
        cases = make_cases(load_base())
        tip = lambda name: cases[name]["constraints"]["hose"]["link_2"]
        self.assertEqual(tip("mass_zero")["mass"], "0")
        self.assertEqual(tip("mass_numeric")["mass"], 7.5)
        self.assertEqual(tip("mass_string")["mass"], "7.5")
        self.assertEqual(type(tip("flags")["constraint_torsion_spring"]), int)
        self.assertNotIn("bone", tip("no_tip_bone"))
        self.assertEqual(set(tip("unknown_pin")) - set(tip("base")),
                         {"fixed", "pin", "inverse_mass", "target"})

    def test_render_is_deterministic_and_preserves_unsafe_case_labels(self):
        cases = make_cases(load_base())
        self.assertEqual(render_case(cases["base"]), render_case(load_base()))
        self.assertIn('"mass" = 7.5', render_case(cases["mass_numeric"]))
        self.assertIn('"mass" = "7.5"', render_case(cases["mass_string"]))
        self.assertIn('"animations" = [  ]', render_case(cases["base"]))

    def test_output_guard_rejects_source_and_build_root(self):
        for target in (REPO, REPO / "tools", REPO / ".build", REPO / ".build/../units"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                checked_output(target)
        self.assertEqual(checked_output(REPO / ".build/test_chain/source"),
                         (REPO / ".build/test_chain/source").resolve())


if __name__ == "__main__":
    unittest.main(verbosity=2)
