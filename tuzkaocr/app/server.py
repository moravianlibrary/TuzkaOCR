from __future__ import annotations

import argparse
import dataclasses
import json
import mimetypes
import os
import re
import secrets
import string
import subprocess
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from collections import OrderedDict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

STATIC = Path(__file__).resolve().parent / "static"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
RESULTS_DIRNAME = "TuzkaOCR"
BUILTIN_MATERIALS = ("print", "handwritten", "kramarky")


def _xdg_user_dirs(home: Path) -> dict[str, Path]:
    cfg = Path(os.environ.get("XDG_CONFIG_HOME", home / ".config")) / "user-dirs.dirs"
    found: dict[str, Path] = {}
    try:
        text = cfg.read_text(encoding="utf-8")
    except OSError:
        return found
    for key, value in re.findall(r'^XDG_(\w+)_DIR="([^"]*)"', text, re.M):
        found[key.lower()] = Path(value.replace("$HOME", str(home)))
    return found


def places() -> list[dict]:
    home = Path.home()
    xdg = _xdg_user_dirs(home) if sys.platform.startswith("linux") else {}
    onedrive = Path(os.environ["OneDrive"]) if os.environ.get("OneDrive") else None
    items = [{"key": "home", "path": str(home)}]
    for key, xdg_key, name in (("desktop", "desktop", "Desktop"),
                               ("documents", "documents", "Documents"),
                               ("downloads", "download", "Downloads"),
                               ("pictures", "pictures", "Pictures")):
        candidates = [xdg.get(xdg_key)] if xdg_key in xdg else []
        if onedrive is not None:
            candidates.append(onedrive / name)
        candidates.append(home / name)
        for candidate in candidates:
            if candidate is not None and candidate.is_dir() and candidate != home:
                items.append({"key": key, "path": str(candidate)})
                break
    return items


def drives() -> list[dict]:
    found: list[dict] = []
    if os.name == "nt":
        for letter in string.ascii_uppercase:
            root = f"{letter}:\\"
            if os.path.exists(root):
                found.append({"name": f"{letter}:", "path": root})
        return found
    roots: list[Path] = []
    if sys.platform == "darwin":
        roots = [Path("/Volumes")]
    else:
        user = os.environ.get("USER", "")
        roots = [Path("/media") / user, Path("/run/media") / user, Path("/mnt")]
    for root in roots:
        try:
            entries = sorted(root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir() and entry.resolve() != Path("/"):
                    found.append({"name": entry.name, "path": str(entry)})
            except OSError:
                continue
    return found


def _hidden(entry: os.DirEntry) -> bool:
    if entry.name.startswith((".", "$", "~$")):
        return True
    if os.name == "nt":
        try:
            attrs = entry.stat(follow_symlinks=False).st_file_attributes
        except (OSError, AttributeError):
            return False
        return bool(attrs & 0x2 or attrs & 0x4)
    return entry.name in {"__pycache__", "node_modules"}


def results_dir_for(folder: Path) -> Path:
    return folder / RESULTS_DIRNAME


def fallback_results_dir(folder: Path) -> Path:
    for place in places():
        if place["key"] == "documents":
            return Path(place["path"]) / RESULTS_DIRNAME / folder.name
    return Path.home() / RESULTS_DIRNAME / folder.name


def _writable(path: Path) -> bool:
    target = path
    while not target.exists():
        if target.parent == target:
            return False
        target = target.parent
    return os.access(target, os.W_OK)


def output_dir_for(folder: Path, custom: str | None = None) -> Path:
    if custom:
        return Path(custom)
    preferred = results_dir_for(folder)
    return preferred if _writable(preferred) else fallback_results_dir(folder)


def _done_stems(out_dir: Path) -> set[str]:
    stems: set[str] = set()
    try:
        for name in os.listdir(out_dir):
            for suffix in (".alto.xml", ".txt"):
                if name.endswith(suffix):
                    stems.add(name[: -len(suffix)])
    except OSError:
        pass
    return stems


def list_folder(path: Path, custom_output: str | None = None) -> dict:
    path = path.expanduser()
    resolved = path.resolve()
    dirs, images = [], []
    with os.scandir(resolved) as it:
        for entry in it:
            if _hidden(entry):
                continue
            try:
                if entry.is_dir():
                    if entry.name == RESULTS_DIRNAME:
                        continue
                    dirs.append({"name": entry.name, "path": entry.path})
                elif entry.is_file() and Path(entry.name).suffix.lower() in IMAGE_EXTS:
                    st = entry.stat()
                    images.append({"name": entry.name, "path": entry.path,
                                   "size": st.st_size, "mtime": int(st.st_mtime)})
            except OSError:
                continue
    key = lambda item: _natural_key(item["name"])
    dirs.sort(key=key)
    images.sort(key=key)
    out_dir = output_dir_for(resolved, custom_output)
    done = _done_stems(out_dir)
    for image in images:
        image["done"] = Path(image["name"]).stem in done
    crumbs = []
    for part in [resolved, *resolved.parents][::-1]:
        crumbs.append({"name": part.name or str(part), "path": str(part)})
    parent = str(resolved.parent) if resolved.parent != resolved else None
    return {"path": str(resolved), "name": resolved.name or str(resolved), "parent": parent,
            "crumbs": crumbs, "dirs": dirs, "images": images,
            "output": str(out_dir), "output_custom": bool(custom_output),
            "output_is_fallback": not custom_output and out_dir != results_dir_for(resolved),
            "writable": os.access(resolved, os.W_OK)}


def _natural_key(name: str):
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", name)]


def open_in_file_manager(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)


class ThumbCache:
    def __init__(self, limit: int = 600):
        self.limit = limit
        self.items: OrderedDict[tuple, bytes] = OrderedDict()
        self.lock = threading.Lock()

    def get(self, path: Path, size: int) -> bytes:
        import cv2
        import numpy as np
        st = path.stat()
        key = (str(path), st.st_mtime_ns, size)
        with self.lock:
            if key in self.items:
                self.items.move_to_end(key)
                return self.items[key]
        data = np.fromfile(path, dtype=np.uint8)
        flag = cv2.IMREAD_REDUCED_COLOR_8 if size <= 200 else cv2.IMREAD_COLOR
        img = cv2.imdecode(data, flag)
        if img is None:
            img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("cannot decode image")
        h, w = img.shape[:2]
        scale = min(1.0, size / max(h, w))
        if scale < 1.0:
            img = cv2.resize(img, (max(1, int(w * scale)), max(1, int(h * scale))),
                             interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
        if not ok:
            raise ValueError("cannot encode image")
        blob = buf.tobytes()
        with self.lock:
            self.items[key] = blob
            while len(self.items) > self.limit:
                self.items.popitem(last=False)
        return blob


def read_result_text(image: Path, out_dir: Path) -> str | None:
    stem = image.stem
    txt = out_dir / f"{stem}.txt"
    if txt.is_file():
        return txt.read_text(encoding="utf-8")
    alto = out_dir / f"{stem}.alto.xml"
    if alto.is_file():
        tree = ET.parse(alto)
        lines = []
        for line in tree.iter():
            if not line.tag.endswith("TextLine"):
                continue
            words = [el.get("CONTENT", "") for el in line if el.tag.endswith("String")]
            lines.append(" ".join(w for w in words if w))
        return "\n".join(lines)
    return None


@dataclasses.dataclass
class Job:
    folder: str
    output: str
    material: str
    formats: list[str]
    files: list[str]
    state: str = "loading"
    index: int = 0
    current: str | None = None
    started: float = dataclasses.field(default_factory=time.time)
    page_started: float | None = None
    finished: float | None = None
    durations: list[float] = dataclasses.field(default_factory=list)
    results: dict[str, dict] = dataclasses.field(default_factory=dict)
    message: str | None = None
    stop: bool = False

    def snapshot(self) -> dict:
        results = dict(self.results)
        done = len(results)
        remaining = len(self.files) - done
        eta = None
        if self.durations and self.state == "running":
            per_page = sum(self.durations[-8:]) / len(self.durations[-8:])
            eta = per_page * remaining
            if self.page_started is not None:
                eta = max(0.0, eta - (time.time() - self.page_started))
        return {
            "folder": self.folder, "output": self.output, "material": self.material,
            "formats": self.formats, "files": self.files, "state": self.state,
            "total": len(self.files),
            "done": done, "failed": sum(1 for r in results.values() if not r["ok"]),
            "current": self.current, "eta": eta, "results": results,
            "elapsed": (self.finished or time.time()) - self.started, "message": self.message,
        }


class Engine:
    def __init__(self):
        from tuzkaocr.config import Config
        from tuzkaocr.domains import DomainRegistry
        self.base = Config()
        self.registry = DomainRegistry(self.base)
        self.processors: dict[str, object] = {}
        self.lock = threading.Lock()
        self.job: Job | None = None

    def materials(self) -> list[dict]:
        items = [{"key": key, "builtin": True} for key in BUILTIN_MATERIALS]
        for status in self.registry.pack_statuses:
            if status.status == "ok" and status.name:
                pack = status.pack
                items.append({"key": status.name, "builtin": False, "title": status.title,
                              "base": status.base, "version": status.version,
                              "description": (pack.description if pack else "").strip()})
        return items

    def default_material(self) -> str:
        name = self.registry.default_name
        return "print" if name in ("default", "print", "printed") else name

    def processor(self, material: str):
        from tuzkaocr.domains import build_domain_config
        from tuzkaocr.pipeline import PageProcessor
        if material not in self.processors:
            domain = self.registry.resolve(material)
            threads = max(1, min(4, os.cpu_count() or 1))
            cfg = build_domain_config(self.base, domain, explicit_overrides={
                "ocr_threads": threads, "line_workers": threads, "page_workers": 1,
            })
            self.processors = {material: PageProcessor(cfg)}
        return self.processors[material]

    def start(self, folder: Path, files: list[str], material: str, formats: list[str],
              custom_output: str | None = None) -> Job:
        with self.lock:
            if self.job and self.job.state in ("loading", "running"):
                raise RuntimeError("busy")
            out_dir = output_dir_for(folder, custom_output)
            out_dir.mkdir(parents=True, exist_ok=True)
            if not os.access(out_dir, os.W_OK):
                raise PermissionError(str(out_dir))
            job = Job(folder=str(folder), output=str(out_dir), material=material,
                      formats=formats, files=files)
            self.job = job
        threading.Thread(target=self._run, args=(job,), daemon=True).start()
        return job

    def _run(self, job: Job) -> None:
        fmt = "multi" if set(job.formats) == {"txt", "alto"} else job.formats[0]
        folder, out_dir = Path(job.folder), Path(job.output)
        total = len(job.files)
        try:
            print(f"Loading models for {job.material}...", flush=True)
            processor = self.processor(job.material)
        except Exception as exc:
            job.state, job.message, job.finished = "error", str(exc), time.time()
            print(f"error: {exc}", flush=True)
            return
        job.state = "running"
        print(f"Reading {total} page(s) from {folder} into {out_dir}", flush=True)
        for i, name in enumerate(job.files, 1):
            if job.stop:
                break
            job.index, job.current, job.page_started = i, name, time.time()
            image = folder / name
            stem = Path(name).stem
            target = out_dir / (stem if fmt == "multi" else
                                stem + {"txt": ".txt", "alto": ".alto.xml"}[fmt])
            try:
                result, meta = processor.process_file(image, out_path=target, fmt=fmt,
                                                      with_meta=True)
                text = result["txt"] if isinstance(result, dict) else (
                    result if fmt == "txt" else None)
                lines = meta.get("n_lines", 0) if meta else 0
                job.results[name] = {"ok": True, "lines": lines,
                                     "empty": lines == 0 and not (text or "").strip()}
                error = None
            except Exception as exc:
                error = str(exc) or exc.__class__.__name__
                job.results[name] = {"ok": False, "error": error}
            spent = time.time() - job.page_started
            job.durations.append(spent)
            mean = sum(job.durations) / len(job.durations)
            eta = mean * (total - i)
            status = f"ERROR {error}" if error else f"{spent:.1f}s"
            print(f"[{i}/{total}] {name} {status}  ETA {eta / 60:.1f}m", flush=True)
        job.current, job.page_started = None, None
        job.finished = time.time()
        job.state = "stopped" if job.stop and len(job.results) < total else "done"
        print(f"{job.state.capitalize()}: {len(job.results)}/{total} page(s) in "
              f"{job.finished - job.started:.0f}s -> {out_dir}", flush=True)


class App:
    def __init__(self, engine: Engine, version: str, port: int):
        self.engine = engine
        self.version = version
        self.port = port
        self.key = secrets.token_urlsafe(24)
        self.url = f"http://127.0.0.1:{port}/?k={self.key}"
        self.thumbs = ThumbCache()


def make_handler(app: App):
    allowed_hosts = {f"127.0.0.1:{app.port}", f"localhost:{app.port}"}

    class Handler(BaseHTTPRequestHandler):
        server_version = "TuzkaOCR"

        def log_message(self, *args):
            pass

        def _send(self, status: int, body: bytes, ctype: str, cache: bool = False):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "private, max-age=3600" if cache else "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload, status: int = 200):
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                       "application/json; charset=utf-8")

        def _error(self, status: int, code: str, detail: str = ""):
            self._json({"error": code, "detail": detail}, status)

        def _guard(self, api: bool) -> bool:
            if self.headers.get("Host", "") not in allowed_hosts:
                self._send(403, b"Forbidden", "text/plain")
                return False
            if api:
                query = parse_qs(urlparse(self.path).query)
                key = self.headers.get("X-TuzkaOCR-Key") or query.get("k", [""])[0]
                if not secrets.compare_digest(key, app.key):
                    self._error(403, "forbidden")
                    return False
            return True

        def do_GET(self):
            url = urlparse(self.path)
            api = url.path.startswith("/api/")
            if not self._guard(api):
                return
            q = {k: v[0] for k, v in parse_qs(url.query).items()}
            try:
                if not api:
                    return self._static(url.path)
                route = url.path[len("/api/"):]
                if route == "info":
                    return self._json({
                        "version": app.version, "platform": sys.platform,
                        "home": str(Path.home()), "places": places(), "drives": drives(),
                        "materials": app.engine.materials(),
                        "default_material": app.engine.default_material(),
                        "start": os.environ.get("TUZKAOCR_APP_START") or str(Path.home()),
                    })
                if route == "list":
                    path = Path(q.get("path") or Path.home())
                    if not path.is_dir():
                        return self._error(404, "not_found", str(path))
                    custom = q.get("output") or None
                    if custom and not Path(custom).is_absolute():
                        custom = None
                    try:
                        return self._json(list_folder(path, custom))
                    except PermissionError:
                        return self._error(403, "no_access", str(path))
                if route == "thumb":
                    size = 160 if q.get("size") != "large" else 2000
                    blob = app.thumbs.get(Path(q["path"]), size)
                    return self._send(200, blob, "image/jpeg", cache=True)
                if route == "text":
                    image = Path(q["path"])
                    text = read_result_text(image, output_dir_for(image.parent, q.get("output")))
                    if text is None:
                        return self._error(404, "no_result")
                    return self._json({"text": text})
                if route == "job":
                    job = app.engine.job
                    return self._json(job.snapshot() if job else None)
                return self._error(404, "not_found")
            except FileNotFoundError as exc:
                return self._error(404, "not_found", str(exc))
            except Exception as exc:
                return self._error(500, "internal", str(exc))

        def do_POST(self):
            url = urlparse(self.path)
            if not self._guard(True):
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
                route = url.path[len("/api/"):]
                if route == "start":
                    folder = Path(body["folder"])
                    files = [f for f in body.get("files", []) if isinstance(f, str)]
                    formats = [f for f in body.get("formats", []) if f in ("txt", "alto")]
                    material = body.get("material") or app.engine.default_material()
                    custom = body.get("output") or None
                    if custom is not None and (not isinstance(custom, str)
                                               or not Path(custom).is_absolute()):
                        return self._error(400, "bad_request")
                    known = {m["key"] for m in app.engine.materials()}
                    if not folder.is_dir():
                        return self._error(400, "not_found", str(folder))
                    if not files or not formats or material not in known:
                        return self._error(400, "bad_request")
                    if any(Path(f).name != f or not (folder / f).is_file() for f in files):
                        return self._error(400, "bad_request")
                    try:
                        job = app.engine.start(folder, files, material, formats, custom)
                    except RuntimeError:
                        return self._error(409, "busy")
                    except OSError as exc:
                        return self._error(400, "cannot_write", str(exc))
                    return self._json(job.snapshot())
                if route == "mkdir":
                    parent = Path(body["parent"])
                    name = str(body["name"]).strip()
                    if (not name or name in (".", "..") or Path(name).name != name
                            or any(c in name for c in '<>:"/\\|?*')):
                        return self._error(400, "bad_name")
                    if not parent.is_dir():
                        return self._error(404, "not_found", str(parent))
                    target = parent / name
                    try:
                        target.mkdir()
                    except FileExistsError:
                        return self._error(409, "exists", str(target))
                    except PermissionError:
                        return self._error(403, "no_access", str(parent))
                    return self._json({"path": str(target)})
                if route == "stop":
                    if app.engine.job:
                        app.engine.job.stop = True
                    return self._json({"ok": True})
                if route == "open":
                    path = Path(body["path"])
                    if not path.is_dir():
                        return self._error(404, "not_found", str(path))
                    open_in_file_manager(path)
                    return self._json({"ok": True})
                return self._error(404, "not_found")
            except (KeyError, ValueError, TypeError) as exc:
                return self._error(400, "bad_request", str(exc))
            except Exception as exc:
                return self._error(500, "internal", str(exc))

        def _static(self, path: str):
            name = "index.html" if path in ("/", "") else path.lstrip("/")
            target = (STATIC / name).resolve()
            if STATIC.resolve() not in target.parents or not target.is_file():
                return self._send(404, b"Not found", "text/plain")
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, target.read_bytes(), ctype)

    return Handler


def create_server(port: int = 0) -> tuple[ThreadingHTTPServer, App]:
    from tuzkaocr import __version__
    httpd = ThreadingHTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    app = App(Engine(), __version__, httpd.server_address[1])
    httpd.RequestHandlerClass = make_handler(app)
    httpd.daemon_threads = True
    return httpd, app


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tuzkaocr app",
                                     description="Open TuzkaOCR in your web browser")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except AttributeError:
            pass

    from tuzkaocr import __version__

    httpd, app = create_server(args.port)
    url = app.url

    print(f"TuzkaOCR {__version__} is running at:\n\n    {url}\n", flush=True)
    print("Keep this window open while you work. Close it, or press Ctrl+C, to quit.\n",
          flush=True)
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nTuzkaOCR stopped.", flush=True)
    finally:
        httpd.server_close()


if __name__ == "__main__":
    main()
