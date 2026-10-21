from __future__ import annotations

import dataclasses
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

from . import __version__, _models
from .config import Config, env_is_explicit


BUILTIN_NAMES = ("default", "print", "printed", "kramarky", "handwritten", "kurrent")
BUILTIN_DOMAIN_NAMES = ("print", "kramarky", "handwritten", "kurrent")
PACK_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,31}$")
PACK_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
SETTING_NAMES = {
    "orientation", "orientation_threshold", "orientation_probe", "orientation_recheck",
    "contrast", "contrast_ink", "reading_order", "height_scale", "large_text",
    "adaptive_downsample",
}
MAX_PACK_BYTES = 500 * 1024 * 1024
MAX_PACK_MEMBERS = 128


class DomainPackError(ValueError):
    pass


@dataclass(frozen=True)
class PackMetadata:
    name: str
    version: str
    title: str
    base: str
    description: str
    default: bool
    requires_tuzkaocr: str
    models: Mapping[str, str | None]
    settings: Mapping[str, Any]
    sha256: Mapping[str, str]
    path: Path
    source: Path
    author: str = ""
    license: str = ""


@dataclass(frozen=True)
class Domain:
    name: str
    base: str
    layout_model: str
    ocr_model: str
    vocab: str
    settings: Mapping[str, Any] = field(default_factory=dict)
    pack: PackMetadata | None = None
    crop_endpoint_ext: float = 0.0
    column_split: bool = False


@dataclass
class PackStatus:
    source: Path
    name: str | None = None
    version: str | None = None
    title: str | None = None
    base: str | None = None
    ocr_model: str | None = None
    default: bool = False
    status: str = "skipped"
    reason: str | None = None
    pack: PackMetadata | None = None


def builtin_domains(base_cfg: Config) -> dict[str, Domain]:
    return {
        "print": Domain(
            "print", "print", base_cfg.layout_model, base_cfg.ocr_model, base_cfg.vocab,
        ),
        "kramarky": Domain(
            "kramarky", "kramarky", base_cfg.kramarky_layout_model,
            base_cfg.kramarky_ocr_model, base_cfg.vocab,
        ),
        "handwritten": Domain(
            "handwritten", "handwritten", base_cfg.handwritten_layout_model,
            base_cfg.handwritten_ocr_model, base_cfg.vocab, crop_endpoint_ext=0.3,
            column_split=True,
        ),
        "kurrent": Domain(
            "kurrent", "kurrent", base_cfg.kurrent_layout_model,
            base_cfg.kurrent_ocr_model, base_cfg.vocab, crop_endpoint_ext=0.3,
            column_split=True,
        ),
    }


def _coerce_setting(name: str, value: Any, base_cfg: Config) -> Any:
    expected = type(getattr(base_cfg, name))
    if expected is bool:
        if type(value) is not bool:
            raise DomainPackError(f"setting {name} must be a boolean")
        return value
    if expected is int:
        if type(value) is not int:
            raise DomainPackError(f"setting {name} must be an integer")
        return value
    if expected is float:
        if type(value) not in (int, float):
            raise DomainPackError(f"setting {name} must be a number")
        return float(value)
    if not isinstance(value, expected):
        raise DomainPackError(f"setting {name} must be a string")
    return value


def _validate_settings(settings: Any, base_cfg: Config) -> dict[str, Any]:
    if not isinstance(settings, dict):
        raise DomainPackError("settings must be an object")
    result = {}
    for name, value in settings.items():
        if name not in SETTING_NAMES:
            raise DomainPackError(f"unknown setting key {name!r}")
        result[name] = _coerce_setting(name, value, base_cfg)
    try:
        dataclasses.replace(base_cfg, **result)
    except (RuntimeError, TypeError, ValueError) as exc:
        raise DomainPackError(f"invalid settings: {exc}") from exc
    return result


def _version_tuple(value: str) -> tuple[int, int, int]:
    if not PACK_VERSION_RE.fullmatch(value):
        raise DomainPackError(f"unsupported version {value!r}; expected X.Y.Z")
    return tuple(int(part) for part in value.split("."))


def _check_requires(requirement: str, current: str) -> None:
    if not isinstance(requirement, str) or not requirement.strip():
        raise DomainPackError("requires_tuzkaocr must be a non-empty version range")
    current_version = _version_tuple(current)
    clauses = [part.strip() for part in requirement.split(",")]
    for clause in clauses:
        match = re.fullmatch(r"(>=|<=|>|<|==|=)\s*(\d+\.\d+\.\d+)", clause)
        if not match:
            raise DomainPackError(f"unsupported requires_tuzkaocr clause {clause!r}")
        operator, target_text = match.groups()
        target = _version_tuple(target_text)
        valid = {
            ">=": current_version >= target,
            "<=": current_version <= target,
            ">": current_version > target,
            "<": current_version < target,
            "==": current_version == target,
            "=": current_version == target,
        }[operator]
        if not valid:
            raise DomainPackError(
                f"TuzkaOCR {current} does not satisfy requires_tuzkaocr {requirement}"
            )


def _pack_directory(source: Path) -> Path:
    if source.is_symlink():
        raise DomainPackError("pack entry must not be a symlink")
    if source.is_dir():
        return source
    if source.suffix.lower() != ".tpack":
        raise DomainPackError("pack must be a folder or a .tpack file")
    try:
        digest = _sha256(source)
    except OSError as exc:
        raise DomainPackError(f"cannot read pack: {exc}") from exc
    cache_root = os.environ.get("TUZKAOCR_PACK_CACHE")
    if cache_root is None:
        cache = Path(tempfile.gettempdir()) / "tuzkaocr-packs"
    elif cache_root == "":
        raise DomainPackError("TUZKAOCR_PACK_CACHE must not be empty")
    else:
        cache = Path(cache_root).expanduser()
    target = cache / digest[:16]
    marker = target / ".complete"
    if marker.is_file() and marker.read_text(encoding="ascii").strip() == digest:
        return target

    try:
        with zipfile.ZipFile(source) as archive:
            members = archive.infolist()
            if len(members) > MAX_PACK_MEMBERS:
                raise DomainPackError(
                    f"zip has {len(members)} members; maximum is {MAX_PACK_MEMBERS}"
                )
            total_size = 0
            for member in members:
                name = member.filename
                path = Path(name)
                mode = member.external_attr >> 16
                if (not name or path.is_absolute() or "/" in name or "\\" in name
                        or ".." in name or name in (".", "..")):
                    raise DomainPackError(f"unsafe zip member {name!r}")
                if member.is_dir():
                    raise DomainPackError(f"nested directories are not allowed in .tpack: {name!r}")
                if stat.S_ISLNK(mode):
                    raise DomainPackError(f"symlinks are not allowed in .tpack: {name!r}")
                total_size += member.file_size
            if total_size > MAX_PACK_BYTES:
                raise DomainPackError(
                    f"zip uncompressed size {total_size} exceeds {MAX_PACK_BYTES} byte limit"
                )
            cache.mkdir(parents=True, exist_ok=True)
            temp_path = Path(tempfile.mkdtemp(prefix=f".{digest[:16]}-", dir=cache))
            try:
                for member in members:
                    with archive.open(member) as reader, (temp_path / member.filename).open("wb") as writer:
                        shutil.copyfileobj(reader, writer)
                (temp_path / ".complete").write_text(digest, encoding="ascii")
                if target.exists():
                    shutil.rmtree(target)
                temp_path.rename(target)
            except Exception:
                shutil.rmtree(temp_path, ignore_errors=True)
                raise
    except DomainPackError:
        raise
    except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
        raise DomainPackError(f"cannot extract .tpack: {exc}") from exc
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _plain_filename(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value:
        raise DomainPackError(f"models.{field_name} must be a filename")
    path = Path(value)
    if (path.is_absolute() or path.name != value or "/" in value or "\\" in value
            or ".." in value or value in (".", "..")):
        raise DomainPackError(f"models.{field_name} must be a plain filename inside the pack")
    return value


def _read_manifest(source: Path, base_cfg: Config) -> tuple[dict[str, Any], PackMetadata]:
    pack_dir = _pack_directory(source)
    manifest_path = pack_dir / "domain.json"
    if manifest_path.is_symlink():
        raise DomainPackError("domain.json must not be a symlink")
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise DomainPackError("missing domain.json") from exc
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DomainPackError(f"cannot parse domain.json: {exc}") from exc
    if not isinstance(raw, dict):
        raise DomainPackError("domain.json must contain an object")
    allowed_keys = {
        "format", "name", "version", "title", "description", "base", "default",
        "requires_tuzkaocr", "models", "settings", "sha256", "author", "license",
    }
    for key in sorted(raw.keys() - allowed_keys):
        print(f"warning: {source}: unknown domain.json key {key!r}", file=sys.stderr, flush=True)
    if type(raw.get("format")) is not int or raw.get("format") != 1:
        raise DomainPackError("format must be 1")
    name = raw.get("name")
    if not isinstance(name, str) or not PACK_NAME_RE.fullmatch(name):
        raise DomainPackError("name must match ^[a-z][a-z0-9_-]{1,31}$")
    if name in BUILTIN_NAMES:
        raise DomainPackError(f"name {name!r} is reserved for a built-in domain")
    version = raw.get("version")
    _version_tuple(version if isinstance(version, str) else "")
    title = raw.get("title")
    if not isinstance(title, str) or not title.strip():
        raise DomainPackError("title must be a non-empty string")
    base = raw.get("base")
    if base not in BUILTIN_DOMAIN_NAMES:
        raise DomainPackError(f"base must be one of {BUILTIN_DOMAIN_NAMES}")
    if type(raw.get("default")) is not bool:
        raise DomainPackError("default must be a boolean")
    requires = raw.get("requires_tuzkaocr", "*")
    if requires != "*":
        _check_requires(requires, __version__)
    models = raw.get("models")
    if not isinstance(models, dict):
        raise DomainPackError("models must be an object")
    unknown_models = set(models) - {"ocr", "vocab", "layout"}
    if unknown_models:
        raise DomainPackError(f"unknown models key {sorted(unknown_models)[0]!r}")
    if "ocr" not in models or "vocab" not in models:
        raise DomainPackError("models.ocr and models.vocab are required")
    model_names = {
        "ocr": _plain_filename(models["ocr"], "ocr"),
        "vocab": _plain_filename(models["vocab"], "vocab"),
        "layout": None if models.get("layout") is None else _plain_filename(models["layout"], "layout"),
    }
    settings = _validate_settings(raw.get("settings", {}), base_cfg)
    checksums = raw.get("sha256")
    if not isinstance(checksums, dict):
        raise DomainPackError("sha256 must be an object")
    for key in (model_names["ocr"], model_names["vocab"], model_names["layout"]):
        if key is not None and key not in checksums:
            raise DomainPackError(f"sha256 is required for {key}")
    for filename, value in checksums.items():
        if (not isinstance(filename, str) or not isinstance(value, str)
                or not SHA256_RE.fullmatch(value)):
            raise DomainPackError(f"sha256 for {filename!r} must be a 64-character lowercase hex digest")
        _plain_filename(filename, "sha256")
    style_name = _sidecar_name(model_names["ocr"])
    if (pack_dir / style_name).exists() and style_name not in checksums:
        raise DomainPackError(f"sha256 is required for style sidecar {style_name}")
    _check_files(pack_dir, model_names, checksums)
    metadata = PackMetadata(
        name=name,
        version=version,
        title=title,
        base=base,
        description=raw.get("description", ""),
        default=raw["default"],
        requires_tuzkaocr=requires,
        models=model_names,
        settings=settings,
        sha256=checksums,
        path=pack_dir,
        source=source,
        author=raw.get("author", ""),
        license=raw.get("license", ""),
    )
    return raw, metadata


def _check_files(pack_dir: Path, models: Mapping[str, str | None], checksums: Mapping[str, str]) -> None:
    for filename, expected in checksums.items():
        path = pack_dir / filename
        if path.is_symlink() or not path.is_file():
            raise DomainPackError(f"missing file {filename}")
        actual = _sha256(path)
        if actual != expected:
            raise DomainPackError(f"sha256 mismatch for {filename}")
    for filename in models.values():
        if filename is not None and not (pack_dir / filename).is_file():
            raise DomainPackError(f"missing file {filename}")


def _sidecar_name(model_name: str) -> str:
    from .ocr.recognizer import _style_model_path

    return _style_model_path(model_name).name


def validate_pack_recognizer(pack: PackMetadata) -> None:
    from .ocr.recognizer import create_recognizer

    model_path = pack.path / str(pack.models["ocr"])
    vocab_path = pack.path / str(pack.models["vocab"])
    create_recognizer(model_path, vocab_path, device="cpu", threads=1)


def _domain_from_pack(pack: PackMetadata, base_cfg: Config,
                      builtins: Mapping[str, Domain]) -> Domain:
    base_domain = builtins[pack.base]
    layout_model = (str(pack.path / str(pack.models["layout"]))
                    if pack.models["layout"] is not None else base_domain.layout_model)
    return Domain(
        name=pack.name,
        base=pack.base,
        layout_model=layout_model,
        ocr_model=str(pack.path / str(pack.models["ocr"])),
        vocab=str(pack.path / str(pack.models["vocab"])),
        settings=pack.settings,
        pack=pack,
        crop_endpoint_ext=base_domain.crop_endpoint_ext,
        column_split=base_domain.column_split,
    )


class DomainRegistry:
    def __init__(self, base_cfg: Config | None = None, *, directory: str | Path | None = None,
                 check: bool = False):
        self.base_config = base_cfg or Config()
        self.builtins = builtin_domains(self.base_config)
        self.domains: dict[str, Domain] = dict(self.builtins)
        self.pack_statuses: list[PackStatus] = []
        self.errors: list[str] = []
        pack_dir = _domains_directory(directory)
        if pack_dir is not None and pack_dir.is_dir():
            self._load_directory(pack_dir, check=check)
        self._validate_duplicates(check=check)
        self.default_name = self._select_default(check=check)
        if not check:
            for status in self.pack_statuses:
                if (status.pack and (status.pack.default or status.pack.name == self.default_name)):
                    try:
                        validate_pack_recognizer(status.pack)
                    except Exception as exc:
                        raise DomainPackError(
                            f"default domain pack {status.source.name} is invalid: {exc}"
                        ) from exc

    @property
    def default_domain(self) -> Domain:
        return self.domains[self.default_name]

    @property
    def custom(self) -> bool:
        return any(status.pack is not None for status in self.pack_statuses)

    def names(self) -> list[str]:
        return list(BUILTIN_NAMES) + sorted(
            name for name, domain in self.domains.items() if domain.pack is not None
        )

    def resolve(self, name: str | None) -> Domain:
        if name in (None, "", "default"):
            return self.default_domain
        if name in ("print", "printed"):
            return self.builtins["print"]
        domain = self.domains.get(name)
        if domain is None:
            raise KeyError(name)
        return domain

    def version_payload(self) -> dict[str, Any]:
        items = []
        for status in self.pack_statuses:
            items.append({
                "name": status.name,
                "version": status.version,
                "title": status.title,
                "base": status.base,
                "ocr_model": status.ocr_model,
                "default": status.default,
                "status": status.status,
                "reason": status.reason,
            })
        return {
            "version": __version__,
            "custom": self.custom,
            "default_domain": self.default_name,
            "domains": items,
        }

    def _load_directory(self, directory: Path, *, check: bool) -> None:
        try:
            entries = sorted(directory.iterdir(), key=lambda path: path.name.casefold())
        except OSError as exc:
            self._error(directory, f"cannot scan domains directory: {exc}", check)
            return
        for source in entries:
            if source.name.startswith("."):
                continue
            if source.is_file() and source.suffix.lower() == ".tpack":
                pass
            elif source.is_dir() and (source / "domain.json").is_file():
                pass
            else:
                continue
            status = PackStatus(source=source)
            raw: dict[str, Any] = {}
            try:
                pack_dir = _pack_directory(source)
                try:
                    parsed = json.loads((pack_dir / "domain.json").read_text(encoding="utf-8"))
                    if isinstance(parsed, dict):
                        raw = parsed
                        status.name = parsed.get("name") if isinstance(parsed.get("name"), str) else None
                        status.version = parsed.get("version") if isinstance(parsed.get("version"), str) else None
                        status.title = parsed.get("title") if isinstance(parsed.get("title"), str) else None
                        status.base = parsed.get("base") if isinstance(parsed.get("base"), str) else None
                        models = parsed.get("models")
                        if isinstance(models, dict) and isinstance(models.get("ocr"), str):
                            status.ocr_model = models["ocr"]
                        status.default = parsed.get("default") is True
                except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                    pass
                _, pack = _read_manifest(source, self.base_config)
                status.pack = pack
                status.name = pack.name
                status.version = pack.version
                status.title = pack.title
                status.base = pack.base
                status.ocr_model = str(pack.models["ocr"])
                status.default = pack.default
                status.status = "ok"
                self.domains[pack.name] = _domain_from_pack(pack, self.base_config, self.builtins)
            except Exception as exc:
                status.reason = str(exc)
                status.status = "error" if check else "skipped"
                self._warn(source, str(exc))
                self._error(source, str(exc), check)
                if status.default and not check:
                    raise DomainPackError(
                        f"default domain pack {source.name} is invalid: {exc}"
                    ) from exc
            self.pack_statuses.append(status)

    def _validate_duplicates(self, *, check: bool) -> None:
        valid = [status for status in self.pack_statuses if status.pack is not None]
        by_name: dict[str, list[PackStatus]] = {}
        defaults = []
        for status in valid:
            by_name.setdefault(status.pack.name, []).append(status)
            if status.pack.default:
                defaults.append(status)
        errors = []
        problem_sources = set()
        for name, copies in by_name.items():
            if len(copies) > 1:
                errors.append(
                    f"duplicate domain name {name!r} in {copies[0].source.name} and "
                    f"{copies[1].source.name}"
                )
                problem_sources.update(status.source for status in copies)
        if len(defaults) > 1:
            errors.append(
                f"multiple default domain packs: {defaults[0].source.name} and "
                f"{defaults[1].source.name}"
            )
            problem_sources.update(status.source for status in defaults)
        if errors and not check:
            raise DomainPackError("; ".join(errors))
        for error in errors:
            self.errors.append(error)
            print(f"error: {error}", file=sys.stderr, flush=True)
        if errors:
            for status in valid:
                if status.source in problem_sources:
                    status.status = "error"
                    status.reason = "; ".join(errors)

    def _select_default(self, *, check: bool) -> str:
        override = os.environ.get("TUZKAOCR_DEFAULT_DOMAIN")
        if override is not None:
            if override in ("", "default", "print", "printed"):
                return "print"
            if override in self.domains:
                return override
            error = f"TUZKAOCR_DEFAULT_DOMAIN={override!r} is not a loaded domain"
            if not check:
                raise DomainPackError(error)
            self.errors.append(error)
            print(f"error: {error}", file=sys.stderr, flush=True)
            return "print"
        defaults = [
            status.pack.name for status in self.pack_statuses
            if status.pack is not None and status.pack.default and status.status == "ok"
        ]
        if len(defaults) == 1:
            return defaults[0]
        return "print"

    def _error(self, source: Path, reason: str, check: bool) -> None:
        if check:
            self.errors.append(f"{source.name}: {reason}")

    @staticmethod
    def _warn(source: Path, reason: str) -> None:
        print(f"warning: domain pack {source.name}: {reason}", file=sys.stderr, flush=True)


def _domains_directory(directory: str | Path | None) -> Path | None:
    if directory is not None:
        return Path(directory).expanduser()
    configured = os.environ.get("TUZKAOCR_DOMAINS_DIR")
    if configured is not None:
        return None if configured == "" else Path(configured).expanduser()
    xdg = os.environ.get("XDG_DATA_HOME")
    data_home = Path(xdg).expanduser() if xdg else Path.home() / ".local" / "share"
    return data_home / "tuzkaocr" / "domains"


def build_domain_config(base_cfg: Config, domain: Domain, *,
                        explicit_overrides: Mapping[str, Any] | None = None) -> Config:
    values: dict[str, Any] = {
        "layout_model": domain.layout_model,
        "ocr_model": domain.ocr_model,
        "vocab": domain.vocab,
        "crop_endpoint_ext": domain.crop_endpoint_ext,
        "column_split": domain.column_split,
        "domain_name": domain.name if domain.pack else "",
        "domain_version": domain.pack.version if domain.pack else "",
    }
    if domain.base != "print":
        values.update(
            adaptive_downsample=False,
            reading_order="basic",
            large_text=False,
        )

    if domain.pack:
        for name, value in domain.settings.items():
            explicit = env_is_explicit(f"TUZKAOCR_{name.upper()}")
            values[name] = getattr(base_cfg, name) if explicit else value

    if explicit_overrides:
        values.update({name: value for name, value in explicit_overrides.items() if value is not None})
    return dataclasses.replace(base_cfg, **values)


def combined_version(domain_name: str | None, domain_version: str | None) -> str:
    if domain_name and domain_version:
        return f"{__version__}+{domain_name}.{domain_version}"
    return __version__


def validate_registry_packs(registry: DomainRegistry) -> list[str]:
    errors = list(registry.errors)
    for status in registry.pack_statuses:
        if status.pack is None:
            continue
        if status.status == "error":
            continue
        try:
            validate_pack_recognizer(status.pack)
            status.status = "ok"
            status.reason = None
        except Exception as exc:
            status.status = "error"
            status.reason = str(exc)
            message = f"{status.source.name}: {exc}"
            errors.append(message)
            print(f"error: domain pack {message}", file=sys.stderr, flush=True)
    return errors
