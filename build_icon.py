"""Generate FOOCUS's multi-resolution Windows icon with a smooth infinity mark."""
from math import pi, sin
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "static" / "foocus.ico"
SIZE = 256
SCALE = 4
image = Image.new("RGBA", (SIZE * SCALE, SIZE * SCALE), (23, 25, 43, 255))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle(
    (8 * SCALE, 8 * SCALE, 248 * SCALE, 248 * SCALE),
    radius=52 * SCALE,
    fill=(23, 25, 43, 255),
)

# Use a smooth infinity motif in FOOCUS's purple-to-blue brand colors.
points = []
for index in range(481):
    angle = 2 * pi * index / 480
    x = 128 + 82 * sin(angle)
    y = 128 + 48 * sin(2 * angle)
    points.append((round(x * SCALE), round(y * SCALE)))

for index in range(len(points) - 1):
    ratio = index / max(1, len(points) - 2)
    start = (139, 120, 255)
    end = (59, 130, 246)
    color = tuple(round(a + (b - a) * ratio) for a, b in zip(start, end)) + (255,)
    draw.line((points[index], points[index + 1]), fill=color, width=12 * SCALE)

image = image.resize((SIZE, SIZE), Image.Resampling.LANCZOS)
OUTPUT.parent.mkdir(parents=True, exist_ok=True)
image.save(
    OUTPUT,
    format="ICO",
    sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
)
print(f"Generated {OUTPUT}")
