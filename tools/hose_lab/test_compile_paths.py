"""SDK-free path guard regressions; all filesystem fixtures are disposable."""
from pathlib import Path
import contextlib
import io
import os
import shutil
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from compile_paths import indexed_resources, reject_redirect, validate_probe
from rig._paths import resolve_paths


class CompilePathTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="hose_compile_paths_")
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "repo"
        self.repo.mkdir()
        self.repo = self.repo.resolve()  # Windows TEMP may contain an 8.3 alias.
        self.probe = self.repo / ".build/probe"
        self.data = self.probe / "data"

    def index(self, text):
        self.data.mkdir(parents=True, exist_ok=True)
        (self.data / "debug_file_index.sjson").write_text(text, encoding="utf-8")

    def test_new_and_existing_dedicated_output_are_allowed(self):
        self.assertEqual(validate_probe(self.repo, Path(".build/probe")), self.probe)
        for directory in ("source/units/hose", "data/data/12", "bundle"):
            (self.probe / directory).mkdir(parents=True, exist_ok=True)
        (self.probe / "compiler.stdout.log").write_text("old log")
        self.assertEqual(validate_probe(self.repo, self.probe), self.probe)

    def assert_repo_alias_works(self, alias):
        self.index('"data/12/1234" = "hose.unit"\n')
        target = self.data / "data/12/1234"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"fixture")
        for probe in (alias / ".build/probe", Path(".build/probe"), self.probe):
            self.assertEqual(validate_probe(alias, probe), self.probe)
        self.assertEqual(indexed_resources(alias, alias / ".build/probe",
                                           alias / ".build/probe/data", ["hose.unit"]), [target])
        arguments = self.rig_arguments(alias / ".build/probe")
        arguments[arguments.index("--repo") + 1] = str(alias)
        with patch.object(sys, "argv", arguments):
            self.assertEqual(resolve_paths(), (self.probe, self.repo))

    def mocked_alias_resolver(self, alias):
        original_resolve = Path.resolve

        def resolve(path, *args, **kwargs):
            if path == alias:
                return self.repo
            if path.is_relative_to(alias):
                raise AssertionError("Alias descendants must not be resolved before reparse inspection")
            return original_resolve(path, *args, **kwargs)
        return resolve

    def test_known_lexical_repo_alias_is_mapped_without_resolving_descendants(self):
        alias = self.repo.parent / "KNOWN~1"
        with patch.object(Path, "resolve", self.mocked_alias_resolver(alias)):
            self.assert_repo_alias_works(alias)
            # An unrelated lexical prefix is not guessed or followed into scope.
            with self.assertRaises(ValueError):
                validate_probe(self.repo, alias / ".build/probe")

    def test_known_repo_alias_does_not_bypass_existing_child_redirect_guard(self):
        alias = self.repo.parent / "KNOWN~1"
        self.data.mkdir(parents=True)
        original = self.repo.parent / "outside.txt"
        original.write_text("preserve")
        os.link(original, self.data / "compiled-output")
        with patch.object(Path, "resolve", self.mocked_alias_resolver(alias)):
            with self.assertRaisesRegex(ValueError, "Hard-linked output"):
                validate_probe(alias, alias / ".build/probe")
        self.assertEqual(original.read_text(), "preserve")

    @unittest.skipUnless(os.name == "nt", "Windows 8.3 alias regression")
    def test_real_windows_short_repo_alias_if_available(self):
        import ctypes
        get_short = ctypes.windll.kernel32.GetShortPathNameW
        get_short.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p, ctypes.c_uint32]
        get_short.restype = ctypes.c_uint32
        needed = get_short(str(self.repo), None, 0)
        if not needed:
            self.skipTest("GetShortPathNameW is unavailable for the temporary directory")
        buffer = ctypes.create_unicode_buffer(needed)
        self.assertGreater(get_short(str(self.repo), buffer, needed), 0)
        alias = Path(buffer.value)
        if alias == self.repo:
            self.skipTest("The temporary filesystem does not provide a distinct 8.3 alias")
        self.assert_repo_alias_works(alias)

    def test_root_and_traversal_and_prefix_sibling_are_rejected(self):
        for path in (self.repo / ".build", self.repo / ".build/../shipping",
                     self.repo / ".build-other/probe", self.repo):
            with self.subTest(path=path), self.assertRaises(ValueError):
                validate_probe(self.repo, path)

    def test_existing_file_cannot_be_used_as_directory(self):
        self.probe.parent.mkdir(parents=True)
        self.probe.write_text("not a directory")
        with self.assertRaises(ValueError):
            validate_probe(self.repo, self.probe)

    def test_windows_reparse_attribute_is_rejected_without_following(self):
        info = SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=info), self.assertRaises(ValueError):
            reject_redirect(self.probe)

    def test_nested_hardlinked_output_is_rejected(self):
        self.data.mkdir(parents=True)
        original = Path(self.temp.name) / "outside.txt"
        original.write_text("preserve")
        os.link(original, self.data / "compiler-output")
        with self.assertRaises(ValueError):
            validate_probe(self.repo, self.probe)
        self.assertEqual(original.read_text(), "preserve")

    def test_nested_file_symlink_including_dangling_is_rejected(self):
        self.data.mkdir(parents=True)
        redirect = self.data / "output"
        try:
            redirect.symlink_to(Path(self.temp.name) / "absent.txt")
        except OSError as exc:
            self.skipTest(f"Creating symlinks is unavailable: {exc}")
        with self.assertRaises(ValueError):
            validate_probe(self.repo, self.probe)

    @unittest.skipUnless(os.name == "nt", "Windows junction regression")
    def test_existing_nested_windows_junction_is_rejected(self):
        outside = Path(self.temp.name) / "outside"
        outside.mkdir()
        # Native PowerShell throughout; cleanup removes only the junction itself.
        quote = lambda p: "'" + str(p).replace("'", "''") + "'"
        for number, relative in enumerate((".build", ".build/probe", ".build/probe/source",
                                           ".build/probe/data/data/ab", ".build/probe/bundle")):
            with self.subTest(redirect=relative):
                repo = Path(self.temp.name) / f"repo-junction-{number}"
                junction = repo / relative
                junction.parent.mkdir(parents=True)
                command = ("$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path "
                           + quote(junction) + " -Target " + quote(outside) + " | Out-Null")
                subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
                               check=True, capture_output=True, text=True)
                try:
                    with self.assertRaises(ValueError):
                        validate_probe(repo, repo / ".build/probe")
                finally:
                    junction.rmdir()
        self.assertTrue(outside.is_dir())

    def rig_arguments(self, output):
        (self.repo / "AGENTS.md").write_text("temporary test checkout")
        (self.repo / "tools").mkdir(exist_ok=True)
        return ["rig", "--repo", str(self.repo), "--output", str(output)]

    def test_rig_resolver_creates_only_dedicated_output(self):
        with patch.object(sys, "argv", self.rig_arguments(".build/probe")):
            base, repo = resolve_paths()
        self.assertEqual((base, repo), (self.probe, self.repo))
        self.assertTrue(base.is_dir())

    def test_rig_resolver_rejects_build_root_before_mkdir(self):
        with patch.object(sys, "argv", self.rig_arguments(self.repo / ".build")):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                resolve_paths()
        self.assertFalse((self.repo / ".build").exists())

    def test_rig_resolver_fails_closed_under_python_optimization(self):
        with patch.object(sys, "flags", SimpleNamespace(optimize=1)):
            with self.assertRaisesRegex(RuntimeError, "requires Python assertions"):
                resolve_paths()
        self.assertFalse((self.repo / ".build").exists())

    def test_optimized_subprocesses_reject_before_output_without_lab_dependencies(self):
        lab = Path(__file__).resolve().parent
        imports = ("from rig._paths import resolve_paths; resolve_paths()",
                   "from rig import test_contract", "from solver import lab_paths")
        for statement in imports:
            for mode in ("flag", "environment"):
                with self.subTest(statement=statement, mode=mode):
                    environment = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
                    environment.pop("PYTHONOPTIMIZE", None)
                    arguments = [sys.executable]
                    if mode == "flag":
                        arguments.append("-O")
                    else:
                        environment["PYTHONOPTIMIZE"] = "1"
                    code = f"import sys; sys.path.insert(0, {str(lab)!r}); {statement}"
                    result = subprocess.run(arguments + ["-c", code], cwd=self.repo,
                                            env=environment, capture_output=True, text=True)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("RuntimeError", result.stderr)
                    self.assertIn("assert", result.stderr.lower())
        self.assertFalse((self.repo / ".build").exists())

    @unittest.skipUnless(shutil.which("powershell"), "Windows PowerShell runner check")
    def test_powershell_wrappers_reject_outside_output_before_inputs_or_writes(self):
        lab = Path(__file__).resolve().parent
        wrappers = (("compiled/Invoke-HoseAssetProbe.ps1", "-ProbeRoot"),
                    ("native_chain/Invoke-NativeChainProbe.ps1", "-ProbeRoot"),
                    ("rig/Invoke-RigProbe.ps1", "-OutputPath"))
        outside = Path(self.temp.name) / "forbidden-output"
        for script, option in wrappers:
            with self.subTest(script=script):
                command = ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                           "-File", str(lab / script), option, str(outside)]
                if script.startswith("rig/"):
                    command += ["-ArtistScene", str(self.repo / "deliberately-absent.blend")]
                result = subprocess.run(command, cwd=self.repo, capture_output=True, text=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("ProbeRoot must be a dedicated directory", result.stdout + result.stderr)
                self.assertFalse(outside.exists())

    def test_rig_resolver_rejects_nested_redirected_output_file(self):
        self.probe.mkdir(parents=True)
        original = Path(self.temp.name) / "artist.txt"
        original.write_text("preserve")
        os.link(original, self.probe / "warlock_hose.fbx")
        with patch.object(sys, "argv", self.rig_arguments(self.probe)):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                resolve_paths()
        self.assertEqual(original.read_text(), "preserve")

    def test_index_requires_one_existing_relative_file(self):
        self.index('"data/12/1234" = "hose.unit"\n')
        target = self.data / "data/12/1234"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"fixture")
        self.assertEqual(indexed_resources(self.repo, self.probe, self.data, ["hose.unit"]), [target])
        with self.assertRaises(ValueError):
            indexed_resources(self.repo, self.probe, self.data, ["missing.unit"])
        self.index('"data/12/1234" = "hose.unit"\n"data/12/1234" = "hose.unit"\n')
        with self.assertRaises(ValueError):
            indexed_resources(self.repo, self.probe, self.data, ["hose.unit"])

    def test_index_rejects_absolute_traversal_and_alternate_stream_paths(self):
        for name in ("../outside", "/tmp/outside", "C:/outside", "C:outside", "data\\outside",
                     "data/../outside", "data//outside", "data/./outside", "data/file:stream"):
            with self.subTest(name=name):
                self.index(f'"{name}" = "hose.unit"\n')
                with self.assertRaises(ValueError):
                    indexed_resources(self.repo, self.probe, self.data, ["hose.unit"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
