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

    def test_sample_outputs_keep_required_review_structure(self):
        samples = Path(__file__).resolve().parents[1] / "agents" / "pr-reviewer" / "samples"
        sample_outputs = sorted(samples.glob("*.md"))

        self.assertGreaterEqual(len(sample_outputs), 2)
        for sample_output in sample_outputs:
            rendered = sample_output.read_text(encoding="utf-8")
            self.assertIn("### Summary of changes", rendered)
            self.assertIn("### Identified risks", rendered)
            self.assertIn("### Improvement suggestions", rendered)
            self.assertRegex(rendered, r"### Confidence score: (Low|Medium|High)")
            self.assertIn("_Reviewed PR: https://github.com/", rendered)

    def test_action_commenter_reuses_cli_output(self):
        root = Path(__file__).resolve().parents[1]
        workflow = root / ".github" / "workflows" / "claude-review-comment.yml"
        contents = workflow.read_text(encoding="utf-8")

        self.assertIn("workflow_dispatch:", contents)
        self.assertIn("pull-requests: write", contents)
        self.assertIn("issues: write", contents)
        self.assertIn("python3 agents/pr-reviewer/claude_review.py --pr", contents)
        self.assertIn("workflow token can only comment on PRs in this repository", contents)
        self.assertIn("          import re\n          import sys", contents)
        self.assertIn('gh pr comment "$pr_number" --body-file review.md', contents)


if __name__ == "__main__":
    unittest.main()
