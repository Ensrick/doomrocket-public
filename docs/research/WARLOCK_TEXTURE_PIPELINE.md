# Warlock texture and native-material pipeline

## Status

This document records the evidence and conversion contract for the Warlock
Bombardier model. The production implementation uses:

- Crunch texture sets 01 and 02 for the custom armor and backpack;
- Crunch texture sets 03 and 04 for the rigid launcher and rocket;
- the exact dark-pact Ratling `mtr_outfit` compiled child as the skinned
  three-map adapter for those two custom parts;
- the exact Stormvermin skin, fur, and whisker children already used by the
  source model for its vanilla body parts.

The conversion and binary splice are implemented by
`tools/build_warlock_texture_adapters.py` and
`tools/splice_warlock_materials.ps1`. Built child payloads remain under
`.build/splice`; they derive from installed Fatshark game data and are not
committed.

The body-material work changes texture inputs and compiled child bindings only.
The later v0.1.53 prop pass also replaces the Dalo launcher/projectile render
geometry while preserving the established unit, attachment, muzzle, and
projectile-node contracts. v0.1.54 corrects one rigid-prop hierarchy defect:
the loaded `pRocket` is a child of the physics-owned `pRocketLauncher`, so the
two remain together when AI inventory drops the weapon on death. Neither pass
changes the character skeleton, animation, or body-ragdoll ownership. v0.1.55
then preserves the source weapon rotation, applies only the measured semantic-
grip translation, and excludes the unrigged long tether from the rigid gun.
The user confirmed the resulting body, launcher, and rocket appearance in game,
along with correct hand/back placement and the one-piece loaded death drop.

The v0.1.55 host capture
`C:\Users\danjo\Downloads\console-2026-08-13-02.50.55-72751c68-b9fa-4a86-91d7-55e6a520a98c.log`
contains 20 summaries of `slots=5/5 custom_textures=6/6 resident`. That
telemetry proves the six custom armor/backpack texture resources were resident;
it does not independently identify the weapon's set-03/set-04 pixels. The
weapon and rocket texture result is therefore recorded as direct visual
acceptance, while source conversion, sampler bindings, and compiled residency
remain covered by the offline suites.

The accepted item `3771657344` is public. For multiplayer appearance testing,
every player must subscribe to and enable the same Doomrocket version; the host
controls spawning. Compare host and client views rather than treating public
visibility as evidence that remote rendering or the `source=husk` lane works.

## Authoritative sources

- Source scene: `C:\Users\danjo\Downloads\xud4soo5fg7g8qd4.blend`
- Crunch archive: `C:\Users\danjo\Downloads\zxnu2hjyuovl4rhx.zip`
- Extracted masters:
  `C:\Users\danjo\source\repos\_warlock_bombardier_art\crunch_textures`
- Shipping character FBX: `units/warlock_bombardier/warlock_bombardier_3p.fbx`
- Shipping launcher/projectile FBXs: `units/rocket/pRocketLauncher.fbx` and
  `units/rocket/SM_Rocket.fbx`
- Installed VT2 bundles under the game's `bundle` directory

The archive SHA-256 is
`551852EE9A9FA99995921E4B6B5CF898D4C17B51486E22FE7772D980F92C2187`.
The Blender source SHA-256 is
`AB6EBC9EF45CEA6E402BBD0415C2D40716824552C2AB514947902D1EAC06C1B2`.

## Mesh, material, and texture-set mapping

The Blender source uses separate meshes and shifted UV tiles. They are not a
single UDIM material. Each mesh has its own material and ordinary repeat/wrap
sampling:

| Source mesh | Source material | UV X tile | Crunch set | Resolution |
|---|---|---:|---:|---:|
| `SM_Skaven_WarlockBombardier_Armor` | `DoomRocket_Armor` | 0 | 01 | 2048 |
| `SM_Skaven_WarlockBombardier_Backpack` | `DoomRocket_Backpack` | 1 | 02 | 2048 |
| `SM_Skaven_WarlockBombardier_RcoketLauncher` | `DoomRocket_Weapon` | 2 | 03 | 1024 |
| `SM_Skaven_WarlockBombardier_Rocket` | `DoomRocket_Rocket` | 3 | 04 | 512 |
| `SM_Skaven_WarlockBombardier_Tube` | `DoomRocket_Pipe` | 4 | liquid warpstone | 512 |

The shipping character FBX includes set 01 and 02 as the `DoomRocket_Armor`
and `DoomRocket_Backpack` slots. Crunch's 4,916-vertex presentation launcher
contains a terminal 1,608-vertex backpack-tether block that has no flexible
rig, so the rigid MVP derives and ships the exact retained 3,308-vertex gun.
The 622-vertex rocket keeps its `DoomRocket_Rocket` slot. The carried unit
includes one loaded rocket; the projectile unit uses the same rocket mesh
independently. Neither the deferred long tether nor the distinct 198-vertex
weapon-local conduit is part of the shipping v0.1.55 rigid MVP. See
`docs/research/WARLOCK_WEAPON_PIPELINE.md` for the pinned split and topology
gates.

## UV orientation: do not flip anything

The shipping FBX was imported into Blender 5.2 in memory and compared against
the source scene loop by loop at five decimal places. Direct comparison
contained every source UV:

- armor: 49,683 of 49,683 source UV loops;
- backpack: 41,636 of 41,636 source UV loops;
- body: 19,938 of 19,938;
- fur: 876 of 876;
- whiskers: 180 of 180.

A Y-flipped comparison matched zero armor/backpack loops. Extra shipping loops
are duplicated coordinates produced by triangulation. Therefore the correct
adapter performs no vertical flip, horizontal flip, rotation, tile collapse,
or resampling. Blender versus Maya image conventions are not the defect here.

## Source shader graph and channel meaning

The Blender `V2 Ubershader 1.07` links are explicit:

- `BC.rgb` to Base Color and `BC.a` to Base Color Alpha;
- `NR.rgb` to Normal and `NR.a` to Normal Alpha;
- `Normal Alpha` directly to Principled Roughness;
- `MASE_Fix.rgb` to Maskmap;
- set 02/03/04 `E.rgb` to emission.

The normal alpha is roughness, not gloss. It must remain linear and must not be
inverted. The old inverse-alpha pass reversed the surface response.

Within the source Ubershader, Maskmap R drives metallic directly. G drives the
AO/response path. B is a feature channel. The original MASE A is a localized
emission mask. This last statement is measurable rather than inferred:

- set 01 `E` and MASE A are identically zero;
- sets 02/03/04 have localized MASE A values up to about 0.53;
- after sRGB decoding, set 02 fits
  `E_linear = MASE.a * (0.61224258, 1.32689383, 0.24368675)` with R-squared
  `0.998656 / 0.999846 / 0.993510`.

`MASE_Fix` is intentional. Its R and B are byte-identical to original MASE;
its G is approximately `round(255 * (G / 255)^0.3)` within one byte for every
pixel. It is RGB and therefore has no stored alpha. Using original MASE RGBA
would discard the authored G correction. Using `MASE_Fix` with synthesized
alpha 255 would destroy emission localization.

## Exact adapter conversion

For all four sets, build the following without resampling:

1. `wb_*_df.png` = source `BC` RGBA byte-for-byte.
2. `wb_*_nm.png` = source `NR` RGBA byte-for-byte.
3. `wb_*_ma.png` = `MASE_Fix.rgb + original MASE.a` for the skinned set-01/02
   adapter.

The rigid standard shader used for sets 03/04 has separate samplers. Preserve
BC and NR, and split the authored channels without resampling: NR alpha to
roughness, `MASE_Fix` R to metallic, `MASE_Fix` G to AO, and E RGB to emission.
These files live under `textures/rocket`; the body adapters remain under
`textures/warlock_bombardier`.

Texture descriptors must use:

| Texture | Color space | Compression requirement |
|---|---|---|
| BC | sRGB | alpha-capable BC7 |
| NR | linear | alpha-capable BC7; alpha is roughness |
| packed MASE | linear | alpha-capable BC7; alpha is emission mask |

Do not use BC5 for NR because it would discard roughness alpha. Do not bind the
separate `E` RGB image into the packed mask sampler.

Preserve BC alpha. Source BC01 contains the full 0-255 range and BC02 has
binary 0/255 alpha. The Blender materials link this alpha and are marked for a
dithered surface. The earlier conversion forced alpha to 255 and was not
source-faithful.

## Native compiled material contracts

### Armor and backpack production adapter

Both use the exact Ratling dark-pact `mtr_outfit` child:

- package/bundle resource:
  `units/beings/player/dark_pact_skins/skaven_ratlinggunner/skin_1001/third_person/chr_third_person_mesh`
  / `64f9019d56c8ce61`;
- material: `0488D08E3CE5CBC3.material`;
- size: 768 bytes;
- SHA-256:
  `0D1DA98E59642E000E954A3438A28EDAC63982F1526937DE6A3893C6F0F144EC`;
- parent: `3D25339231384C80`;
- base sampler `F9292771` (`texture_map_02af90f8`);
- packed-mask sampler `909D00F3` (`texture_map_27b67fd2`);
- normal/roughness sampler `9AD51991` (`texture_map_8bf37d8e`).

Armor sets `emissive_color` (`C985395A`) to zero. Backpack sets it to the
linear fit `(0.61224258, 1.32689383, 0.24368675)`. The old `(8, 8, 8)` value
was an over-bright white approximation and did not preserve hue.

The exact Ratling double-sided child `2FFDBB1D607130AD` is retained as an A/B
fallback concept. It preserves its authored double-sided PBR behavior but has
no `emissive_color` reflection, so it deliberately loses the green glow. If
runtime testing finds missing backpack interior/back faces with the production
0488 adapter, compare against 2FFD before searching for a double-sided
emissive parent. Do not change texture conversion during that A/B test.

### Exact source-native body materials

The source's final body, fur, and whiskers are vanilla Stormvermin meshes. The
shipping FBX retains their UVs exactly, so cross-species Globadier, generic fur,
and Laurel feather substitutions are unnecessary and incorrect.

The production splice copies these three children byte-for-byte from
`resource_packages/breeds/skaven_storm_vermin` (bundle
`c43c291e4cc55d96`):

| Slot | Child | Bytes | Parent | SHA-256 |
|---|---|---:|---|---|
| skin | `2CC5FCB51388A255` | 496 | `EE15D2DA0DB8191E` | `15BDECC1897BD62E2EBA055B38388840A95FCA3395CFE9E25A442817ECF16295` |
| fur | `EB663E2D6E5EB732` | 416 | `3BC475F93930640D` | `64E8E88C1D17A54C2A774B3F1FF090B994CAF6620BD8E5C0E857C6D84C3270D2` |
| whiskers | `3EB079055472D4C3` | 128 | `64058AD3567FB490` | `680284D028524BB224667DD4FF14013CF3C52C66CA62CE83E6C392C6CE47571A` |

The splicer verifies every texture binding, not only one representative slot.
The canonical Stormvermin package is loaded explicitly so its native texture
resources remain deterministic rather than relying on whichever level happens
to contain a Stormvermin.

## Reproducible build and validation

Generate texture adapters:

```powershell
py -3 tools/build_warlock_texture_adapters.py
```

Rebuild the rigid props from Crunch's hash-pinned Blender scene with
`tools/prepare_warlock_weapon_fbx.py`. Its output must keep the exact runtime
names `pRocketLauncher`, `pRocket`, `root_point`, `handle`, `p_fx`, and
`a_barrel`; Blender numeric suffixes are a hard failure. The regression suite
also compares every output shape, topology and UV bank with Crunch's isolated
exports and rejects the old Dalo payload hashes.

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' `
  --background 'C:\Users\danjo\Downloads\xud4soo5fg7g8qd4.blend' `
  --python tools/prepare_warlock_weapon_fbx.py -- `
  --launcher-output .build/weapon_candidate/pRocketLauncher.fbx `
  --projectile-output .build/weapon_candidate/SM_Rocket.fbx
```

Do not use a shipping FBX as both `--legacy-*` input and output. By default the
exporter obtains the immutable old node-frame FBXs from pinned Git blobs and
verifies their reviewed SHA-256 values before importing them. Explicit
`--legacy-launcher` and `--legacy-projectile` inputs are accepted only when
their hashes match those baselines, and input/output aliasing is rejected.

### Carried-weapon placement summary

The authoritative attachment, coordinate, semantic-grip, projectile, physics,
offline-test, and runtime-acceptance contract is
`docs/research/WARLOCK_WEAPON_PIPELINE.md`. This texture document retains only
the placement summary needed to avoid rebuilding the correct art with a stale
transform rule.

Crunch's final launcher and loaded rocket are unrigged, unparented
presentation-space props. Their object-world rotation agrees with the pinned
legacy weapon frame after FBX axis normalization, but their object origin is
not a grip locator. The carried-mesh rule is:

```text
v_weapon = Translation(delta_grip) * source_object_world * v_source
delta_grip = (-0.00002098033, -0.91097664833, +0.06153465062) m
```

The translation maps the upper 10 mm cap of Crunch's unique disconnected
217-vertex pistol-grip component onto the reviewed Dalo attachment landmark.
It is applied equally to launcher and loaded rocket and is translation-only.
Do not restore the rejected v0.1.54
`inverse(source_armature_world * j_leftweaponattach_rest)` carried-mesh bake,
and do not use a generic nearest-surface snap: the uncalibrated nearest surface
is the rear stock, not the grip.

The launcher remains under the preserved legacy `root_point` rig. The loaded
rocket remains a direct child of actor-owned `pRocketLauncher`, because the
death-drop `rp_dropped` actor owns only that launcher node. Do not add an
independent loaded-warhead actor. The fired `SM_Rocket` is a separate legacy
projectile-frame normalization path and must not inherit the carried prop's
semantic translation by assumption.

v0.1.54 passed its self-inverting Blender hand-space round trip while appearing
displaced in both hand and back attachments. The weapon pipeline therefore
normalizes Maya/Blender axis metadata, checks the complete model/geometry
chain, identifies the semantic grip rather than an arbitrary surface, and
verifies the final compiled unit is not a stale pre-calibration bundle. Those
placement gates, measurements, and failure signatures live only in the
authoritative weapon document.

Extract, hash-check, and validate all five donor payloads without changing a
built bundle:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File tools/splice_warlock_materials.ps1 -PayloadOnly
```

The normal production order remains build, then material splice, then the
repository's verification/deploy workflow. Never publish an unspliced SDK
bundle, and never use a launcher path that uploads before the splice.

## Runtime acceptance

Test with one living enemy and a non-gibbing corpse, then several simultaneous
enemies. Verify:

- armor and backpack patterns align with the model;
- metallic and AO response are localized rather than uniformly bright;
- rough and smooth regions match the source without alpha inversion;
- green emission is localized and colored, not a white full-surface glow;
- backpack faces remain visible from exterior and interior angles;
- skin, fur, and whiskers match the Stormvermin source appearance;
- material assignment reports 5/5 slots and all six custom armor/backpack
  textures resident;
- no magenta missing-resource material appears.
- the carried launcher is Crunch's final shape with a loaded rocket, uses the
  set-03/set-04 appearance, stays in the left hand, and emits/fires from the
  existing muzzle location;
- after a loaded enemy dies, the launcher and its loaded warhead fall as one
  rigid object; the warhead must neither float at the death pose nor become a
  second independent physics body;
- the fired projectile is Crunch's rocket, travels on the existing forward
  axis, and retains its collision/explosion behavior.

The accepted v0.1.55 host MVP passed this visual inspection, including the
set-03/set-04 launcher and rocket appearance. Visual approval remains a runtime
test for every future art or material change. The source graph, UV orientation,
texture conversion, donor lineage, binary bindings, and package residency are
independently testable offline. The flexible backpack tether, separate short
conduit, and chimney particles remain deliberately deferred and must not be
described as part of this result.
