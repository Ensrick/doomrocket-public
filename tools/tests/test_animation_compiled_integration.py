"""Reject malformed DynamicData before granting runtime profile ownership."""
from pathlib import Path
import struct
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'animation_rig'))
from compiled_integration import dynamic_strings
from test_warlock_weapon_pipeline import idstring32


class CompiledMetadata(unittest.TestCase):
    def fixture(self):
        name=idstring32('warlock_rig_profile');raw=b'localized-v1-runtime\0'
        raw+=b'\0'*(-len(raw)%4)
        return struct.pack('<6I',8,0,name,0xffffffff,3,len(raw))+raw

    def test_expected_string_hash_and_padded_value(self):
        self.assertEqual(dynamic_strings(self.fixture()),{0x3b8925a1:'localized-v1-runtime'})

    def test_empty_shipping_header(self):
        self.assertEqual(dynamic_strings(struct.pack('<2I',0xffffffff,0)),{})

    def test_truncated_value_rejected(self):
        with self.assertRaises((ValueError,AssertionError)):dynamic_strings(self.fixture()[:-1])

    def test_embedded_null_rejected(self):
        raw=bytearray(self.fixture());raw[27]=0
        with self.assertRaises(ValueError):dynamic_strings(raw)

    def test_type_confusion_rejected(self):
        raw=bytearray(self.fixture());struct.pack_into('<I',raw,16,2)
        with self.assertRaises(ValueError):dynamic_strings(raw)

    def test_invalid_next_offset_rejected(self):
        raw=bytearray(self.fixture());struct.pack_into('<I',raw,12,8)
        with self.assertRaises(ValueError):dynamic_strings(raw)

    def test_duplicate_key_rejected(self):
        raw=bytearray(self.fixture());struct.pack_into('<I',raw,12,len(raw));raw.extend(self.fixture()[8:])
        with self.assertRaises(ValueError):dynamic_strings(raw)

    def test_terminal_trailing_data_rejected(self):
        with self.assertRaises(ValueError):dynamic_strings(self.fixture()+b'\0\0\0\0')


if __name__=='__main__':unittest.main()
