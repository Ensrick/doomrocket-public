"""Pure verification helpers. No SDK, Blender, artist assets or optional packages."""
from collections import Counter, defaultdict
import itertools
import math


class VerificationError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise VerificationError(message)


def matrix_multiply(a, b):
    return tuple(tuple(sum(a[r][k]*b[k][c] for k in range(4)) for c in range(4)) for r in range(4))


def transform_point(matrix, point):
    return tuple(sum(matrix[r][c]*(*point, 1)[c] for c in range(4)) for r in range(3))


def check_matrix(matrix):
    require(len(matrix) == 4 and all(len(row) == 4 for row in matrix), 'Expected 4x4 matrix')
    require(all(math.isfinite(x) for row in matrix for x in row), 'Nonfinite matrix')


def inverse(matrix):
    check_matrix(matrix)
    work = [list(row)+[float(r == c) for c in range(4)] for r, row in enumerate(matrix)]
    for col in range(4):
        pivot = max(range(col, 4), key=lambda r: abs(work[r][col]))
        require(abs(work[pivot][col]) > 1e-12, 'Singular matrix')
        work[col], work[pivot] = work[pivot], work[col]
        divisor = work[col][col]
        work[col] = [x/divisor for x in work[col]]
        for r in range(4):
            if r != col:
                factor = work[r][col]
                work[r] = [v-factor*w for v, w in zip(work[r], work[col])]
    result = tuple(tuple(row[4:]) for row in work)
    check_matrix(result)
    return result


def parse_faces(encoded, vertex_count):
    faces, current = [], []
    for value in encoded:
        require(isinstance(value, int), 'Noninteger source polygon index')
        index = -value-1 if value < 0 else value
        require(0 <= index < vertex_count, 'Source polygon index out of bounds')
        current.append(index)
        if value < 0:
            require(len(current) in (3, 4) and len(set(current)) == len(current), 'Invalid source triangle/quad')
            faces.append(tuple(current))
            current = []
    require(not current and faces, 'Unterminated or empty source polygon stream')
    return faces


def weld_positions(points, tolerance=1e-6):
    require(math.isfinite(tolerance) and tolerance > 0, 'Invalid weld tolerance')
    canonical, members, mapping = [], [], []
    buckets = defaultdict(list)
    for source, point in enumerate(points):
        require(len(point) == 3 and all(math.isfinite(x) for x in point), 'Nonfinite source vertex')
        key = tuple(math.floor(x/tolerance) for x in point)
        candidates = []
        for offset in itertools.product((-1, 0, 1), repeat=3):
            for index in buckets[tuple(a+b for a, b in zip(key, offset))]:
                if math.dist(point, canonical[index]) < tolerance:
                    candidates.append(index)
        if candidates:
            index = min(candidates)
            require(all(math.dist(point, points[j]) < tolerance for j in members[index]), 'Ambiguous seam weld')
        else:
            index = len(canonical)
            canonical.append(tuple(point))
            members.append([])
            buckets[key].append(index)
        members[index].append(source)
        mapping.append(index)
    return canonical, members, mapping


def map_positions(points, source, tolerance=.001):
    require(source, 'No canonical source vertices')
    mapping, maximum = [], 0.0
    for vertex, point in enumerate(points):
        require(len(point) == 3 and all(math.isfinite(x) for x in point), f'Nonfinite compiled vertex {vertex}')
        nearest = min(range(len(source)), key=lambda j: math.dist(point, source[j]))
        error = math.dist(point, source[nearest])
        require(error < tolerance, f'Compiled vertex {vertex} deviates {error} m')
        maximum = max(maximum, error)
        mapping.append(nearest)
    require(set(mapping) == set(range(len(source))), 'Incomplete canonical source vertex coverage')
    return mapping, maximum


def cyclic_face(face):
    return min(face[i:]+face[:i] for i in range(len(face)))


def edge_balance(faces):
    counts = Counter()
    for face in faces:
        for a, b in zip(face, face[1:]+face[:1]):
            require(a != b, 'Collapsed face edge')
            counts[tuple(sorted((a, b)))] += 1 if a < b else -1
    return {edge: count for edge, count in counts.items() if count}


def validate_topology(faces, source_mapping, triangles, compiled_mapping):
    """Oriented polygon coverage permits either legal quad diagonal."""
    polygon_counts, vertex_faces = Counter(), defaultdict(set)
    for face in faces:
        require(all(0 <= v < len(source_mapping) for v in face), 'Source face index out of bounds')
        mapped = tuple(source_mapping[v] for v in face)
        require(len(mapped) in (3, 4) and len(set(mapped)) == len(mapped), 'Collapsed/unsupported source polygon')
        key = cyclic_face(mapped)
        polygon_counts[key] += 1
        for vertex in key:
            vertex_faces[vertex].add(key)
    require(set(vertex_faces) == set(source_mapping), 'Source contains unused canonical vertices')
    require(set(compiled_mapping) == set(source_mapping), 'Incomplete canonical source vertex coverage')
    expected_count = sum((len(face)-2)*count for face, count in polygon_counts.items())
    require(len(triangles) == expected_count, 'Missing or extra compiled triangles')
    assigned, referenced = defaultdict(list), set()
    for triangle in triangles:
        require(len(triangle) == 3 and all(isinstance(v, int) and 0 <= v < len(compiled_mapping) for v in triangle), 'Invalid compiled triangle index')
        referenced.update(triangle)
        mapped = tuple(compiled_mapping[v] for v in triangle)
        require(len(set(mapped)) == 3, 'Collapsed compiled triangle')
        candidates = set.intersection(*(vertex_faces[v] for v in mapped))
        require(len(candidates) == 1, 'Triangle does not identify exactly one source polygon')
        assigned[next(iter(candidates))].append(mapped)
    require(referenced == set(range(len(compiled_mapping))), 'Compiled asset contains unreferenced vertices')
    for face, multiplicity in polygon_counts.items():
        actual = assigned[face]
        require(len(actual) == (len(face)-2)*multiplicity, f'Wrong triangle coverage for polygon {face}')
        require(edge_balance(actual) == edge_balance([face]*multiplicity), f'Winding/boundary mismatch for polygon {face}')
    return {'source_polygons': len(faces), 'canonical_polygon_groups': len(polygon_counts),
            'triangles': expected_count, 'canonical_vertices': len(set(source_mapping)),
            'complete_vertex_coverage': True, 'oriented_polygon_coverage': True}


def decode_influences(indices, weights, palette, skin_nodes, node_names):
    """Check all four slots before filtering zeros; NaN is never unused."""
    require(len(indices) == len(weights) == 4, 'Expected four skin slots')
    positive = {}
    for index, weight in zip(indices, weights):
        require(math.isfinite(weight) and 0 <= weight <= 1, 'Nonfinite/negative/out-of-range skin weight')
        require(isinstance(index, int) and 0 <= index < len(palette), 'Palette index out of bounds')
        skin_index = palette[index]
        require(isinstance(skin_index, int) and 0 <= skin_index < len(skin_nodes), 'Skin matrix index out of bounds')
        node = skin_nodes[skin_index]
        if weight > 0:
            require(node in node_names, 'Positive influence references a non-control node')
            name = node_names[node]
            positive[name] = positive.get(name, 0.0)+weight
    require(abs(sum(positive.values())-1) <= .0005, 'Skin weights do not sum to one')
    return positive


def weighted_point(point, influences, transforms):
    require(influences, 'Vertex has no influences')
    result = [0.0, 0.0, 0.0]
    for name, weight in influences.items():
        require(math.isfinite(weight) and weight >= 0, 'Invalid weighted influence')
        require(name in transforms, 'Missing bone transform')
        p = transform_point(transforms[name], point)
        for axis in range(3):
            result[axis] += p[axis]*weight
    require(all(math.isfinite(x) for x in result), 'Nonfinite weighted vertex')
    return tuple(result)


def pose_targets(controls, trial):
    result = {}
    for index, control in enumerate(controls):
        rest = control['frame']
        if trial == 0:
            result[control['name']] = rest
            continue
        ax = math.sin(index*.37+trial)*(.15+trial*.1)
        az = math.cos(index*.29+trial)*.2
        rx = ((1,0,0,0),(0,math.cos(ax),-math.sin(ax),0),(0,math.sin(ax),math.cos(ax),0),(0,0,0,1))
        rz = ((math.cos(az),-math.sin(az),0,0),(math.sin(az),math.cos(az),0,0),(0,0,1,0),(0,0,0,1))
        shift = ((1,0,0,.05*math.sin(index*.23+trial)),(0,1,0,.07*math.cos(index*.19+trial)),(0,0,1,.04*math.sin(index*.31)),(0,0,0,1))
        result[control['name']] = matrix_multiply(matrix_multiply(shift, rest), matrix_multiply(rx, rz))
    return result


def validate_deformation(source_points, source_weights, compiled_points, compiled_weights,
                         compiled_mapping, canonical_members, controls, profiles, tolerance=.002):
    """Compare actual weighted vertices under three distinct per-bone pose sets."""
    errors = []
    for trial in range(3):
        targets = pose_targets(controls, trial)
        source_transforms = {c['name']: matrix_multiply(targets[c['name']], inverse(c['frame'])) for c in controls}
        compiled_transforms = {p['name']: matrix_multiply(matrix_multiply(targets[p['name']], p['control_to_compiled_bone']), p['compiled_inverse_bind']) for p in profiles}
        maximum = 0.0
        for vertex, point in enumerate(compiled_points):
            source = canonical_members[compiled_mapping[vertex]][0]
            expected = weighted_point(source_points[source], source_weights[source], source_transforms)
            actual = weighted_point(point, compiled_weights[vertex], compiled_transforms)
            maximum = max(maximum, math.dist(expected, actual))
        require(maximum < tolerance, f'Weighted LBS mismatch in pose {trial}: {maximum} m')
        errors.append(maximum)
    return errors
