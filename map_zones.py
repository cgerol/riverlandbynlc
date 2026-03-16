"""
Create a side-by-side comparison with grid overlay to manually trace zones.
Also warp the reference image onto the HD image for direct comparison.
"""
from PIL import Image, ImageDraw, ImageFont
import json

def draw_grid(draw, w, h, step=100, color=(255,255,255,80)):
    for x in range(0, w, step):
        draw.line([(x,0),(x,h)], fill=color, width=1)
        draw.text((x+2, 2), str(x), fill=(255,255,0))
    for y in range(0, h, step):
        draw.line([(0,y),(w,y)], fill=color, width=1)
        draw.text((2, y+2), str(y), fill=(255,255,0))

# Load images
hd = Image.open('assets/masterplan-zones.jpg').convert('RGBA')
ref = Image.open('assets/masterplan zones - low res.jpeg').convert('RGBA')

print(f"HD: {hd.size}, Ref: {ref.size}")

# Create grid overlay on HD image
hd_grid = hd.copy()
draw = ImageDraw.Draw(hd_grid)
draw_grid(draw, hd.width, hd.height, step=50)
hd_grid.save('hd_grid.png')
print("Saved hd_grid.png")

# Create grid overlay on reference image
ref_grid = ref.copy()
draw2 = ImageDraw.Draw(ref_grid)
draw_grid(draw2, ref.width, ref.height, step=50)
ref_grid.save('ref_grid.png')
print("Saved ref_grid.png")

# Now let's resize the reference to match HD dimensions and overlay at 50% opacity
ref_resized = ref.resize(hd.size, Image.LANCZOS)
# Blend
blended = Image.blend(hd, ref_resized, alpha=0.5)
draw3 = ImageDraw.Draw(blended)
draw_grid(draw3, hd.width, hd.height, step=100)
blended.save('blended_overlay.png')
print("Saved blended_overlay.png")

# Also create the blended version without grid for cleaner viewing
blended_clean = Image.blend(hd, ref_resized, alpha=0.45)
blended_clean.save('blended_clean.png')
print("Saved blended_clean.png")

print("\nNow visually inspect blended_overlay.png and hd_grid.png")
print("to trace zone boundaries in HD coordinates (1024x1424)")
