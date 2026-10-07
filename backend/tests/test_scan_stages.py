"""Photo/scan stages: quality gate, parsing, OCR-tolerance. (Whole-image OCR is covered by run_acceptance.py.)"""
import io
import unittest

import cv2
import numpy as np
from PIL import Image

from support import DOC  # noqa: F401  (sets import paths)

from app.scan.stages import ocr, parse, quality, rectify


def page(width=900, height=1200, paper=250, ink=10, text=True, noise=0.0):
    img = np.full((height, width, 3), paper, np.uint8)
    if text:
        for i, t in enumerate(["STATE REVENUE DEPARTMENT", "INCOME CERTIFICATE", "Certificate No: INC-0000-0001",
                               "Name: Sample Holder", "Issue Date: 2026-01-01", "Annual income: 100000"]):
            cv2.putText(img, t, (60, 120 + i * 70), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (ink,) * 3, 2)
    return img


def jpeg(img):
    buf = io.BytesIO()
    Image.fromarray(img).save(buf, "JPEG", quality=92)
    return buf.getvalue()


def fails(img):
    return {s.name for s in quality.assess(img) if s.severity.value == "fail"}


class QualityTests(unittest.TestCase):
    def test_good_page_passes(self):
        self.assertEqual(fails(page()), set())

    def test_white_paper_is_not_glare(self):
        """Regression: mean brightness of a clean page is ~250; it was once rejected as 'glare'."""
        img = page(paper=255)
        self.assertGreater(float(img.mean()), 240)
        self.assertEqual(fails(img), set())

    def test_blur_dark_washed_out_small(self):
        self.assertEqual(fails(cv2.GaussianBlur(page(), (0, 0), 14)), {"quality_blur"})
        self.assertEqual(fails(page(paper=35, ink=0)), {"quality_dark"})  # dark only; not also "blurry"
        self.assertTrue(fails(page(paper=252, ink=215)))  # faint ink: unreadable, whichever rule names it
        hotspot = page(paper=200)
        hotspot[100:700, 100:800] = 255                   # flash reflection wiping out part of the page
        self.assertEqual(fails(hotspot), {"quality_glare"})
        self.assertEqual(fails(page(width=300, height=300)), {"quality_low_resolution"})

    def test_blank_image_is_rejected(self):
        self.assertNotEqual(fails(np.full((900, 900, 3), 250, np.uint8)), set())

    def test_corrupt_and_oversize_files(self):
        sig, img = quality.check_quality(b"\xff\xd8\xff not really a jpeg")
        self.assertEqual((img, sig[0].name), (None, "quality_invalid_image"))

    def test_huge_photos_are_shrunk_on_load_and_small_ones_are_left_alone(self):
        big = np.full((4200, 3000, 3), 250, np.uint8)       # about 12.6 MP, like a phone photo
        cv2.putText(big, "INCOME CERTIFICATE", (200, 400), cv2.FONT_HERSHEY_SIMPLEX, 3, (10, 10, 10), 6)
        loaded, problem = quality.load_image(jpeg(big))
        self.assertIsNone(problem)
        self.assertLessEqual(max(loaded.shape[:2]), 3000)
        self.assertAlmostEqual(loaded.shape[0] / loaded.shape[1], 4200 / 3000, delta=0.02)   # proportions kept
        small, _ = quality.load_image(jpeg(page()))
        self.assertEqual(small.shape[:2], (1200, 900))

    def test_exif_rotation_is_applied(self):
        up = page(width=700, height=1000)
        sideways = np.ascontiguousarray(np.rot90(up, 1))
        exif = Image.Exif()
        exif[0x0112] = 6
        buf = io.BytesIO()
        Image.fromarray(sideways).save(buf, "JPEG", exif=exif)
        loaded, problem = quality.load_image(buf.getvalue())
        self.assertIsNone(problem)
        self.assertEqual(loaded.shape[:2], (1000, 700))


class RectifyTests(unittest.TestCase):
    def test_skewed_page_is_straightened_and_plain_image_falls_back(self):
        canvas = np.full((1200, 1200, 3), 50, np.uint8)
        cv2.fillPoly(canvas, [np.array([[200, 200], [1000, 250], [950, 1050], [150, 980]], np.int32)], (240, 240, 240))
        warped, sig = rectify.rectify_page(canvas)
        self.assertEqual(sig[0].name, "rectify_success")
        self.assertLess(warped.shape[0], 1200)
        flat, sig = rectify.rectify_page(np.full((800, 800, 3), 200, np.uint8))
        self.assertEqual((sig[0].name, flat.shape), ("rectify_fallback", (800, 800, 3)))


def lines(*texts, conf=95.0):
    out = []
    for t in texts:
        words, pos = [], 0
        for w in t.split(" "):
            words.append(ocr.Word(w, conf, pos, pos + len(w)))
            pos += len(w) + 1
        out.append(ocr.Line(t, words))
    return ocr.OcrPass("test", out, conf)


class ParseTests(unittest.TestCase):
    def read(self, *texts, conf=95.0):
        return {k: v.value for k, v in parse.read_fields(DOC, lines(*texts, conf=conf)).items()}

    def test_clean_text(self):
        got = self.read("Certificate No: INC-0000-0001", "Name: Sample Holder", "Issue Date: 2026-01-01", "Annual income: 100000")
        self.assertEqual(got, {"certificate_number": "INC-0000-0001", "holder_name": "Sample Holder",
                               "issue_date": "2026-01-01", "income_amount": "100000"})

    def test_ocr_digit_confusions_are_repaired_in_digit_fields_only(self):
        got = self.read("Certificate No: INC-OOOO-OOOI", "Name: Olivia Hill", "Issue Date: 2O26-O1-O1", "Annual income: 1,OO,OOO")
        self.assertEqual(got["certificate_number"], "INC-0000-0001")
        self.assertEqual(got["issue_date"], "2026-01-01")
        self.assertEqual(got["income_amount"], "100000")
        self.assertEqual(got["holder_name"], "Olivia Hill")  # a name is never 'repaired'

    def test_repair_runs_before_matching_so_a_value_is_never_truncated(self):
        """Regression: matching the raw text first would have read '1OOOOO' as just '1'."""
        self.assertEqual(self.read("Annual income: 1OOOOO")["income_amount"], "100000")

    def test_label_spacing_case_and_missing_separator(self):
        got = self.read("certificate  no INC-0000-0001", "NAME;  Sample Holder")
        self.assertEqual((got["certificate_number"], got["holder_name"]), ("INC-0000-0001", "Sample Holder"))

    def test_number_found_without_its_label(self):
        self.assertEqual(self.read("Cert. no 1 INC-0000-0001")["certificate_number"], "INC-0000-0001")

    def test_confidence_is_that_of_the_value_words_only(self):
        p = lines("Name: Sample Holder")
        p.lines[0].words[0].conf = 5.0  # the label was misread; the value is fine
        self.assertAlmostEqual(parse.read_fields(DOC, p)["holder_name"].conf, 95.0)

    def test_doc_type_detection_tolerates_ocr_errors_and_uses_the_qr_as_a_fallback(self):
        self.assertEqual(parse.detect_doc_type("STATE REVENUE DEPARTMENT\nINCOME CERTIFICAT", None)["id"], "income_certificate")
        self.assertEqual(parse.detect_doc_type("smudged", "INC-2026-0412")["id"], "income_certificate")
        self.assertIsNone(parse.detect_doc_type("Some other letter", None))


class ReconcileTests(unittest.TestCase):
    def reconcile(self, *passes):
        return parse.reconcile(DOC, [{k: parse.FieldRead(*v) for k, v in p.items()} for p in passes])

    def full(self, **over):
        base = {"certificate_number": ("INC-0000-0001", 90), "holder_name": ("Sample Holder", 90),
                "issue_date": ("2026-01-01", 90), "income_amount": ("100000", 90)}
        base.update(over)
        return base

    def test_confident_agreement(self):
        values, confs, problems = self.reconcile(self.full())
        self.assertEqual((problems, values["income_amount"]), ({}, "100000"))

    def test_missing_low_and_inconsistent_are_reported_never_guessed(self):
        _, _, problems = self.reconcile({k: v for k, v in self.full().items() if k != "income_amount"})
        self.assertEqual(problems, {"income_amount": "missing"})
        _, _, problems = self.reconcile(self.full(income_amount=("100000", 40)))
        self.assertEqual(problems, {"income_amount": "low"})
        _, _, problems = self.reconcile(self.full(), self.full(income_amount=("100800", 88)))
        self.assertEqual(problems, {"income_amount": "inconsistent"})

    def test_a_confident_pass_beats_a_shaky_one(self):
        values, _, problems = self.reconcile(self.full(income_amount=("1008", 30)), self.full())
        self.assertEqual((problems, values["income_amount"]), ({}, "100000"))

    def test_names_that_differ_only_in_case_or_order_agree(self):
        _, _, problems = self.reconcile(self.full(), self.full(holder_name=("HOLDER, sample", 90)))
        self.assertEqual(problems, {})


if __name__ == "__main__":
    unittest.main()
