# Odoo App Store Assets

Synced from repository `branding/` (official hexagonal RelayRuntime identity).

| File | Status | Notes |
|------|--------|-------|
| `AppIcon.png` | Present | Manifest `icon` + store mark (canonical) |
| `AppIcon.svg` | Present | Vector mark |
| `icon.png` | Present (256×256) | Compatibility alias of `AppIcon.png` for tooling that probes `icon.png` |
| `HorizontalLogo.png` / `.svg` | Present | Official horizontal lockup |
| `VerticalLogo.png` / `.svg` | Present | Official vertical lockup |
| `banner.png` | Present (1260×630) | Store cover |
| `banner_1.png` / `.jpg` | Present | Hero / marketing banner |
| `index.html` | Present | Store description (RWPST / 20.0.6.1.0) |
| `screenshots/01_command_center.png` | Present | Command Center |
| `screenshots/02_settings.png` | Present | Settings |
| `screenshots/03_bulk_wizard.png` | Present | Bulk wizard |
| `screenshots/06_delivery_dashboard.png` | Present | Delivery Dashboard |
| `screenshots/04_*.png`, `05_*.png` | Optional / missing | See `screenshots/README.md` |
| `demo.gif` | Optional / missing | Short Mock Provider demo |

## Removed / stale (do not restore)

- `icon.svg`, `icon_128.png` — legacy circular marks  
- `AppIcon.jpg`, `HorizontalLogo.jpg`, `VerticalLogo.jpg` — superseded by PNG/SVG  

## Manifest

```python
'icon': '/relayruntime/static/description/AppIcon.png',
'images': [
    'static/description/banner_1.png',
    'static/description/AppIcon.png',
    'static/description/screenshots/01_command_center.png',
    'static/description/screenshots/02_settings.png',
    'static/description/screenshots/03_bulk_wizard.png',
    'static/description/screenshots/06_delivery_dashboard.png',
],
```
