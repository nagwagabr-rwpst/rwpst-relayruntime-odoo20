"""Generate RWPST RelayRuntime brand palette reference image."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent / "RWPST_RelayRuntime_ColorPalette.png"
W, H = 1400, 2200
BG = "#F8FAFC"
TEXT = "#0F172A"
MUTED = "#64748B"

def hex_to_rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))

def darken(hex_color, pct=10):
    r, g, b = hex_to_rgb(hex_color)
    f = 1 - pct / 100
    return "#{:02X}{:02X}{:02X}".format(int(r * f), int(g * f), int(b * f))

def lighten(hex_color, pct=12):
    r, g, b = hex_to_rgb(hex_color)
    f = pct / 100
    return "#{:02X}{:02X}{:02X}".format(
        min(255, int(r + (255 - r) * f)),
        min(255, int(g + (255 - g) * f)),
        min(255, int(b + (255 - b) * f)),
    )

PALETTE = {
    "Primary Brand": [
        ("Navy — App Identity", "#0F172A", "Headers, nav, primary text"),
        ("Indigo Deep", "#1E3A8A", "Sidebar, hero bands, emphasis"),
        ("Relay Blue", "#2563EB", "CTAs, links, active nav"),
        ("WhatsApp Green", "#25D366", "Messaging accent, WA actions"),
        ("Vibrant Orange", "#F97316", "Highlights, badges, energy"),
    ],
    "Tile Colors (Launcher Icons)": [
        ("Tile 1 — Projects Hub", "#4F46E5", "Project launcher / hub"),
        ("Tile 2 — Contacts", "#0D9488", "CRM & contact directory"),
        ("Tile 3 — Templates", "#0891B2", "Message templates"),
        ("Tile 4 — Campaigns", "#EA580C", "Outbound campaigns"),
        ("Tile 5 — Inbox", "#16A34A", "Live conversations"),
        ("Tile 6 — Analytics", "#7C3AED", "Reports & insights"),
        ("Tile 7 — Settings", "#475569", "Config & admin"),
    ],
    "Lifecycle Funnel Gradient": [
        ("Stage 1 — Draft / Lead", "#94A3B8", "Draft, prospect, idle"),
        ("Stage 2 — Scheduled", "#60A5FA", "Queued, scheduled send"),
        ("Stage 3 — Sent / Engaged", "#34D399", "Sent, delivered, active"),
        ("Stage 4 — Converted / Read", "#1E40AF", "Read, won, completed"),
    ],
    "Alerts & KPI Secondary": [
        ("Success / KPI Up", "#22C55E", "Positive delta, healthy"),
        ("Warning / KPI Watch", "#F59E0B", "Threshold, pending"),
        ("Danger / KPI Down", "#EF4444", "Error, failed, critical"),
        ("Info / Neutral KPI", "#3B82F6", "Informational metric"),
    ],
}

def load_font(size, bold=False):
    names = [
        "C:/Windows/Fonts/segoeuib.ttf" if bold else "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
    ]
    for n in names:
        try:
            return ImageFont.truetype(n, size)
        except OSError:
            continue
    return ImageFont.load_default()

def draw_swatch(draw, x, y, sw, sh, color, title, subtitle, fonts):
    r, g, b = hex_to_rgb(color)
    draw.rounded_rectangle([x, y, x + sw, y + sh], radius=12, fill=color, outline="#E2E8F0", width=1)
    # hover strip
    hover = darken(color, 8) if sum(hex_to_rgb(color)) > 380 else lighten(color, 10)
    draw.rounded_rectangle([x + sw - 52, y + 8, x + sw - 8, y + 28], radius=6, fill=hover)
    active = darken(color, 14) if sum(hex_to_rgb(color)) > 380 else darken(color, 6)
    draw.rounded_rectangle([x + sw - 52, y + 32, x + sw - 8, y + 52], radius=6, fill=active)
    hov_font = fonts["tiny"]
    draw.text((x + sw - 50, y + 10), "Hov", fill="#FFFFFF" if sum(hex_to_rgb(hover)) < 400 else TEXT, font=hov_font)
    draw.text((x + sw - 50, y + 34), "Act", fill="#FFFFFF" if sum(hex_to_rgb(active)) < 400 else TEXT, font=hov_font)

    tx = x + sw + 16
    draw.text((tx, y + 4), title, fill=TEXT, font=fonts["label"])
    draw.text((tx, y + 28), f"HEX {color}   RGB({r}, {g}, {b})", fill=MUTED, font=fonts["code"])
    draw.text((tx, y + 50), f"Hover {hover}   Active {active}", fill=MUTED, font=fonts["tiny"])
    draw.text((tx, y + 72), subtitle, fill=MUTED, font=fonts["tiny"])

def main():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    fonts = {
        "title": load_font(32, True),
        "section": load_font(20, True),
        "label": load_font(15, True),
        "code": load_font(13),
        "tiny": load_font(11),
        "note": load_font(12),
    }

    y = 40
    draw.text((48, y), "RWPST RelayRuntime", fill=TEXT, font=fonts["title"])
    y += 44
    draw.text((48, y), "Brand Color Palette — Enterprise SaaS Dashboard", fill=MUTED, font=fonts["section"])
    y += 36
    draw.line([(48, y), (W - 48, y)], fill="#E2E8F0", width=2)
    y += 28

    sw, sh = 88, 88
    for section, items in PALETTE.items():
        draw.text((48, y), section, fill="#1E3A8A", font=fonts["section"])
        y += 36
        for title, color, sub in items:
            draw_swatch(draw, 48, y, sw, sh, color, title, sub, fonts)
            y += sh + 20
        y += 16

    notes = [
        "Hover / Active state guidelines:",
        "• Tiles & buttons: darken fill 8% on hover, 14% on active (light colors: lighten 10% / darken 6%).",
        "• Primary CTAs (Relay Blue): hover #1D4ED8, active #1E40AF with 2px focus ring #93C5FD.",
        "• WhatsApp actions: hover #20BD5A, active #1DA851; keep white icon/text.",
        "• KPI badges: use 12% tinted backgrounds (e.g. success bg #DCFCE7) with solid border on hover.",
        "• Funnel gradient: interpolate stages left→right; hover stage lifts 4px with stage color at 90% opacity.",
    ]
    draw.rounded_rectangle([48, y, W - 48, y + 200], radius=12, fill="#FFFFFF", outline="#E2E8F0")
    ny = y + 16
    for i, line in enumerate(notes):
        draw.text((64, ny), line, fill=TEXT if i == 0 else MUTED, font=fonts["label"] if i == 0 else fonts["note"])
        ny += 28 if i == 0 else 24

    # footer gradient bar (funnel preview)
    bar_y = H - 72
    stages = [c for _, c, _ in PALETTE["Lifecycle Funnel Gradient"]]
    seg = (W - 96) // len(stages)
    for i, c in enumerate(stages):
        draw.rectangle([48 + i * seg, bar_y, 48 + (i + 1) * seg, bar_y + 24], fill=c)
    draw.text((48, bar_y - 22), "Funnel gradient preview →", fill=MUTED, font=fonts["tiny"])

    img.save(OUT, "PNG", optimize=True)
    print(f"Saved: {OUT}")

if __name__ == "__main__":
    main()
