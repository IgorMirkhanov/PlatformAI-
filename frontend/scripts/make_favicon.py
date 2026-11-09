from pathlib import Path

from PIL import Image

src = Path(__file__).resolve().parents[1] / "public" / "mpa-logo.png"
public = Path(__file__).resolve().parents[1] / "public"
app = Path(__file__).resolve().parents[1] / "src" / "app"

im = Image.open(src).convert("RGBA")
w, h = im.size
px = im.load()

# Quote mark occupies the first two white column runs (~0..390).
mark = im.crop((0, 0, 400, h))
mw, mh = mark.size
mp = mark.load()

# Build an alpha mask from bright opaque pixels only (ignore white sheet noise
# with low structure: keep pixels that are bright AND near other bright pixels
# inside the mark cluster). Prefer luminance + alpha.
alpha = Image.new("L", (mw, mh), 0)
ap = alpha.load()
for y in range(mh):
    for x in range(mw):
        r, g, b, a = mp[x, y]
        lum = (r + g + b) / 3
        if a > 128 and lum > 180:
            ap[x, y] = a

# Tight bbox of the mark.
bbox = alpha.getbbox()
if not bbox:
    raise SystemExit("no mark pixels found")
mark_rgb = Image.new("RGBA", (mw, mh), (255, 255, 255, 255))
cropped = Image.composite(mark_rgb, Image.new("RGBA", (mw, mh), (0, 0, 0, 0)), alpha)
cropped = cropped.crop(bbox)

# Square black canvas with padding.
cw, ch = cropped.size
side = int(max(cw, ch) * 1.25)
canvas = Image.new("RGBA", (side, side), (0, 0, 0, 255))
ox = (side - cw) // 2
oy = (side - ch) // 2
canvas.alpha_composite(cropped, (ox, oy))


def save_png(path: Path, size: int) -> None:
    canvas.resize((size, size), Image.Resampling.LANCZOS).save(path)


ico_16 = canvas.resize((16, 16), Image.Resampling.LANCZOS)
ico_32 = canvas.resize((32, 32), Image.Resampling.LANCZOS)
ico_48 = canvas.resize((48, 48), Image.Resampling.LANCZOS)
ico_16.save(
    public / "favicon.ico",
    format="ICO",
    sizes=[(16, 16), (32, 32), (48, 48)],
    append_images=[ico_32, ico_48],
)
save_png(public / "favicon-32x32.png", 32)
save_png(public / "apple-touch-icon.png", 180)
save_png(public / "icon-192.png", 192)
save_png(public / "icon-512.png", 512)
save_png(app / "icon.png", 32)
save_png(app / "apple-icon.png", 180)
print("ok", bbox, side)
