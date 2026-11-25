# Custom domain packs

A custom domain pack (`.tpack`) contains a manifest, a recognizer, its matching vocabulary,
and optionally a layout model. It lets you add your own domain, such as a recognizer
fine-tuned for one collection or language, without copying its models into the TuzkaOCR
package. A pack may also be an unpacked folder containing `domain.json` and the referenced
files.

## Install a pack

For a pip installation, copy the `.tpack` file into
`~/.local/share/tuzkaocr/domains/`, or into `$XDG_DATA_HOME/tuzkaocr/domains/` when
`XDG_DATA_HOME` is set. You can choose another folder with `TUZKAOCR_DOMAINS_DIR`.
Restart the CLI or service after adding a pack.

For Compose, put the pack in the checkout's `domains/` directory. Compose mounts that folder
read-only at `/app/domains` and stores extracted zip contents in a writable temporary cache.
To build an image with a pack built in, use the published image as a base and copy the pack
into it:

```dockerfile
FROM ghcr.io/moravianlibrary/tuzkaocr:1.11.1
COPY sk-theses.tpack /app/domains/
```

Pack files are not part of the repository; Git ignores `domains/*.tpack`.

## Check the installation

Run these flags from a checkout or installed CLI; none needs an input image:

```bash
python cli.py --list-domains
python cli.py --check-domains
python cli.py --version
```

`--list-domains` shows built-in, loaded, and skipped domains. `--check-domains` checks each
pack's manifest, checksums, recognizer, and vocabulary, and exits non-zero if any pack is
invalid. A malformed non-default pack is skipped with a warning. A malformed default pack,
duplicate pack names, or multiple default packs stop startup so the generic model is not
selected silently.

## Select a domain

When a pack declares itself as the default, `--domain default` (or omitting `--domain`) uses
it. The API uses the same choice when `domain` is omitted or set to `default`. Select any
loaded pack explicitly with its name:

```bash
python cli.py page.tif --domain sk-theses
```

`--domain print` always selects the built-in print domain, even when a pack is the default.
The API's `domain=print` has the same bypass behavior. Set `TUZKAOCR_DEFAULT_DOMAIN` to a
loaded domain name to override the manifest default; set it to `print` to use the built-in
print domain by default.

Pack settings inherit the selected base domain. Pack settings override base settings, explicit
`TUZKAOCR_*` environment values override the pack, and CLI flags or API form fields override
both where those controls are available. Values that come only from the bundled
`tuzkaocr.env` are defaults, not explicit settings, so they never override a pack.

## Version reporting

Without a custom domain, the reported version is the core version, such as `1.11.1`. Output
made with a pack includes its name and version as build metadata, such as
`1.11.1+sk-theses.1.0`. The CLI reports the active default pack with `--version`; API clients
can query the authenticated `/api/v1/version` endpoint. ALTO records the combined version in
`softwareVersion` and identifies the pack in `applicationDescription`.

The unauthenticated `/healthz` response reports only the core version and whether any valid
custom packs are loaded; it never includes pack names.

## Pack errors

| Message or condition | What to do |
|---|---|
| `sha256 mismatch for <file>` | Replace the damaged pack with the original file from its provider. |
| `unsupported requires_tuzkaocr clause` or version does not satisfy the requirement | Install a pack built for this TuzkaOCR version, or use a compatible release. |
| `unknown setting key '<key>'` | Remove the unsupported setting and rebuild the pack. |
| `unsafe zip member` or nested directories are not allowed | Ask the provider for a pack with files only at its root. |
| `default domain pack ... is invalid` | Fix or remove that pack before restarting; a default pack must load successfully. |
| duplicate domain name or multiple default packs | Keep one pack per name and at most one manifest default. |
| `model <file> expects N classes, vocab <file> covers M` | Use the matching vocabulary shipped with that recognizer. A custom recognizer always comes with its own vocab. |
| `Unknown domain` | Check `--list-domains` or `/api/v1/models`, then use a listed name. |

Two-file page-style recognizers must include their `.style.onnx` sidecar beside the recognizer.
The pack builder copies that sidecar automatically when it exists.
