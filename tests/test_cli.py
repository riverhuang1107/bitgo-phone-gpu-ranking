import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from phone_gpu_rank.bitgo_runtime import (
    SEARCH_KEYWORDS,
    SUPPLEMENTAL_SEARCH_QUERIES,
    SearchResult,
    BitgoConfig,
    parse_antutu_rows,
    parse_model_text,
    write_search_audit,
)
from phone_gpu_rank.cli import main
from phone_gpu_rank.render import OUTPUT_BASENAME, render_html


class ConfigTests(unittest.TestCase):
    def test_missing_env_is_reported(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "Missing required environment variables"):
                BitgoConfig.from_env()


class ResponseTests(unittest.TestCase):
    def test_parse_bitgo_content_array(self) -> None:
        raw = json.dumps({"body": {"content": [{"type": "text", "text": "# Report"}]}})
        self.assertEqual(parse_model_text(raw), "# Report")


class RenderTests(unittest.TestCase):
    def test_render_html_contains_table(self) -> None:
        html = render_html("# T\n\n| GPU | Score |\n| --- | --- |\n| A | 1 |")
        self.assertIn("<table>", html)
        self.assertIn("<th>GPU</th>", html)
        self.assertIn("<td>A</td>", html)


class SearchAuditTests(unittest.TestCase):
    def test_search_audit_records_required_keywords(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "search-audit.json"
            results = [SearchResult(query=keyword, ok=True, results=[]) for keyword in [*SEARCH_KEYWORDS, *SUPPLEMENTAL_SEARCH_QUERIES]]
            write_search_audit(path, results)
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["searched_keywords"][: len(SEARCH_KEYWORDS)], SEARCH_KEYWORDS)
            self.assertTrue(payload["all_required_keywords_searched"])

    def test_parse_antutu_rows(self) -> None:
        html = """
        <tbody><tr><td>1</td><td>Red Magic 11 Pro</td><td>S-8 Elite Gen 5</td><td>| 16+512</td>
        <td>1,156,174</td><td>1,467,427</td><td>502,273</td><td>855,553</td><td>3,981,427</td></tr></tbody>
        """
        rows = parse_antutu_rows(html)
        self.assertEqual(rows[0]["device"], "Red Magic 11 Pro")
        self.assertEqual(rows[0]["gpu"], "1,467,427")


class CliTests(unittest.TestCase):
    def test_report_with_mock_writes_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            mock_file = tmp_path / "response.json"
            mock_file.write_text(json.dumps({"content": "# Mock"}), encoding="utf-8")
            code = main(["--output-dir", str(tmp_path / "out"), "report", "--format", "both", "--mock-response", str(mock_file)])
            self.assertEqual(code, 0)
            self.assertTrue((tmp_path / "out" / f"{OUTPUT_BASENAME}.md").exists())
            self.assertTrue((tmp_path / "out" / f"{OUTPUT_BASENAME}.html").exists())

    def test_mail_requires_html(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            code = main(["--output-dir", tmp, "mail", "--to", "a@example.com"])
            self.assertEqual(code, 2)

    def test_mail_generates_mime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            html_path = tmp_path / f"{OUTPUT_BASENAME}.html"
            html_path.write_text("<html><body>Report</body></html>", encoding="utf-8")
            code = main(["--output-dir", tmp, "mail", "--to", "a@example.com", "--subject", "GPU"])
            self.assertEqual(code, 0)
            eml = tmp_path / f"{OUTPUT_BASENAME}.eml"
            self.assertTrue(eml.exists())
            self.assertIn("text/html", eml.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
