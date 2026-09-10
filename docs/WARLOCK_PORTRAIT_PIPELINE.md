# Warlock Engineer kill-feed portrait

## Source and runtime identity

The September 7 handoff contains a 60x70 and a 110x130 PNG. Only the 60x70
image is used. It is copied without modification to
`textures/unit_frame_portrait_enemy_doomrocket.png`; the larger image remains
outside the mod. The small source SHA-256 is
`62dfcc74716e983a865231de9e54a04cda4d009df62cde6d72a017865694d613`.
It is RGB, with no alpha channel. Preserve the supplied background; do not
infer transparency from black pixels, crop, rescale, sharpen, or pre-flip it.

| Asset | Role |
| --- | --- |
| `textures/unit_frame_portrait_enemy_doomrocket.png` | Exact artist-supplied input |
| `textures/doomrocket/doomrocket_atlas.dds` | Generated 128x128 atlas, with the 60x70 input at its upper-left and transparent padding |
| `textures/doomrocket/doomrocket_atlas.texture` | Existing uncompressed, alpha-preserving texture recipe |
| `materials/doomrocket/doomrocket_atlas.lua` | Entry `unit_frame_portrait_enemy_doomrocket`, size 60x70, UVs (0,0) to (0.46875,0.546875) |
| `materials/doomrocket/doomrocket_atlas.material` | Existing GUI material variants |
| `scripts/mods/doomrocket/doomrocket_data.lua` | VMF atlas registration and in-game renderer injection |
| `scripts/mods/doomrocket/doomrocket.lua` | Maps the `skaven_doomrocket` breed to the portrait entry |

The game code in `scripts/ui/views/positive_reinforcement_ui.lua` selects
`UISettings.breed_textures` and takes the rendered dimensions from the atlas
entry. Its widget in `positive_reinforcement_ui_definitions.lua` does not draw
a separate enemy portrait frame. It mirrors the second portrait in the normal
kill-feed layout; the input must not compensate for that native mirroring.

## Rebuild and verify

```powershell
py -3 tools/build_doomrocket_portrait_atlas.py
py -3 tools/tests/test_doomrocket_portrait_pipeline.py
```

The builder is asset packing, not an art-editing pass: it preserves the
provided pixels, rejects the wrong dimensions, and writes the existing DDS
layout. Changing the standalone PNG without regenerating the DDS leaves the
old portrait in game. The full release pipeline runs the portrait checks
again against the clean compiled package before an upload is allowed.

The SDK's compiled texture channel storage must be distinguished from a
generic image decoder's interpretation. Do not compensate by recoloring or
swapping the source artwork based only on a decoded compiled DDS. Native
in-game colors still require visible acceptance.

## Runtime acceptance

1. Wait for explicit Workshop publication confirmation and verify the exact
   candidate load banner. For v0.1.56-alpha, enable only the public alpha on
   all participants; disable TEST.
2. Kill an Engineer and compare its kill-feed portrait with the supplied PNG.
   Require the new image, correct red warhead/green highlights, native size,
   and no unexpected crop, atlas padding, halo, or extra frame.
3. Compare its placement with another special's kill-feed portrait. Allow the
   game's normal attacker/victim mirroring; do not pre-flip the artwork.
4. Check the host and a remote client, including Engineer-caused player kills
   where practical. Capture a screenshot or video and both complete logs.

Offline and compiled checks do not certify native shader rendering or
multiplayer visibility. Leave runtime acceptance pending until those results
are supplied.
