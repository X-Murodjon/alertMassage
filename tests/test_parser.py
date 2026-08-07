from __future__ import annotations

import sys
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from public_monitor import (  # noqa: E402
    find_matches,
    parse_ai_analysis,
    parse_args,
    parse_public_page,
)


FIXTURE = """
<div class="tgme_widget_message" data-post="CorpInfo/123">
  <div class="tgme_widget_message_text">UZMK bo'yicha yillik hisobot e'lon qilindi</div>
  <a class="tgme_widget_message_document_wrap" href="https://t.me/CorpInfo/123?single">
    <div class="tgme_widget_message_document_title">report.pdf</div>
    <div class="tgme_widget_message_document_extra">PDF 2.4 MB</div>
  </a>
  <a class="tgme_widget_message_photo_wrap"
     style="background-image:url('https://cdn.example/report.jpg')"></a>
  <time datetime="2026-08-07T05:00:00+00:00"></time>
</div>
"""


class ParserTests(unittest.TestCase):
    def test_parse_public_post(self) -> None:
        posts = parse_public_page("CorpInfo", FIXTURE)
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0].message_id, 123)
        self.assertIn("hisobot", posts[0].text)
        self.assertIn("report.pdf", posts[0].file_names)
        self.assertEqual(len(posts[0].document_links), 1)
        self.assertEqual(posts[0].image_links[0], "https://cdn.example/report.jpg")

    def test_keyword_and_company_matches(self) -> None:
        result = find_matches(
            "UZMK yillik hisobot",
            ["hisobot", "dividend"],
            ["UZMK"],
        )
        self.assertEqual(result.keywords, ("hisobot",))
        self.assertEqual(result.companies, ("UZMK",))

    def test_once_argument(self) -> None:
        original = sys.argv
        try:
            sys.argv = ["public_monitor.py", "--once"]
            self.assertTrue(parse_args().once)
        finally:
            sys.argv = original

    def test_parse_ai_analysis(self) -> None:
        result = parse_ai_analysis(
            """```json
            {
              "relevant": true,
              "importance": 87,
              "sentiment": "Ijobiy",
              "company_or_code": "UZMK",
              "event": "Yillik hisobot",
              "summary": "Daromad oshgan.",
              "market_impact": "Ijobiy ta’sir qilishi mumkin.",
              "risks": "Pul oqimini tekshirish kerak."
            }
            ```"""
        )
        self.assertTrue(result.relevant)
        self.assertEqual(result.importance, 87)
        self.assertEqual(result.company_or_code, "UZMK")

    def test_digest_argument(self) -> None:
        original = sys.argv
        try:
            sys.argv = ["public_monitor.py", "--digest-days", "3"]
            self.assertEqual(parse_args().digest_days, 3)
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
