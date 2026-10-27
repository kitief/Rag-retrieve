from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "icons"
OUT.mkdir(parents=True, exist_ok=True)

BLUE = (14, 165, 233, 255)
WHITE = (255, 255, 255, 235)


def make(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = max(1, size // 16)
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=max(2, size // 5),
        fill=BLUE,
    )
    w = size * 0.46
    h = size * 0.5
    cx, cy = size / 2, size / 2
    d.rounded_rectangle(
        [cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2],
        radius=max(1, size // 20),
        fill=WHITE,
    )
    line_w = max(1, size // 26)
    for i in range(3):
        y = cy - h / 2 + h * (0.28 + 0.2 * i)
        d.line(
            [cx - w / 2 + w * 0.16, y, cx + w / 2 - w * 0.16, y],
            fill=BLUE,
            width=line_w,
        )
    return img


for s in (32, 128, 256, 512):
    make(s).save(OUT / f"{s}x{s}.png")
make(256).save(OUT / "128x128@2x.png")
make(256).save(OUT / "icon.png")
make(512).save(
    OUT / "icon.ico",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print("icons:", sorted(p.name for p in OUT.iterdir()))
