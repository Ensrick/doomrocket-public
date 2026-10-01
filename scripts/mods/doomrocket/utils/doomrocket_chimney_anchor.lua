-- Measured tall-chimney top lip; not the decorative spikes or hose outlet.
-- Provenance/geometry gates: tools/fixtures/warlock_chimney_anchor.json and
-- tools/tests/test_doomrocket_chimney_anchor.py. Remeasure after an art change.
-- All 32 lip vertices are rigidly weighted to j_backpack in source, FBX, and
-- compiled skin. This frame is inverse_bind_j_backpack * Translation(lip)
-- in column-vector notation: the same transformation used by those vertices.
-- Arrays below are Stingray basis vectors (columns in that notation), not
-- rows to transpose. Their 0.01 scale cancels the compiled scale-100 wrapper.
-- Do not normalize the axes or apply the Blender metre offset here.
-- Native fx/chr_warp_fire_backpack_smoke_01 emits along its local +Z axis.
return {
	node = "j_backpack",
	x_axis = { 0.0025734149385243654, -0.00959326047450304, 0.00116046704351902 },
	y_axis = { 0.009537847712635994, 0.002714452799409628, 0.001288804691284895 },
	z_axis = { -0.001551389112137258, 0.0007751737139187753, 0.009848457761108875 },
	position = { 0.00010618387103213372, 0.0036664297743104622, 0.008681312697815679 },
}
