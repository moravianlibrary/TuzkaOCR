from __future__ import annotations

import argparse
import dataclasses
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


def _process_one(args_tuple) -> tuple[str, float, str | None, dict | None]:
    img_path, out_path, fmt = args_tuple
    t0 = time.time()
    try:
        _, metadata = _pool_processor.process_file(
            img_path, out_path=out_path, fmt=fmt, with_meta=True,
        )
        return str(img_path), time.time() - t0, None, metadata
    except Exception as exc:
        return str(img_path), time.time() - t0, str(exc), None


def _orientation_summary(metadata: dict) -> str:
    confidence = metadata.get("orientation_confidence")
    confidence_text = "n/a" if confidence is None else f"{confidence:.3f}"
    recheck_text = " recheck" if metadata.get("orientation_recheck") else ""
    return (f"orientation={metadata['orientation_angle']}° "
            f"confidence={confidence_text} method={metadata['orientation_method']}"
            f"{recheck_text}")


def main() -> None:
    if sys.argv[1:2] == ["app"]:
        from tuzkaocr.app.server import main as app_main
        app_main(sys.argv[2:])
        return
    p = argparse.ArgumentParser(
        description="tuzkaocr — OCR pipeline for scanned page and document images",
        epilog="Run 'tuzkaocr app' to choose folders and read pages in your web browser instead.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("input", nargs="?", help="Image file or directory (with --batch)")
    p.add_argument("--out",      default=None,    help="Output file path (single image)")
    p.add_argument("--out-dir",  default="results", help="Output directory (batch mode)")
    p.add_argument("--format",   choices=["alto", "page", "txt", "multi"], default="alto",
                   help="Output format: alto (ALTO XML), page (PAGE XML), txt (plain text), "
                        "or multi (ALTO and text)")
    p.add_argument("--batch",    action="store_true", help="Process all images in a directory")
    p.add_argument("--workers",  type=int, default=2, help="Parallel page workers (batch)")

    p.add_argument("--domain", default="default",
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

    p.add_argument("--height-scale", type=float, default=None,
                   help="Multiply predicted line heights (use 1.5 if layout model underestimates)")
    p.add_argument("--no-adaptive", dest="adaptive", action="store_false",
                   help="Disable adaptive downsampling (fixed-downsample layout instead of sizing it to the text)")
    p.set_defaults(adaptive=None)
    p.add_argument("--reading-order", choices=["columns", "basic"], default=None,
                   help="Block reading order for printed pages: columns (column by column, "
                        "aware of printed rules) or basic (horizontal bands); default "
                        "TUZKAOCR_READING_ORDER or columns")
    p.add_argument("--no-large-text", dest="large_text", action="store_false",
                   help="Disable the extra layout pass for text far larger than the body "
                        "text (newspaper mastheads)")
    p.set_defaults(large_text=None)
    p.add_argument("--no-showthrough", dest="showthrough", action="store_false",
                   help="Keep faint mirrored text bleeding through from the reverse side "
                        "instead of removing it (printed domain)")
    p.set_defaults(showthrough=None)
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
    p.add_argument("--orientation", choices=["off", "auto"], default=None,
                   help="Page orientation handling; default TUZKAOCR_ORIENTATION or off")
    p.add_argument("--orientation-threshold", type=float, default=None,
                   help="Minimum classifier probability before using its angle directly")
    p.add_argument("--orientation-probe", choices=["on", "off"], default=None,
                   help="Use OCR confidence probing when the classifier is below threshold")
    p.add_argument("--contrast", choices=["off", "on", "auto", "line"], default=None,
                   help="Normalize grayscale contrast per page or recognizer crop")
    p.add_argument("--ndk-warn", action="store_true",
                   help="Report NDK profile fields that could not be filled from the input "
                        "or the configuration")
    p.add_argument("--version", action="store_true", help="Show the core and default domain version")
    p.add_argument("--list-domains", action="store_true", help="List built-in and installed domains")
    p.add_argument("--check-domains", action="store_true", help="Validate every installed domain pack")

    args = p.parse_args()
    from tuzkaocr import __version__
    from tuzkaocr.config import Config
    from tuzkaocr.domains import (DomainPackError, DomainRegistry, build_domain_config,
                                  retired_domain_message, validate_registry_packs)

    _base = Config()
    try:
        registry = DomainRegistry(_base, check=args.check_domains)
    except DomainPackError as exc:
        print(f"error: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(2)

    if args.check_domains:
        errors = validate_registry_packs(registry)
        if not registry.pack_statuses:
            print("No custom domain packs found.")
        for status in registry.pack_statuses:
            if status.status == "ok":
                print(f"OK {status.source.name}: {status.name} {status.version}")
            else:
                print(f"ERROR {status.source.name}: {status.reason}")
        raise SystemExit(1 if errors else 0)

    if args.version:
        print(f"TuzkaOCR {__version__}")
        default_domain = registry.default_domain
        if default_domain.pack:
            pack = default_domain.pack
            model = Path(str(pack.models["ocr"])).stem
            print(f'custom domain: {pack.name} {pack.version} "{pack.title}" (default)')
            print(f"  base {pack.base} · model {model} · requires {pack.requires_tuzkaocr} · checksums ok")
        raise SystemExit(0)

    if args.list_domains:
        print(f"default: {registry.default_name}")
        for name in ("print", "kramarky", "handwritten"):
            print(f"{name} (built-in)")
        for status in registry.pack_statuses:
            if status.status == "ok":
                marker = " (default)" if registry.default_name == status.name else ""
                print(f"{status.name} {status.version} — {status.title} [{status.base}]{marker}")
            else:
                print(f"{status.source.name}: {status.status} — {status.reason}")
        raise SystemExit(0)

    if not args.input:
        p.error("input is required unless --version, --list-domains, or --check-domains is used")

    retired = retired_domain_message(args.domain)
    if retired:
        p.error(retired)
    try:
        domain = registry.resolve(args.domain)
    except KeyError:
        p.error(f"unknown domain {args.domain!r}. Allowed: {', '.join(registry.names())}")

    if args.physical_img_nr is not None and args.physical_img_nr <= 0:
        p.error("--physical-img-nr must be a positive integer")
    if args.batch and (args.physical_img_nr is not None or args.source_identifier is not None):
        p.error("--physical-img-nr and --source-identifier apply to a single image, not --batch")

    from tuzkaocr.alto import physical_page_number
    overrides = {
        "layout_model": args.layout_model,
        "ocr_model": args.ocr_model,
        "vocab": args.vocab,
        "device": args.device,
        "ocr_threads": args.ocr_threads,
        "line_workers": args.line_workers,
        "page_workers": args.workers,
        "height_scale": args.height_scale,
        "adaptive_downsample": False if args.adaptive is False else None,
        "reading_order": args.reading_order if domain.base == "print" else None,
        "large_text": False if args.large_text is False else None,
        "showthrough": False if args.showthrough is False else None,
        "role_classifier": args.role_classifier,
        "alto_profile": args.alto_profile,
        "orientation": args.orientation,
        "orientation_threshold": args.orientation_threshold,
        "orientation_probe": args.orientation_probe,
        "contrast": args.contrast,
        "alto_lang": args.alto_lang,
        "alto_agency": args.alto_agency,
        "alto_dpi": args.alto_dpi,
        "alto_page_width_mm": args.alto_page_width_mm,
    }
    cfg = build_domain_config(
        _base, domain, explicit_overrides=overrides,
    )
    cfg_kwargs = dataclasses.asdict(cfg)
    domain_display = domain.name if domain.pack else (
        "default" if args.domain in ("default", "", None) else domain.name
    )

    if (args.ndk_warn and cfg_kwargs["alto_profile"] == "ndk"
            and not cfg_kwargs["alto_agency"].strip()):
        print("note: processingAgency is omitted — set TUZKAOCR_ALTO_AGENCY or --alto-agency "
              "to name the institution running the OCR (the NDK profile requires it)",
              file=sys.stderr, flush=True)

    if not args.batch:
        from tuzkaocr.pipeline import PageProcessor

        processor = PageProcessor(cfg)

        img_path = Path(args.input)
        suffix_map = {"alto": ".alto.xml", "page": ".page.xml", "txt": ".txt", "multi": ""}
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

        result, metadata = processor.process_file(
            img_path, out_path=out_path, fmt=args.format, with_meta=True,
            source_identifier=args.source_identifier,
            physical_img_nr=args.physical_img_nr,
        )
        elapsed = time.time() - t0

        if args.format == "multi":
            n_lines = result["txt"].count("\n")
            n_strings = result["alto"].count("<String ")
            print(f"Done in {elapsed:.1f}s — {n_strings} words, {n_lines} lines → "
                  f"{out_path}.alto.xml, {out_path}.txt; "
                  f"{_orientation_summary(metadata)} domain={domain_display}", flush=True)
        elif args.format == "page":
            n_words = result.count("<Word ")
            print(f"Done in {elapsed:.1f}s — {n_words} words → {out_path}; "
                  f"{_orientation_summary(metadata)} domain={domain_display}", flush=True)
        elif args.format == "txt":
            n_lines = result.count("\n")
            print(f"Done in {elapsed:.1f}s — {n_lines} lines → {out_path}; "
                  f"{_orientation_summary(metadata)} domain={domain_display}", flush=True)
        else:
            n_strings = result.count("<String ")
            print(f"Done in {elapsed:.1f}s — {n_strings} words → {out_path}; "
                  f"{_orientation_summary(metadata)} domain={domain_display}", flush=True)

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

        suffix_map = {"alto": ".alto.xml", "page": ".page.xml", "txt": ".txt", "multi": ""}
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
                img_path, elapsed, err, metadata = future.result()
                done += 1
                if err:
                    errors += 1
                    print(f"[{done:4d}/{len(images)}] ERROR {Path(img_path).name} "
                          f"domain={domain_display}: {err}",
                          flush=True)
                else:
                    eta = (time.time() - t0) / done * (len(images) - done)
                    print(f"[{done:4d}/{len(images)}] {Path(img_path).name} "
                          f"{elapsed:.1f}s  ETA {eta/60:.1f}m  "
                          f"{_orientation_summary(metadata)} domain={domain_display}", flush=True)

        total = time.time() - t0
        print(f"\nDone: {done - errors}/{len(images)} OK, {errors} errors, "
              f"total {total:.1f}s ({total/max(1,len(images)):.1f}s/page)", flush=True)


if __name__ == "__main__":
    main()
