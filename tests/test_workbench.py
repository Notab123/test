import json
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import workbench


class ScopeTests(unittest.TestCase):
    def test_only_exact_owned_deployment_hosts(self):
        for host in (
            "vercel.app", "vercel.com", "v0.app", "*.vercel.live",
            "a.vercel.app.evil.test", "https://a.vercel.app", "a.vercel.app/path",
            "a.vercel.app:443", "A.vercel.app", "a..vercel.app", "-a.vercel.app",
        ):
            with self.subTest(host=host), self.assertRaises(ValueError):
                workbench.validate_owned_host(host)

    def test_scope_anchors_only_explicit_host(self):
        scope = workbench.build_scope(["my-project.vercel.app", "my-project.vercel.app"])
        includes = scope["target"]["scope"]["include"]
        self.assertEqual(len(includes), 2)
        self.assertEqual(scope["target"]["scope"]["exclude"], [])
        self.assertEqual({item["host"] for item in includes}, {r"^my\-project\.vercel\.app$"})
        self.assertEqual({item["port"] for item in includes}, {"^80$", "^443$"})
        with self.assertRaises(ValueError):
            workbench.build_scope([])

    def test_supplied_scope_is_reference_only(self):
        snapshot = json.loads((ROOT / "references" / "attached-scope.json").read_text())
        self.assertEqual(len(snapshot["target"]["scope"]["include"]), 12)
        self.assertEqual(len(snapshot["target"]["scope"]["exclude"]), 2)
        self.assertTrue(all(set(item) == {"enabled", "file", "host", "port", "protocol"}
                            for group in ("include", "exclude")
                            for item in snapshot["target"]["scope"][group]))


class ScanTests(unittest.TestCase):
    def setUp(self):
        workbench.init_workspace()
        self.temp = tempfile.TemporaryDirectory(dir=workbench.SOURCES)
        self.source = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_scan_only_local_source_no_symlink_or_vendor(self):
        (self.source / "index.ts").write_text("const session = getSession();\nfetch(url);\n")
        (self.source / "node_modules").mkdir()
        (self.source / "node_modules" / "ignored.ts").write_text("fetch(url)")
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "private.ts").write_text("fetch(secret)")
            (self.source / "linked.ts").symlink_to(Path(outside) / "private.ts")
            matches = workbench.scan_source(self.source)
        self.assertEqual(matches, [("index.ts", 1, "auth/session"), ("index.ts", 2, "outbound-request")])

    def test_reject_external_source(self):
        with tempfile.TemporaryDirectory() as outside:
            with self.assertRaises(ValueError):
                workbench.scan_source(outside)


if __name__ == "__main__":
    unittest.main()
