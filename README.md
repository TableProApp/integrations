# TablePro integrations

The registry behind the TablePro integrations directory: apps, extensions and tools that work with [TablePro](https://tablepro.app).

Each entry is a folder in `integrations/` with an `integration.json` manifest and a 512x512 `icon.png`. A pull request adds or changes one entry, CI checks it, and a maintainer reviews it against the [listing policy](POLICY.md).

To list your integration, read [CONTRIBUTING.md](CONTRIBUTING.md).

## Layout

| Path | Holds |
| --- | --- |
| `integrations/<slug>/` | `integration.json`, `icon.png`, optional `screenshot-1.png` to `screenshot-4.png` |
| `schema/` | JSON Schema 2020-12 for manifests, curation files and the published index |
| `curation/` | Maintainer files: official publishers, partners, reserved names, removed entries, protected icons, accepted scan hits |
| `scripts/` | `validate.py`, `build.py` (the published data), `health.py` (the weekly check), the shared `registry.py`, and their tests |
| `_owner/` | Repository settings and rulesets, applied once by an org owner |

## License

Code and schemas: [MIT](LICENSE). Manifest text: [CC0-1.0](LICENSE-DATA). Icons and screenshots stay their owners' property. TablePro is a trademark of Ngo Quoc Dat, see [tablepro.app/brand](https://tablepro.app/brand).
