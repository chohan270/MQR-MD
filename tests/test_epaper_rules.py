import io
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pypdfium2 as pdfium
from PIL import Image
from pypdf import PdfReader, PdfWriter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))

import epaper_scheduler  # noqa: E402
import wm  # noqa: E402


class EpaperRulesTest(unittest.TestCase):
    def test_mw_removes_brand_strip_text_at_different_positions_and_colors(self):
        import mw

        pages = []
        expected_x = [42, 137]
        for x, y, font_size, color in [
            (42, 58, 10, (1, 0, 0)),
            (137, 215, 18, (0, 0, 1)),
        ]:
            source = io.BytesIO()
            from reportlab.pdfgen import canvas

            pdf = canvas.Canvas(source, pagesize=(400, 500))
            pdf.setFillColorRGB(*color)
            pdf.setFont('Helvetica-Bold', font_size)
            pdf.drawString(x, y, mw.BOTTOM_WATERMARK_TEXT)
            pdf.save()
            source.seek(0)
            pages.append(PdfReader(source).pages[0])

        boxes = [mw.find_watermark_boxes(page) for page in pages]
        self.assertEqual(len(boxes[0]), 1)
        self.assertEqual(len(boxes[1]), 1)
        self.assertAlmostEqual(boxes[0][0][0], expected_x[0], delta=2)
        self.assertAlmostEqual(boxes[1][0][0], expected_x[1], delta=2)
        self.assertFalse(mw.is_promo_page(pages[0]))

        mw.remove_bottom_watermark(pages)
        writer = PdfWriter()
        for page in pages:
            writer.add_page(page)
        output = io.BytesIO()
        writer.write(output)

        document = pdfium.PdfDocument(output.getvalue())
        try:
            for index, (left, bottom, right, top) in enumerate(box[0] for box in boxes):
                pixmap = document[index].render(scale=2)
                image = pixmap.to_pil().convert('RGB')
                sample_x = round((left + right) * pixmap.width / 2 / 400)
                sample_y = round((500 - (bottom + top) / 2) * pixmap.height / 500)
                red, green, blue = image.getpixel((sample_x, sample_y))
                self.assertGreaterEqual(red, 245)
                self.assertGreaterEqual(green, 245)
                self.assertGreaterEqual(blue, 245)
        finally:
            document.close()

    def test_front_watermark_preserves_original_page_content(self):
        source = io.BytesIO()
        from reportlab.pdfgen import canvas

        pdf = canvas.Canvas(source, pagesize=(200, 300))
        pdf.drawString(20, 40, 'Original page content')
        pdf.save()
        source.seek(0)

        reader = PdfReader(source)
        settings = (wm.WATERMARK_PNG, 25, 0.1, 'top-right', 100)
        with patch.object(wm, 'pick_watermark_settings', return_value=settings):
            watermarked_page, _ = wm.build_watermarked_front_page(reader)

        self.assertIn('Original page content', watermarked_page.extract_text())
        self.assertEqual(float(watermarked_page.mediabox.width), 200)
        self.assertEqual(float(watermarked_page.mediabox.height), 300)
        self.assertTrue(watermarked_page.images)

    def test_mw_front_watermark_uses_shared_page_overlay(self):
        import mw

        page = PdfWriter().add_blank_page(width=200, height=300)
        with patch.object(wm, 'build_watermarked_front_page_for_page', return_value=(page, Image.new('RGB', (1, 1)))) as overlay:
            result, preview = mw.build_front_watermark(page)

        overlay.assert_called_once_with(page)
        self.assertIs(result, page)
        self.assertEqual(preview.size, (1, 1))

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

    def test_khabrain_requires_more_than_one_page(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            one_page_path = os.path.join(tmpdir, 'khabrain-one-page.pdf')
            multi_page_path = os.path.join(tmpdir, 'khabrain-multi-page.pdf')

            one_page = PdfWriter()
            one_page.add_blank_page(width=200, height=300)
            with open(one_page_path, 'wb') as fh:
                one_page.write(fh)

            multi_page = PdfWriter()
            multi_page.add_blank_page(width=200, height=300)
            multi_page.add_blank_page(width=200, height=300)
            with open(multi_page_path, 'wb') as fh:
                multi_page.write(fh)

            self.assertFalse(epaper_scheduler.has_multiple_pdf_pages(one_page_path))
            self.assertTrue(epaper_scheduler.has_multiple_pdf_pages(multi_page_path))

    def test_process_pdf_keeps_original_page_count(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'source.pdf')
            output_path = os.path.join(tmpdir, 'output.pdf')

            writer = PdfWriter()
            writer.add_blank_page(width=200, height=300)
            writer.add_blank_page(width=200, height=300)
            with open(input_path, 'wb') as fh:
                writer.write(fh)

            original_branding = wm.EXTRA_LAST_PDF
            wm.EXTRA_LAST_PDF = ""
            try:
                wm.process_pdf(input_path, output_path)
            finally:
                wm.EXTRA_LAST_PDF = original_branding
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

    def test_mw_cleans_newspaper_pages_but_leaves_appended_branding_page_untouched(self):
        import mw

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'source.pdf')
            brand_path = os.path.join(tmpdir, 'pbk.pdf')
            output_path = os.path.join(tmpdir, 'output.pdf')
            phrase = mw.BOTTOM_WATERMARK_TEXT

            source_writer = PdfWriter()
            for x, y in [(35, 35), (90, 90), (145, 145)]:
                source = io.BytesIO()
                from reportlab.pdfgen import canvas

                pdf = canvas.Canvas(source, pagesize=(300, 400))
                pdf.drawString(x, y, phrase)
                pdf.save()
                source.seek(0)
                source_writer.add_page(PdfReader(source).pages[0])
            with open(input_path, 'wb') as source_file:
                source_writer.write(source_file)

            brand_source = io.BytesIO()
            from reportlab.pdfgen import canvas

            pdf = canvas.Canvas(brand_source, pagesize=(300, 400))
            pdf.drawString(35, 35, phrase)
            pdf.save()
            brand_source.seek(0)
            brand_writer = PdfWriter()
            brand_writer.add_page(PdfReader(brand_source).pages[0])
            with open(brand_path, 'wb') as brand_file:
                brand_writer.write(brand_file)

            original_branding = wm.EXTRA_LAST_PDF
            wm.EXTRA_LAST_PDF = brand_path
            try:
                mw.process_pdf(input_path, output_path)
            finally:
                wm.EXTRA_LAST_PDF = original_branding

            result = PdfReader(output_path)
            self.assertEqual(len(result.pages), 4)
            branding_boxes = mw.find_watermark_boxes(result.pages[-1])
            self.assertEqual(len(branding_boxes), 1)
            self.assertAlmostEqual(branding_boxes[0][0], 35, delta=2)

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

    def test_daily_ausaf_runs_configured_editions_after_publication_time(self):
        import epaper_registry

        config = epaper_registry.NEWSPAPERS['dailyausaf']
        self.assertEqual(config['available_after'], '11:30')
        self.assertEqual(config['extra_args'], [
            '--editions', 'Islamabad', 'Lahore', 'Peshawar', 'Gilgit_Baltistan',
            'London', 'Muzafarabad', 'Karachi',
        ])

if __name__ == '__main__':
    unittest.main()
