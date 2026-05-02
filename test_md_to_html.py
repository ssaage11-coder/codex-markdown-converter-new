import tempfile
import unittest
from pathlib import Path

from md_to_html import MarkdownConversionError, convert_markdown, main


class MarkdownToHtmlTests(unittest.TestCase):
    def test_convert_common_markdown_blocks(self) -> None:
        source = """# Hello

This is **bold** text and this is *italic* text.

Visit [OpenAI](https://openai.com).

- One
- Two

> Quote

```python
print("hello")
```
"""

        result = convert_markdown(source)

        self.assertIn("<h1>Hello</h1>", result)
        self.assertIn("<strong>bold</strong>", result)
        self.assertIn("<em>italic</em>", result)
        self.assertIn('<a href="https://openai.com">OpenAI</a>', result)
        self.assertIn("<ul>", result)
        self.assertIn("<li>One</li>", result)
        self.assertIn("<blockquote>", result)
        self.assertIn('<pre><code class="language-python">print("hello")\n</code></pre>', result)

    def test_raw_html_is_escaped(self) -> None:
        result = convert_markdown("<script>alert(1)</script>")

        self.assertNotIn("<script>", result)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", result)

    def test_table_conversion(self) -> None:
        source = """| Name | Value |
| --- | --- |
| A | **B** |
"""

        result = convert_markdown(source)

        self.assertIn("<table>", result)
        self.assertIn("<th>Name</th>", result)
        self.assertIn("<td><strong>B</strong></td>", result)

    def test_cli_writes_output_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            tmp_path = Path(directory)
            input_path = tmp_path / "input.md"
            output_path = tmp_path / "output.html"
            input_path.write_text("# Title\n", encoding="utf-8")

            exit_code = main([str(input_path), "-o", str(output_path)])

            self.assertEqual(exit_code, 0)
            self.assertEqual(output_path.read_text(encoding="utf-8"), "<h1>Title</h1>")

    def test_unclosed_code_block_raises_error(self) -> None:
        with self.assertRaises(MarkdownConversionError):
            convert_markdown("```python\nprint('missing close')\n")


if __name__ == "__main__":
    unittest.main()
