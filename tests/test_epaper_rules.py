import io
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

    def test_process_pdf_appends_group_branding_pdf(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'source.pdf')
            brand_path = os.path.join(tmpdir, 'pbk.pdf')
            output_path = os.path.join(tmpdir, 'output.pdf')

            source_writer = PdfWriter()
            source_writer.add_blank_page(width=200, height=300)
            source_writer.add_blank_page(width=200, height=300)
            with open(input_path, 'wb') as fh:
                source_writer.write(fh)

            brand_writer = PdfWriter()
            brand_writer.add_blank_page(width=200, height=300)
            with open(brand_path, 'wb') as fh:
                brand_writer.write(fh)

            original_branding = wm.EXTRA_LAST_PDF
            wm.EXTRA_LAST_PDF = brand_path
            try:
                wm.process_pdf(input_path, output_path)
            finally:
                wm.EXTRA_LAST_PDF = original_branding

            reader = PdfReader(output_path)
            self.assertEqual(len(reader.pages), 3)

    def test_mw_pdf_keeps_original_filename_and_generates_thumbnail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'TheNews Lahore 28August.pdf')
            output_path = os.path.join(tmpdir, 'processed.pdf')

            image = Image.new('RGB', (1200, 1800), 'white')
            image.save(input_path, format='PDF')

            import mw

            mw.process_pdf(input_path, output_path)

            self.assertTrue(os.path.exists(output_path))
            self.assertTrue(os.path.exists(output_path.replace('.pdf', '.thumb.jpg')))
            self.assertTrue(os.path.getsize(output_path.replace('.pdf', '.thumb.jpg')) > 0)

    def test_mw_clean_filename_removes_mw_marker(self):
        import mw

        self.assertEqual(mw.clean_filename('TheNews MW Lahore 28August.pdf'), 'TheNews Lahore 28August.pdf')
        self.assertEqual(mw.clean_filename('MW TheNews Lahore 28August.pdf'), 'TheNews Lahore 28August.pdf')
        self.assertEqual(mw.clean_filename('TheNews Lahore 28August.pdf'), 'TheNews Lahore 28August.pdf')

    def test_registry_includes_mashriq_akhbar_and_pakistan_today(self):
        import epaper_registry

        self.assertIn('mashriqakhbar', epaper_registry.NEWSPAPERS)
        self.assertIn('pakistantoday', epaper_registry.NEWSPAPERS)
        self.assertEqual(epaper_registry.NEWSPAPERS['mashriqakhbar']['available_after'], '10:00')
        self.assertEqual(epaper_registry.NEWSPAPERS['pakistantoday']['script'], 'pakistantoday.py')

    def test_registry_keeps_both_daily_pakistan_downloaders(self):
        import epaper_registry

        self.assertEqual(epaper_registry.NEWSPAPERS['dailypakistan']['script'], 'dailypakistan.py')
        self.assertEqual(
            epaper_registry.NEWSPAPERS['dailypakistanlate']['script'],
            'dailypakistan_late.py',
        )
        self.assertEqual(epaper_registry.NEWSPAPERS['dailypakistanlate']['available_after'], '11:00')

    def test_registry_includes_the_patriot_isb(self):
        import epaper_registry

        config = epaper_registry.NEWSPAPERS['thepatriot']
        self.assertEqual(config['display'], 'The Patriot ISB')
        self.assertEqual(config['script'], 'thepatriot.py')

    def test_registry_includes_lead_pakistan_at_eight_am(self):
        import epaper_registry

        config = epaper_registry.NEWSPAPERS['leadpakistan']
        self.assertEqual(config['script'], 'leadpakistan.py')
        self.assertEqual(config['available_after'], '08:00')

if __name__ == '__main__':
    unittest.main()
