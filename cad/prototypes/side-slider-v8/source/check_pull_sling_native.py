"""Verify independently reopened printable and nonprinted native solids."""
from probe_internal_assembly import ROOT,cad as m,volume
import json,re,math,hashlib,zipfile,xml.etree.ElementTree as ET
OUT=ROOT/'.tools/cad-runs/pull-sling-v3';native=OUT/'native';check=native/'reopen'
src=json.loads((OUT/'evidence.json').read_text())
log=(check/'validate.log').read_text(encoding='utf-8-sig').replace('\0','')
assert log.count('This object is a valid ShapeManager solid.')==46
assert re.search(r'Total errors found\s+0\s+fixed\s+0',log) and 'Unknown command' not in log
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'};refs={}
for style in ('receiver','wrist','keypad'):
    with zipfile.ZipFile(OUT/'references'/f'{style}_battery_access.3mf') as z:root=ET.fromstring(z.read('3D/3dmodel.model'))
    for obj in root.findall('c:resources/c:object',NS):
        if obj.attrib['name'] not in {r['name'] for r in src['reference_parts']}:continue
        vs=[[float(v.attrib[k]) for k in ('x','y','z')] for v in obj.findall('c:mesh/c:vertices/c:vertex',NS)]
        fs=[[int(f.attrib[k]) for k in ('v1','v2','v3')] for f in obj.findall('c:mesh/c:triangles/c:triangle',NS)]
        refs[obj.attrib['name']]=m.trimesh.Trimesh(vertices=vs,faces=fs,process=False)
parts=[dict(r,volume_mm3=r['source_volume_mm3'],bounds_mm=r['assembly_bounds_mm'],offset_x_mm=r['native_offset_x_mm'],printed=True) for r in src['printed_parts']]
parts += [dict(r,printed=False) for r in src['reference_parts']]
rows=[]
for part in parts:
    name=part['name'];txt=(check/(name+'-mass.mpr')).read_text()
    v=float(re.search(r'Volume:\s+([\d.E+\-]+)',txt).group(1))
    xyz=[(float(a),float(b)) for a,b in re.findall(r'[XYZ]:\s+([\d.E+\-]+)\s+--\s+([\d.E+\-]+)',txt)[:3]]
    bounds=m.np.array([[a for a,b in xyz],[b for a,b in xyz]])
    expected=m.np.array(part['bounds_mm']);expected[:,0]+=part['offset_x_mm']
    delta=abs(v-part['volume_mm3']);db=float(abs(bounds-expected).max())
    assert delta<.1 and db<.0001,(name,delta,db)
    if part['printed']:
        disk=m.trimesh.load(OUT/'stl'/(name+'.stl'),force='mesh');disk.apply_transform(part['print_to_assembly'])
    else:disk=refs[name].copy()
    disk.apply_translation([part['offset_x_mm'],0,0])
    raw=m.trimesh.load(check/(name+'.stl'),force='mesh')
    relocation=m.np.where(bounds[0]<0,1e-6-bounds[0],0.);raw.apply_translation(-relocation)
    assert abs(raw.bounds-bounds).max()<.0001
    assert raw.is_watertight and raw.is_winding_consistent and raw.volume>0,name
    extra=volume(m.dif(raw,disk));missing=volume(m.dif(disk,raw))
    assert math.isfinite(extra+missing) and max(extra,missing)<.1,(name,extra,missing)
    rows.append({'name':name,'printed':part['printed'],'volume_delta_mm3':delta,'bounds_delta_mm':db,
                 'extra_boundary_mm3':extra,'missing_boundary_mm3':missing,'raw_export_closed':True,
                 'stl_positive_octant_relocation_mm':relocation.tolist()})
report={'passed':True,'kernel_valid_solids':46,'printable_solids':34,'nonprinted_reference_solids':12,'audit_errors':0,
        'parts':rows,'drawing_sha256':hashlib.sha256((native/'PitchComm-v8-battery-access-fit.dwg').read_bytes()).hexdigest(),
        'scope':'References are cell, soft film, adhesive and assumed connector; no actual fit or material strength measurement.'}
(check/'evidence.json').write_text(json.dumps(report,indent=2))
print('PASS:46reopened ShapeManager solids;34printed+12reference;all boundaries match;AUDIT0.')
