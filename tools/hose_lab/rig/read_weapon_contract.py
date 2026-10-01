"""Read authoritative compiled weapon node, without modifying its bundle."""
import sys,json,hashlib,argparse
from pathlib import Path
from _paths import resolve_paths
BASE,REPO=resolve_paths()
sys.path.insert(0,str(REPO/'tools/tests'))
from test_warlock_weapon_pipeline import compiled_bundle_resources,resource_key,compiled_unit_structure,compiled_node_index
payload=compiled_bundle_resources()[resource_key('unit','units/rocket/pRocketLauncher')][0][1]
structure=compiled_unit_structure(payload);node=compiled_node_index(structure,'pRocketLauncher')
result={'sha256':hashlib.sha256(payload).hexdigest(),'node':node,'world':structure.nodes[node].world_transform}
(BASE/'compiled_weapon_node.json').write_text(json.dumps(result,indent=2))
print(result)
