"""Validate full saved native assembly against all canonical print meshes."""
from probe_internal_assembly import ROOT,cad as m,volume
import json,re,math,hashlib
OUT=ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1'
native=OUT/'native/numbered-repair';check=native/'saved-check'
src=json.loads((OUT/'evidence.json').read_text());log=(check/'validate.log').read_text(encoding='utf-8-sig').replace('\0','')
assert log.count('This object is a valid ShapeManager solid.')==len(src['parts'])
assert re.search(r'Total errors found\s+0\s+fixed\s+0',log)
assert 'Unknown command' not in log
rows=[]
for part in src['parts']:
    name=part['name'];txt=(check/(name+'-mass.mpr')).read_text()
    v=float(re.search(r'Volume:\s+([\d.E+\-]+)',txt).group(1))
    xyz=[(float(a),float(b)) for a,b in re.findall(r'[XYZ]:\s+([\d.E+\-]+)\s+--\s+([\d.E+\-]+)',txt)[:3]]
    bounds=m.np.array([[a for a,b in xyz],[b for a,b in xyz]])
    expected=m.np.array(part['assembly_bounds_mm']);expected[:,0]+=part['native_offset_x_mm']
    delta=abs(v-part['source_volume_mm3']);db=float(abs(bounds-expected).max())
    assert delta<.1 and db<.0001,(name,delta,db)
    disk=m.trimesh.load(OUT/'stl'/(name+'.stl'),force='mesh');disk.apply_transform(part['print_to_assembly']);disk.apply_translation([part['native_offset_x_mm'],0,0])
    raw=m.trimesh.load(check/(name+'.stl'),force='mesh');relocation=m.np.where(bounds[0]<0,1e-6-bounds[0],0.);raw.apply_translation(-relocation)
    assert abs(raw.bounds-bounds).max()<.0001
    item={'name':name,'volume_delta_mm3':delta,'bounds_delta_mm':db,'raw_export_closed':bool(raw.is_watertight),
          'raw_export_winding_consistent':bool(raw.is_winding_consistent),'stl_positive_octant_relocation_mm':relocation.tolist()}
    if raw.is_watertight and raw.is_winding_consistent:
        extra=volume(m.dif(raw,disk));missing=volume(m.dif(disk,raw))
        assert math.isfinite(extra+missing) and max(extra,missing)<.1,(name,extra,missing)
        item.update(extra_boundary_mm3=extra,missing_boundary_mm3=missing)
    rows.append(item)
draw=native/'PitchComm-slider-v7-complete.dwg'
report={'passed':True,'kernel_valid_solids':len(rows),'audit_errors':0,'parts':rows,'drawing_sha256':hashlib.sha256(draw.read_bytes()).hexdigest(),
        'scope':'Complete 34 printed candidate parts. Hardware references/wires are modeled clearance envelopes, not drawing solids. Canonical prepared STL/3MF files are the print artifacts.'}
(check/'evidence.json').write_text(json.dumps(report,indent=2))
print('PASS:',len(rows),'reopened valid solids; native volume/bounds match; raw exports closed',sum(r['raw_export_closed'] for r in rows))
