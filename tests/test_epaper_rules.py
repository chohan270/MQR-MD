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
    def test_mw_skips_pages_with_full_skip_reference_image_fingerprint(self):
        import mw

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'reference.pdf')
            output_path = os.path.join(tmpdir, 'must-not-exist.pdf')
            reference_image = Image.new('RGB', (320, 100), 'white')
            for x in range(320):
                reference_image.putpixel((x, 25), (x % 256, (x * 3) % 256, (x * 7) % 256))
            reference_image.save(input_path, format='PDF')

            page = PdfReader(input_path).pages[0]
            fingerprint = mw.image_difference_hash(page.images[0].image)
            with patch.object(mw, 'REFERENCE_SKIP_IMAGE_HASHES', (fingerprint,)):
                self.assertTrue(mw.has_reference_ad_image(page))
                self.assertIsNone(mw.process_pdf(input_path, output_path, skip_reference_images=True))
                with patch.object(mw, 'find_front_page_cover_boxes', return_value=([], (0, 0))):
                    self.assertIsNotNone(
                        mw.process_pdf(input_path, output_path, skip_reference_images=False)
                    )

            self.assertTrue(os.path.exists(output_path))

    def test_mw_covers_a_matched_front_page_reference_photo_and_keeps_processing(self):
        import mw
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'cover-reference.pdf')
            output_path = os.path.join(tmpdir, 'processed.pdf')
            template_path = str(mw._COVER_TEMPLATE_DIR / 'reference-01.jpg')
            image_width = 300
            with Image.open(template_path) as template:
                image_height = image_width * template.height / template.width

            source = io.BytesIO()
            pdf = canvas.Canvas(source, pagesize=(600, 800))
            pdf.setFont('Helvetica-Bold', 20)
            pdf.drawString(30, 760, 'NEWSPAPER FRONT PAGE')
            pdf.drawImage(
                ImageReader(template_path),
                150,
                250,
                width=image_width,
                height=image_height,
            )
            pdf.save()
            source.seek(0)
            with open(input_path, 'wb') as input_file:
                input_file.write(source.getvalue())

            page = PdfReader(input_path).pages[0]
            boxes, rendered_size = mw.find_front_page_cover_boxes(page)
            self.assertEqual(len(boxes), 1)
            left, top, right, bottom = boxes[0]
            self.assertGreater(right - left, 0)
            self.assertGreater(bottom - top, 0)

            with patch.object(mw.wm, 'build_watermarked_front_page_for_page', return_value=(None, None)):
                result = mw.process_pdf(input_path, output_path, skip_reference_images=True)
            self.assertEqual(result, output_path)

            document = pdfium.PdfDocument(output_path)
            try:
                pixmap = document[0].render(scale=1.5)
                image = pixmap.to_pil().convert('RGB')
                center_x = round((left + right) / 2 * image.width / rendered_size[0])
                center_y = round((top + bottom) / 2 * image.height / rendered_size[1])
                self.assertGreaterEqual(min(image.getpixel((center_x, center_y))), 245)
                self.assertTrue(os.path.exists(output_path))
            finally:
                document.close()

    def test_all_five_reference_photos_are_cover_images_not_full_pdf_skip_images(self):
        import mw
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        for index, template_path in enumerate(sorted(mw._COVER_TEMPLATE_DIR.glob('reference-*.jpg'))):
            with self.subTest(reference=template_path.name):
                source = io.BytesIO()
                pdf = canvas.Canvas(source, pagesize=(600, 800))
                pdf.drawImage(ImageReader(str(template_path)), 50, 100, width=120, height=100)
                pdf.save()
                source.seek(0)
                page = PdfReader(source).pages[0]
                fingerprint = mw.image_difference_hash(page.images[0].image)

                self.assertTrue(mw._matches_reference_hash(
                    fingerprint,
                    (mw.FRONT_PAGE_COVER_IMAGE_HASHES[index],),
                ))
                self.assertFalse(mw.has_reference_ad_image(page))
                box = mw._find_embedded_cover_boxes(page)[0]
                for actual, expected in zip(box, (50, 100, 170, 200)):
                    self.assertAlmostEqual(actual, expected, delta=1)

    def test_mw_locates_a_reference_photo_inside_a_flattened_page_scan(self):
        import mw

        template = mw._COVER_TEMPLATES[0]
        page_image = Image.new('RGB', (300, 400), 'white')
        page_image.paste(template.resize((120, 83)), (50, 70))

        box = mw._candidate_cover_matches(page_image, template)

        self.assertIsNotNone(box)
        left, top, right, bottom = box
        self.assertAlmostEqual(left, 50, delta=10)
        self.assertAlmostEqual(top, 70, delta=10)
        self.assertAlmostEqual(right, 170, delta=10)
        self.assertAlmostEqual(bottom, 153, delta=10)

    def test_mw_skips_a_flattened_front_page_containing_the_pbk_news_logo(self):
        import mw
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'pbk-logo-front-page.pdf')
            output_path = os.path.join(tmpdir, 'must-skip.pdf')
            scan = Image.new('RGB', (300, 400), 'white')
            logo = mw._SKIP_REFERENCE_TEMPLATES[1].resize((180, 34))
            scan.paste(logo, (60, 50))
            scan_buffer = io.BytesIO()
            scan.save(scan_buffer, format='PNG')
            scan_buffer.seek(0)

            source = io.BytesIO()
            pdf = canvas.Canvas(source, pagesize=(600, 800))
            pdf.drawImage(ImageReader(scan_buffer), 0, 0, width=600, height=800)
            pdf.save()
            source.seek(0)
            with open(input_path, 'wb') as input_file:
                input_file.write(source.getvalue())

            self.assertTrue(mw.contains_reference_ad(input_path))
            self.assertIsNone(mw.process_pdf(input_path, output_path, skip_reference_images=True))
            self.assertFalse(os.path.exists(output_path))

    def test_mw_skips_a_flattened_front_page_containing_the_addtext_reference(self):
        import mw
        from reportlab.lib.utils import ImageReader
        from reportlab.pdfgen import canvas

        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, 'addtext-front-page.pdf')
            output_path = os.path.join(tmpdir, 'must-skip.pdf')
            scan = Image.new('RGB', (300, 400), 'white')
            reference = mw._SKIP_REFERENCE_TEMPLATES[0].resize((200, 26))
            scan.paste(reference, (50, 60))
            scan_buffer = io.BytesIO()
            scan.save(scan_buffer, format='PNG')
            scan_buffer.seek(0)

            source = io.BytesIO()
            pdf = canvas.Canvas(source, pagesize=(600, 800))
            pdf.drawImage(ImageReader(scan_buffer), 0, 0, width=600, height=800)
            pdf.save()
            source.seek(0)
            with open(input_path, 'wb') as input_file:
                input_file.write(source.getvalue())

            self.assertTrue(mw.contains_reference_ad(input_path))
            self.assertIsNone(mw.process_pdf(input_path, output_path, skip_reference_images=True))
            self.assertFalse(os.path.exists(output_path))

    def test_mw_clean_filename_moves_day_first_date_to_end(self):
        import mw

        self.assertEqual(mw.clean_filename('7 Oct 92 News Lahore.pdf'), '92 News Lahore 7Oct.pdf')
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
