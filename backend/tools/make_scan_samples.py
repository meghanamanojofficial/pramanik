"""Generate photo/scan samples from the demo PDFs: perspective, rotation, blur, darkness, noise.
Run from backend/ after make_test_pdfs.py:   python tools/make_scan_samples.py

    scans/genuine_clean.jpg         flat scan of genuine.pdf                      -> VERIFIED
    scans/genuine_photographed.jpg  skewed phone photo on a dark table, uneven light -> VERIFIED
    scans/genuine_phone_rotated.jpg sideways pixels + EXIF orientation (phones do this) -> VERIFIED
    scans/tampered_amount.jpg       scan of edited_amount.pdf                     -> MISMATCH
    scans/unknown_number.jpg        scan of unknown_number.pdf                    -> SUSPICIOUS
    scans/revoked.jpg               scan of revoked.pdf                           -> SUSPICIOUS
    scans/forged_signature.jpg      scan of forged_signature.pdf                  -> MATCHES_RECORD_INTEGRITY_CONCERNS
    scans/genuine_blurry.jpg        out of focus                                  -> RESCAN
    scans/genuine_dark.jpg          under-exposed                                 -> RESCAN
    scans/unreadable_noise.jpg      sharp enough to pass the gate, but text is destroyed -> INCONCLUSIVE
    pdfs/scanned_genuine.pdf        genuine.pdf flattened to a picture (no text layer) -> VERIFIED
"""
import io
from pathlib import Path

import cv2
import numpy as np
import pymupdf as fitz
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
PDFS = ROOT.parent / "demo_docs" / "pdfs"
SCANS = ROOT.parent / "demo_docs" / "scans"
RNG = np.random.default_rng(7)  # fixed seed: the samples are the same every run


def render(pdf: Path, dpi: int = 200) -> np.ndarray:
    with fitz.open(str(pdf)) as doc:
        pix = doc[0].get_pixmap(dpi=dpi, alpha=False)
        return np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, 3).copy()


def save(img: np.ndarray, path: Path, quality: int = 92, exif_orientation: int | None = None) -> None:
    pil = Image.fromarray(img)
    kwargs = {"quality": quality}
    if exif_orientation:
        exif = Image.Exif()
        exif[0x0112] = exif_orientation
        kwargs["exif"] = exif
    pil.save(path, "JPEG", **kwargs)


def photographed(img: np.ndarray) -> np.ndarray:
    """Page on a dark surface, skewed, lit from one side, with sensor noise."""
    h, w = img.shape[:2]
    m = 120
    canvas = np.full((h + 2 * m, w + 2 * m, 3), 55, dtype=np.uint8)
    canvas[m:m + h, m:m + w] = img
    src = np.float32([[m, m], [m + w, m], [m, m + h], [m + w, m + h]])
    dst = np.float32([[m + 40, m + 55], [m + w - 25, m + 10], [m + 55, m + h - 35], [m + w - 10, m + h - 12]])
    out = cv2.warpPerspective(canvas, cv2.getPerspectiveTransform(src, dst), (canvas.shape[1], canvas.shape[0]),
                              borderValue=(50, 50, 50))
    ramp = np.linspace(1.0, 0.78, out.shape[1], dtype=np.float32)[None, :, None]  # light falls off to the right
    out = np.clip(out.astype(np.float32) * ramp + RNG.normal(0, 4, out.shape), 0, 255).astype(np.uint8)
    return out


def main() -> int:
    needed = [PDFS / n for n in ("genuine.pdf", "edited_amount.pdf", "unknown_number.pdf")]
    if not all(p.exists() for p in needed):
        print(f"Demo PDFs not found in {PDFS}. Run: python tools/make_test_pdfs.py")
        return 1
    SCANS.mkdir(parents=True, exist_ok=True)

    genuine = render(PDFS / "genuine.pdf")
    save(genuine, SCANS / "genuine_clean.jpg")
    save(photographed(genuine), SCANS / "genuine_photographed.jpg")
    save(np.ascontiguousarray(np.rot90(genuine, 1)), SCANS / "genuine_phone_rotated.jpg", exif_orientation=6)
    save(cv2.GaussianBlur(genuine, (0, 0), 14), SCANS / "genuine_blurry.jpg")
    save(np.clip(genuine * 0.15, 0, 255).astype(np.uint8), SCANS / "genuine_dark.jpg")

    # sharp (passes the blur test) but the text itself is wrecked by speckle noise
    speckle = genuine.copy()
    mask = RNG.random(speckle.shape[:2]) < 0.10
    speckle[mask] = RNG.choice([0, 255], size=int(mask.sum()))[:, None]
    save(speckle, SCANS / "unreadable_noise.jpg", quality=95)

    for src, dst in (("edited_amount", "tampered_amount"), ("unknown_number", "unknown_number"),
                     ("revoked", "revoked"), ("forged_signature", "forged_signature")):
        if (PDFS / f"{src}.pdf").exists():
            save(render(PDFS / f"{src}.pdf"), SCANS / f"{dst}.jpg")

    # an image-only PDF: what a flatbed "scan to PDF" produces (no text layer at all)
    with fitz.open() as out:
        page = out.new_page(width=595, height=842)
        buf = io.BytesIO()
        Image.fromarray(genuine).save(buf, "JPEG", quality=92)
        page.insert_image(page.rect, stream=buf.getvalue())
        out.save(PDFS / "scanned_genuine.pdf")

    print(f"Generated sample scans in {SCANS} and {PDFS / 'scanned_genuine.pdf'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
