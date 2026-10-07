from __future__ import annotations

import argparse
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path


_pool_processor = None


def _init_worker(cfg_kwargs: dict) -> None:
    global _pool_processor
    from tuzkaocr.config import Config
    from tuzkaocr.pipeline import PageProcessor
    _pool_processor = PageProcessor(Config(**cfg_kwargs))


def _process_one(args_tuple) -> tuple[str, float, str | None]:
    img_path, out_path, fmt = args_tuple
    t0 = time.time()
    try:
        _pool_processor.process_file(img_path, out_path=out_path, fmt=fmt)
        return str(img_path), time.time() - t0, None
    except Exception as exc:
        return str(img_path), time.time() - t0, str(exc)


def main() -> None:
    p = argparse.ArgumentParser(
        description="tuzkaocr — OCR pipeline for scanned page and document images",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", help="Image file or directory (with --batch)")
    p.add_argument("--out",      default=None,    help="Output file path (single image)")
    p.add_argument("--out-dir",  default="results", help="Output directory (batch mode)")
    p.add_argument("--format",   choices=["alto", "txt", "multi"], default="alto",
                   help="Output format: alto (ALTO XML), txt (plain text), or multi (both)")
    p.add_argument("--batch",    action="store_true", help="Process all images in a directory")
    p.add_argument("--workers",  type=int, default=2, help="Parallel page workers (batch)")

    p.add_argument("--domain",       choices=["default", "print", "kramarky", "handwritten", "kurrent"], default="default",
                   help="Preset model pair; --layout-model/--ocr-model override individual slots")
    p.add_argument("--layout-model", default=None,
                   help="Override layout model (bundled filename or path); default depends on --domain")
    p.add_argument("--ocr-model",    default=None,
                   help="Override OCR model (bundled filename or path); default depends on --domain")
    p.add_argument("--vocab",        default=None,
                   help="Override vocab (bundled filename or path); default: vocab.json")

    p.add_argument("--device",      default="cpu",
                   help="Compute device: cpu | cuda | auto")
    p.add_argument("--ocr-threads", type=int, default=4,
                   help="ONNX intra-op threads")
    p.add_argument("--line-workers", type=int, default=4,
                   help="Parallel line OCR threads per page")

    p.add_argument("--height-scale", type=float, default=1.0,
                   help="Multiply predicted line heights (use 1.5 if layout model underestimates)")
    p.add_argument("--no-adaptive", dest="adaptive", action="store_false",
                   help="Disable adaptive downsampling (use fixed DS3 layout)")
    p.set_defaults(adaptive=True)
    p.add_argument("--role-classifier", dest="role_classifier", action="store_true",
                   help="Tag each line with role (body/heading/header/footer/page_number) in ALTO TYPE attr")
    p.set_defaults(role_classifier=False)

    p.add_argument("--alto-profile", choices=["ndk", "basic"], default=None,
                   help="ALTO flavour: ndk (Czech NDK ingest profile) or basic (legacy)")
    p.add_argument("--alto-lang", default=None,
                   help="Language code for ALTO LANG attributes; detected from the text "
                        "when not given")
    p.add_argument("--alto-agency", default=None,
                   help="Institution running the OCR, written as processingAgency; "
                        "omitted when not set")
    p.add_argument("--alto-dpi", type=int, default=None,
                   help="Override the scan resolution used to estimate FONTSIZE; read from "
                        "the image when not given")
    p.add_argument("--alto-page-width-mm", type=float, default=None,
                   help="Physical width of the page in millimetres; the resolution is derived "
                        "from it when the image itself records none")
    p.add_argument("--source-identifier", default=None,
                   help="Identifier of the source image, written as fileIdentifier "
                        "(single image only)")
    p.add_argument("--physical-img-nr", type=int, default=None,
                   help="Sequential page number within the volume; taken from a trailing "
                        "number in the filename when not given (single image only)")
    p.add_argument("--ndk-warn", action="store_true",
                   help="Report NDK profile fields that could not be filled from the input "
                        "or the configuration")

    args = p.parse_args()
    if args.physical_img_nr is not None and args.physical_img_nr <= 0:
        p.error("--physical-img-nr must be a positive integer")
    if args.batch and (args.physical_img_nr is not None or args.source_identifier is not None):
        p.error("--physical-img-nr and --source-identifier apply to a single image, not --batch")

    from tuzkaocr.alto import physical_page_number
    from tuzkaocr.config import Config
    _base = Config()
    if args.domain == "kramarky":
        domain_layout = _base.kramarky_layout_model
        domain_ocr    = _base.kramarky_ocr_model
    elif args.domain == "handwritten":
        domain_layout = _base.handwritten_layout_model
        domain_ocr    = _base.handwritten_ocr_model
    elif args.domain == "kurrent":
        domain_layout = _base.kurrent_layout_model
        domain_ocr    = _base.kurrent_ocr_model
    else:
        domain_layout = _base.layout_model
        domain_ocr    = _base.ocr_model

    cfg_kwargs = dict(
        layout_model  = args.layout_model or domain_layout,
        ocr_model     = args.ocr_model    or domain_ocr,
        vocab         = args.vocab        or _base.vocab,
        device        = args.device,
        ocr_threads   = args.ocr_threads,
        line_workers  = args.line_workers,
        page_workers  = args.workers,
        height_scale  = args.height_scale,
        adaptive_downsample = args.adaptive,
        role_classifier = args.role_classifier,
        crop_endpoint_ext = (0.3 if args.domain in ("handwritten", "kurrent") else 0.0),
        column_split = args.domain in ("handwritten", "kurrent"),
        alto_profile = args.alto_profile or _base.alto_profile,
        alto_lang = args.alto_lang if args.alto_lang is not None else _base.alto_lang,
        alto_agency = args.alto_agency if args.alto_agency is not None else _base.alto_agency,
        alto_dpi = args.alto_dpi if args.alto_dpi is not None else _base.alto_dpi,
        alto_page_width_mm = (args.alto_page_width_mm if args.alto_page_width_mm is not None
                              else _base.alto_page_width_mm),
    )

    if (args.ndk_warn and cfg_kwargs["alto_profile"] == "ndk"
            and not cfg_kwargs["alto_agency"].strip()):
        print("note: processingAgency is omitted — set TUZKAOCR_ALTO_AGENCY or --alto-agency "
              "to name the institution running the OCR (the NDK profile requires it)",
              file=sys.stderr, flush=True)

    if not args.batch:
        from tuzkaocr.pipeline import PageProcessor

        cfg = Config(**cfg_kwargs)
        processor = PageProcessor(cfg)

        img_path = Path(args.input)
        suffix_map = {"alto": ".alto.xml", "txt": ".txt", "multi": ""}
        if args.format == "multi":
            out_path = Path(args.out) if args.out else img_path.with_suffix("")
        else:
            out_path = Path(args.out) if args.out else img_path.with_suffix(suffix_map[args.format])

        t0 = time.time()
        if (args.ndk_warn and args.physical_img_nr is None
                and physical_page_number(img_path.name) is None):
            print(f"note: no page number in {img_path.name!r}; PHYSICAL_IMG_NR falls back to "
                  "1 — pass --physical-img-nr to record the page's place in the volume",
                  file=sys.stderr, flush=True)

        result = processor.process_file(img_path, out_path=out_path, fmt=args.format,
                                        source_identifier=args.source_identifier,
                                        physical_img_nr=args.physical_img_nr)
        elapsed = time.time() - t0

        if args.format == "multi":
            n_lines = result["txt"].count("\n")
            n_strings = result["alto"].count("<String ")
            print(f"Done in {elapsed:.1f}s — {n_strings} words, {n_lines} lines → "
                  f"{out_path}.alto.xml, {out_path}.txt", flush=True)
        elif args.format == "txt":
            n_lines = result.count("\n")
            print(f"Done in {elapsed:.1f}s — {n_lines} lines → {out_path}", flush=True)
        else:
            n_strings = result.count("<String ")
            print(f"Done in {elapsed:.1f}s — {n_strings} words → {out_path}", flush=True)

    else:
        in_dir  = Path(args.input)
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

        exts = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
        images = sorted(p for p in in_dir.iterdir() if p.suffix.lower() in exts)
        if not images:
            print(f"No images found in {in_dir}", file=sys.stderr)
            sys.exit(1)

        unnumbered = ([p.name for p in images if physical_page_number(p.name) is None]
                      if args.ndk_warn else [])
        if unnumbered:
            print(f"note: {len(unnumbered)} of {len(images)} filenames carry no page number "
                  f"(e.g. {unnumbered[0]!r}); their PHYSICAL_IMG_NR falls back to 1",
                  file=sys.stderr, flush=True)

        print(f"Processing {len(images)} images with {args.workers} worker(s)...", flush=True)

        suffix_map = {"alto": ".alto.xml", "txt": ".txt", "multi": ""}
        suffix = suffix_map[args.format]
        tasks = [
            (str(img), str(out_dir / (img.stem + suffix)), args.format)
            for img in images
        ]

        t0 = time.time()
        done = 0
        errors = 0

        with ProcessPoolExecutor(
            max_workers=args.workers,
            initializer=_init_worker,
            initargs=(cfg_kwargs,),
        ) as pool:
            futures = {pool.submit(_process_one, t): t[0] for t in tasks}
            for future in as_completed(futures):
                img_path, elapsed, err = future.result()
                done += 1
                if err:
                    errors += 1
                    print(f"[{done:4d}/{len(images)}] ERROR {Path(img_path).name}: {err}",
                          flush=True)
                else:
                    eta = (time.time() - t0) / done * (len(images) - done)
                    print(f"[{done:4d}/{len(images)}] {Path(img_path).name} "
                          f"{elapsed:.1f}s  ETA {eta/60:.1f}m", flush=True)

        total = time.time() - t0
        print(f"\nDone: {done - errors}/{len(images)} OK, {errors} errors, "
              f"total {total:.1f}s ({total/max(1,len(images)):.1f}s/page)", flush=True)


if __name__ == "__main__":
    main()
