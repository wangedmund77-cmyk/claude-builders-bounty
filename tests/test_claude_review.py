import textwrap
import unittest
import importlib.util
import sys
from pathlib import Path


def load_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "agents" / "pr-reviewer" / "claude_review.py"
    spec = importlib.util.spec_from_file_location("claude_review", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


claude_review = load_module()


class ClaudeReviewTest(unittest.TestCase):
    def test_parses_and_categorizes_risks(self):
        diff = textwrap.dedent(
            """\
            diff --git a/app/auth.py b/app/auth.py
            index 1111111..2222222 100644
            --- a/app/auth.py
            +++ b/app/auth.py
            @@ -1,2 +1,3 @@
             def run(value):
            +    eval(value)
                 return True
            diff --git a/tests/test_auth.py b/tests/test_auth.py
            index 3333333..4444444 100644
            --- a/tests/test_auth.py
            +++ b/tests/test_auth.py
            @@ -0,0 +1,2 @@
            +def test_run():
            +    assert True
            """
        )

        analysis = claude_review.analyze_diff(diff)
        rendered = claude_review.render_markdown(analysis, pr_url="https://github.com/o/r/pull/1")

        self.assertEqual(len(analysis.files), 2)
        self.assertIn("Shell execution", "\n".join(analysis.risks))
        self.assertIn("security-sensitive", "\n".join(analysis.risks))
        self.assertIn("Confidence score: Medium", rendered)
        self.assertIn("https://github.com/o/r/pull/1", rendered)

    def test_pr_url_validation(self):
        self.assertEqual(
            claude_review.pr_to_diff_url("https://github.com/owner/repo/pull/123"),
            "https://github.com/owner/repo/pull/123.diff",
        )
        with self.assertRaises(ValueError):
            claude_review.pr_to_diff_url("https://example.com/not-a-pr")


if __name__ == "__main__":
    unittest.main()
