"""Encode rendered simulation frames; no regeneration or image manipulation."""
from PIL import Image
from pathlib import Path
from _paths import resolve_paths
BASE,REPO=resolve_paths()
paths=sorted((BASE/'demo_frames').glob('*.png'));assert len(paths)==60
frames=[Image.open(p).convert('RGB') for p in paths]
palette=frames[0].quantize(colors=192)
encoded=[f.quantize(palette=palette,dither=Image.Dither.NONE) for f in frames]
output=BASE/'offline_hose_physics_demo.gif'
encoded[0].save(output,save_all=True,append_images=encoded[1:],duration=[30,30,40]*20,loop=0,optimize=True,disposal=1)
print('GIF',output,output.stat().st_size)
