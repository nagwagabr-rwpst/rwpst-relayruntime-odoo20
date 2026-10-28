# RelayRuntime

WhatsApp campaigns and bulk sending for **Odoo 20 Community**, with a delivery dashboard, operator retry, and live sending through Green API.

| | |
|---|---|
| Version | 20.0.6.1.0 |
| License | LGPL-3 |
| Edition | Odoo Community |
| Technical name | `relayruntime` |

## Install

1. Clone this repository into a directory named `relayruntime` on the Odoo addons path. Odoo uses the directory name as the module name, and the manifest, XML IDs, and assets expect that name.
2. Dependencies: `base`, `sale`, `mail`, `product`, and the Python package `requests` (shipped with Odoo).
3. Update the apps list and install **RelayRuntime**.

```text
git clone https://github.com/nagwagabr-rwpst/rwpst-relayruntime-odoo20.git relayruntime
```

## What it does

- Bulk WhatsApp sending, attachments, and product catalogs
- Campaign history and a delivery dashboard (sent, failed, skipped)
- Operator retry for failed and skipped recipients
- One active provider configuration per company
- Live sending through Green API, and a Mock Provider for demos and tests

The Apps Store description is `static/description/index.html`. `demo.gif` is not referenced by the manifest. `static/description/demo.gif.md` is only a note for a future recording.

## Security notes

Provider tokens are stored on `whatsapp.config`. `access_token` and `webhook_secret` are readable only by the WhatsApp Manager group. Record visibility for configuration, message logs, and campaigns is limited to the active companies.
