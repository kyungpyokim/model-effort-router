import io
import os
from contextlib import redirect_stderr, redirect_stdout
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import install_core


class CoreInstallTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.source = self.root / "source" / "model_effort_router"
        self.source.mkdir(parents=True)
        (self.source / "__init__.py").write_text("")
        (self.source / "entrypoints.py").write_text("RUNTIME_API = 1\n")
        self.runtime = self.root / "shared runtime"

    def test_install_check_and_update_remove_stale_modules(self):
        self.assertTrue(install_core.check(self.source, self.runtime))
        install_core.install(self.source, self.runtime)
        self.assertEqual(install_core.check(self.source, self.runtime), [])
        (self.runtime / "model_effort_router" / "removed.py").write_text("old")
        (self.source / "entrypoints.py").write_text("RUNTIME_API = 2\n")
        self.assertTrue(install_core.check(self.source, self.runtime))
        install_core.install(self.source, self.runtime)
        self.assertEqual(install_core.check(self.source, self.runtime), [])
        self.assertFalse((self.runtime / "model_effort_router" / "removed.py").exists())

    def test_ignores_bytecode(self):
        (self.source / "__pycache__").mkdir()
        (self.source / "__pycache__" / "a.pyc").write_bytes(b"cache")
        (self.source / "a.pyc").write_bytes(b"cache")
        install_core.install(self.source, self.runtime)
        self.assertFalse(list((self.runtime / "model_effort_router").rglob("*.pyc")))
        self.assertEqual(install_core.check(self.source, self.runtime), [])

    def test_copy_failure_preserves_previous_install(self):
        install_core.install(self.source, self.runtime)
        with patch.object(install_core.shutil, "copytree", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                install_core.install(self.source, self.runtime)
        self.assertEqual(install_core.check(self.source, self.runtime), [])

    def test_activation_failure_restores_previous_install(self):
        install_core.install(self.source, self.runtime)
        (self.source / "entrypoints.py").write_text("RUNTIME_API = 2\n")
        rename = Path.rename

        def fail_activation(path, target):
            if path.parent.name.startswith(".mer-install-") and path.name == "model_effort_router":
                raise OSError("activation failed")
            return rename(path, target)

        with patch.object(Path, "rename", fail_activation):
            with self.assertRaisesRegex(OSError, "activation failed"):
                install_core.install(self.source, self.runtime)
        self.assertEqual((self.runtime / "model_effort_router" / "entrypoints.py").read_text(), "RUNTIME_API = 1\n")

    def test_rejects_overlapping_source_and_destination(self):
        for runtime in (self.source.parent, self.source / "nested", self.root):
            # The last target is an ancestor of a deliberately nested source.
            source = self.source if runtime != self.root else self.root / "model_effort_router" / "nested"
            source.mkdir(parents=True, exist_ok=True)
            with self.subTest(runtime=runtime), self.assertRaises(ValueError):
                install_core.install(source, runtime)
        self.assertTrue((self.source / "entrypoints.py").exists())

    def test_runtime_path_uses_absolute_override_or_xdg_default(self):
        self.assertEqual(
            install_core.runtime_path({"HOME": str(self.root)}), self.root / ".local/share/model-effort-router/runtime"
        )
        self.assertEqual(install_core.runtime_path({"MER_CORE_PATH": str(self.runtime)}), self.runtime)
        self.assertEqual(
            install_core.runtime_path({"XDG_DATA_HOME": str(self.root)}), self.root / "model-effort-router/runtime"
        )
        with self.assertRaises(ValueError):
            install_core.runtime_path({"MER_CORE_PATH": "relative"})
        self.assertEqual(
            install_core.runtime_path({"HOME": str(self.root), "XDG_DATA_HOME": "relative"}),
            self.root / ".local/share/model-effort-router/runtime",
        )

    def test_installer_cli_installs_and_checks_in_temporary_home(self):
        with patch.dict(os.environ, {"MER_CORE_PATH": str(self.runtime)}), redirect_stdout(io.StringIO()):
            self.assertEqual(install_core.main(["--check"]), 1)
            self.assertEqual(install_core.main([]), 0)
            self.assertEqual(install_core.main(["--check"]), 0)
        self.assertTrue((self.runtime / "model_effort_router" / "cli.py").exists())

    def test_invalid_path_cli_reports_error_without_creating_files(self):
        errors = io.StringIO()
        with patch.dict(os.environ, {"MER_CORE_PATH": "relative"}), redirect_stderr(errors):
            self.assertEqual(install_core.main([]), 2)
        self.assertIn("absolute directory", errors.getvalue())
        self.assertFalse(self.runtime.exists())

    def test_symlink_target_is_not_followed_or_replaced(self):
        self.runtime.mkdir()
        target = self.runtime / "model_effort_router"
        target.symlink_to(self.source, target_is_directory=True)
        with self.assertRaises(ValueError):
            install_core.install(self.source, self.runtime)
        self.assertTrue(target.is_symlink())
        self.assertTrue((self.source / "entrypoints.py").is_file())

    def test_check_rejects_symlinked_package_and_bootstrap_files(self):
        self.runtime.mkdir()
        target = self.runtime / "model_effort_router"
        target.symlink_to(self.source, target_is_directory=True)
        self.assertIn("symlink: model_effort_router", install_core.check(self.source, self.runtime))
        target.unlink()
        install_core.install(self.source, self.runtime)
        for name in ("__init__.py", "entrypoints.py"):
            path = target / name
            path.unlink()
            path.symlink_to(self.source / name)
            with self.subTest(name=name):
                self.assertIn(f"symlink: model_effort_router/{name}", install_core.check(self.source, self.runtime))
            path.unlink()
            path.write_text((self.source / name).read_text())

    def test_staging_mismatch_does_not_replace_previous_install(self):
        install_core.install(self.source, self.runtime)
        with patch.object(install_core, "check", return_value=["differs: entrypoints.py"]):
            with self.assertRaisesRegex(OSError, "staged core"):
                install_core.install(self.source, self.runtime)
        self.assertEqual(install_core.check(self.source, self.runtime), [])

    def test_failed_rollback_retains_backup_for_recovery(self):
        install_core.install(self.source, self.runtime)
        rename = Path.rename

        def fail_activation_and_rollback(path, target):
            if path.parent.name.startswith(".mer-install-"):
                raise OSError("rename blocked")
            return rename(path, target)

        with patch.object(Path, "rename", fail_activation_and_rollback):
            with self.assertRaisesRegex(OSError, "rename blocked"):
                install_core.install(self.source, self.runtime)
        backups = list(self.runtime.glob(".mer-install-*/previous/entrypoints.py"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), "RUNTIME_API = 1\n")
