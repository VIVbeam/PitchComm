"""Render the complete serialized v8 assemblies and actual plate positions."""
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
source=(ROOT/'.tools/cad-source/render_complete_slider_pack.py').read_text(encoding='utf-8')
source=source.replace("OUT=ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1'", "OUT=ROOT/'.tools/cad-runs/pull-sling-v3'")
source=source.replace("src=json.loads((OUT/'evidence.json').read_text());study=json.loads((OUT.parent/'evidence.json').read_text())", "src={'parts':json.loads((OUT/'evidence.json').read_text())['printed_parts'],'styles':json.loads((ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1/evidence.json').read_text())['styles']};study=json.loads((ROOT/'.tools/cad-runs/side-slider-v7/evidence.json').read_text())")
source=source.replace('complete-closed-open-v2.png','complete-closed-open-v3.png').replace('print-plates-preview-v2.png','print-plates-preview-v3.png')
exec(compile(source,'v8-serialized-preview','exec'))
