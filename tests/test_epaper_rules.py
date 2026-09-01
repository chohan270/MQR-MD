import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import epaper_scheduler  # noqa: E402
import wm  # noqa: E402


class EpaperRulesTest(unittest.TestCase):
    def test_rejects_previous_day_dates_and_accepts_today(self):
        today = datetime.now().date()
        prev_day = today - timedelta(days=1)

        current_names = [
            f'Jang_{today.month}-{today.day}-{today.year}.pdf',
            f'Jang_{today.strftime("%Y-%m-%d")}.pdf',
        ]
        previous_names = [
            f'Jang_{prev_day.month}-{prev_day.day}-{prev_day.year}.pdf',
            f'Jang_{prev_day.strftime("%Y-%m-%d")}.pdf',
        ]

        for name in current_names:
            self.assertTrue(epaper_scheduler.has_current_date(name), f'{name} should be accepted')

        for name in previous_names:
            self.assertFalse(epaper_scheduler.has_current_date(name), f'{name} should be rejected')

    def test_process_pdf_keeps_original_page_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'source.pdf')
            output_path = os.path.join(tmpdir, 'output.pdf')

            writer = PdfWriter()
            writer.add_blank_page(width=200, height=300)
            writer.add_blank_page(width=200, height=300)
            with open(input_path, 'wb') as fh:
                writer.write(fh)

            wm.process_pdf(input_path, output_path)
            reader = PdfReader(output_path)

            self.assertEqual(len(reader.pages), 2)


if __name__ == '__main__':
    unittest.main()
