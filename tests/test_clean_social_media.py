import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CLEANER = PROJECT_ROOT / "scripts" / "clean_social_media.py"


class SocialMediaCleanerTests(unittest.TestCase):
    def test_removes_known_vector_watermark_and_reports_its_type(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "input.pdf"
            output_path = Path(temp_dir) / "cleaned.pdf"
            document = canvas.Canvas(str(input_path))
            document.drawString(50, 500, "Social Media Pakistan 0342-4938217")
            document.drawString(50, 450, "Newspaper content remains")
            document.save()

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLEANER),
                    str(input_path),
                    str(output_path),
                    "--strict",
                    "--skip-reference-images",
                ],
                cwd=PROJECT_ROOT / "scripts",
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            marker = next(
                line for line in result.stdout.splitlines()
                if line.startswith("CLEAN_SOCIAL_MEDIA_RESULT:")
            )
            report = json.loads(marker.split(":", 1)[1])
            self.assertEqual(report["status"], "cleaned")
            self.assertIn("Phone-number watermark", report["watermarkTypes"])
            self.assertTrue(output_path.is_file())

    def test_strict_mode_blocks_an_image_only_pdf_when_no_page_can_be_verified(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            input_path = Path(temp_dir) / "scanned.pdf"
            output_path = Path(temp_dir) / "cleaned.pdf"
            image = Image.new("RGB", (500, 700), "white")
            ImageDraw.Draw(image).text((40, 80), "Social Media Pakistan", fill="black")
            image_buffer = io.BytesIO()
            image.save(image_buffer, format="PNG")
            image_buffer.seek(0)
            document = canvas.Canvas(str(input_path))
            document.drawImage(ImageReader(image_buffer), 0, 0, width=500, height=700)
            document.save()

            result = subprocess.run(
                [
                    sys.executable,
                    str(CLEANER),
                    str(input_path),
                    str(output_path),
                    "--strict",
                    "--skip-reference-images",
                ],
                cwd=PROJECT_ROOT / "scripts",
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 4, result.stderr + result.stdout)
            marker = next(
                line for line in result.stdout.splitlines()
                if line.startswith("CLEAN_SOCIAL_MEDIA_RESULT:")
            )
            report = json.loads(marker.split(":", 1)[1])
            self.assertEqual(report["status"], "failed")
            self.assertFalse(output_path.exists())


if __name__ == "__main__":
    unittest.main()
