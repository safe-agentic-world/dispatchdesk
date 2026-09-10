"""Offline repository checks; no GitHub access or optional SDK required."""
from pathlib import Path
import re
import unittest
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]


class RepositoryTests(unittest.TestCase):
    def test_local_documentation_links_resolve(self):
        for required in ("README.md", "CONTRIBUTING.md", "VALIDATION.md", "LICENSE"):
            self.assertTrue((ROOT / required).is_file(), f"Missing {required}")
        paths = list(ROOT.glob("*.md")) + list((ROOT / ".github").rglob("*.md"))
        for path in paths:
            content = re.sub(r"(?ms)^```.*?^```[^\n]*", "", path.read_text(encoding="utf-8"))
            for target in re.findall(r"!?\[[^\]\n]*\]\(([^)\n]+)\)", content):
                parsed = urlsplit(target.strip().strip("<>"))
                if parsed.scheme or parsed.netloc or not parsed.path:
                    continue
                base = ROOT if parsed.path.startswith("/") else path.parent
                with self.subTest(file=path.name, target=target):
                    self.assertTrue((base / unquote(parsed.path.lstrip("/"))).exists(), target)

    def test_repository_identity_stays_consistent(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
        self.assertIn("git clone https://github.com/safe-agentic-world/dispatchdesk.git", readme)
        self.assertIn("cd dispatchdesk", readme)
        self.assertIn('Repository = "https://github.com/safe-agentic-world/dispatchdesk"', metadata)
        self.assertNotIn("nomos-customer-support-agent", readme)


if __name__ == "__main__":
    unittest.main()
