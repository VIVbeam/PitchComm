"""Independent serialized geometry and saved-native validation preparation."""
from probe_internal_assembly import ROOT,cad as m,volume,sweep
import json,hashlib,zipfile,xml.etree.ElementTree as ET,math
OUT=ROOT/'.tools/cad-runs/pull-sling-v3'
BASE=ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1'
src=json.loads((OUT/'evidence.json').read_text());assert src['passed']
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
def moved(mesh,T):
    mesh=mesh.copy();mesh.apply_transform(T);return mesh
def read(path):
    with zipfile.ZipFile(path) as z:
        assert z.testzip() is None;root=ET.fromstring(z.read('3D/3dmodel.model'))
    assert root.attrib['unit']=='millimeter'
    objects={o.attrib['name']:o for o in root.findall('c:resources/c:object',NS)}
    names=set(objects)-{'assembly'}
    assert {objects[n].attrib['id'] for n in names}=={o.attrib['objectid'] for o in objects['assembly'].findall('c:components/c:component',NS)}
    result={}
    for name in names:
        obj=objects[name]
        vs=[[float(v.attrib[k]) for k in ('x','y','z')] for v in obj.findall('c:mesh/c:vertices/c:vertex',NS)]
        fs=[[int(f.attrib[k]) for k in ('v1','v2','v3')] for f in obj.findall('c:mesh/c:triangles/c:triangle',NS)]
        mesh=m.trimesh.Trimesh(vertices=vs,faces=fs,process=False)
        assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0 and len(mesh.split(only_watertight=False))==1,name
        result[name]=mesh
    return result
def match(A,B,label):
    extra=volume(m.dif(A,B));missing=volume(m.dif(B,A))
    assert math.isfinite(extra+missing) and max(extra,missing)<.1,(label,extra,missing)
    assert abs(A.bounds-B.bounds).max()<.0001,label
    return {'name':label,'extra_mm3':extra,'missing_mm3':missing}
def contacts(group):
    rows={};items=list(group.items())
    for i,(a,A) in enumerate(items):
        for b,B in items[i+1:]:
            if m.np.any(m.np.minimum(A.bounds[1],B.bounds[1])-m.np.maximum(A.bounds[0],B.bounds[0])<=0):continue
            hit=volume(m.inter(A,B));assert math.isfinite(hit)
            if hit>.001:rows[a+'/'+b]=hit
    assert not rows,rows
    return rows
canonical={};changed=[];rows=[];pairs={};refs={}
for item in src['printed_parts']:
    name=item['name'];path=OUT/'stl'/(name+'.stl')
    digest=hashlib.sha256(path.read_bytes()).hexdigest();assert digest==item['source_sha256']
    if digest!=hashlib.sha256((BASE/'stl'/path.name).read_bytes()).hexdigest():changed.append(name)
    mesh=m.trimesh.load(path,force='mesh');canonical[name]=mesh
    assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0 and len(mesh.split(only_watertight=False))==1
    assert abs(mesh.bounds[0][2])<.0001
assert changed==['wrist_body'],changed
for style in ('receiver','wrist','keypad'):
    parts={r['name']:r for r in src['printed_parts'] if r['style']==style}
    refmeta={r['name']:r for r in src['reference_parts'] if r['name'].startswith(style+'_')}
    for category,filename in (('assemblies',style+'_complete_assembly.3mf'),('plates',style+'_print_plate.3mf'),('references',style+'_battery_access.3mf')):
        group=read(OUT/category/filename)
        assert set(group)==set(parts)|(set(refmeta) if category=='references' else set())
        for name,mesh in group.items():
            if name in refmeta:
                item=refmeta[name]
                assert abs(mesh.volume-item['volume_mm3'])<.1 and abs(mesh.bounds-m.np.array(item['bounds_mm'])).max()<.0001
                refs[name]=mesh
                rows.append({'name':name,'file':filename,'volume_delta_mm3':abs(mesh.volume-item['volume_mm3'])})
                continue
            expected=moved(canonical[name],parts[name]['print_to_assembly']) if category!='plates' else canonical[name]
            if category=='plates':
                assert abs(mesh.bounds[0][2])<.0001 and mesh.bounds[0][:2].min()>=0 and mesh.bounds[1][:2].max()<=200
                expected=expected.copy();expected.apply_translation(mesh.bounds[0]-expected.bounds[0])
            row=match(mesh,expected,name);row['file']=filename;rows.append(row)
        pairs[filename]=contacts(group)
    print(style,'serialized assemblies, plates and reference parts PASS',flush=True)
# Changed watch floor land must clear both closed and continuously released panel.
body=moved(canonical['wrist_body'],next(r['print_to_assembly'] for r in src['printed_parts'] if r['name']=='wrist_body'))
env={};stage=BASE.parent;exec((stage/'mfd-source/builder-prefix.py').read_text(),env)
cm=env['m'];import copy
defs=(stage/'study_side_slider_v7.py').read_text();defs=defs[defs.index('def contact('):defs.index('evidence={')]
state={'cad':cm,'p':json.loads((stage/'mfd-source/source/profiles.json').read_text()),'copy':copy,'math':math,'volume':volume,'LIMIT':.001,
       'shift':lambda mesh,d:moved(mesh,m.trimesh.transformations.translation_matrix(d))}
exec(compile(defs,'frozen-slider','exec'),state)
q=copy.deepcopy(state['p']);q['wrist']=json.loads((BASE/'evidence.json').read_text())['styles']['wrist']['case_profile']
C=cm.Case(q,'wrist');case=state['build'](C)
motion=volume(m.inter(body,sweep(case['released_panel'],[0,0,case['travel']])))
assert motion<.001,motion
report={'passed':True,'stl_parts':len(canonical),'changed_stl_parts':changed,'unchanged_stl_parts':33,
        'serialized_mesh_objects':len(rows),'readbacks':rows,'pair_contacts_mm3':pairs,'watch_panel_sweep_contact_mm3':motion}
assert len(rows)==114
(OUT/'serialized-evidence.json').write_text(json.dumps(report,indent=2))
check=OUT/'native/reopen';assert not check.exists();check.mkdir()
script=['(setvar "FILEDIA" 0)','(setvar "CMDECHO" 0)','(setvar "FACETRES" 10)','(setvar "LUPREC" 8)',
        '(command "_.AUDIT" "_Yes")','(if (/= (sslength (ssget "_X" (list (cons 0 "3DSOLID")))) 46) (quit))']
items=[{'name':r['name'],'layer':'PART_'+r['name']} for r in src['printed_parts']]+src['reference_parts']
for r in items:
    name=r['name'];layer=r['layer']
    script += [f'(setq pc-set (ssget "_X" (list (cons 8 "{layer}") (cons 0 "3DSOLID"))))',
               '(if (/= (sslength pc-set) 1) (quit))','(setq pc-s (ssname pc-set 0))',
               f'(princ "\\nKERNEL_CHECK_{name}\\n")','(command "_.SOLIDEDIT" "_Body" "_Check" pc-s "" "_eXit")',
               f'(command "_.MASSPROP" pc-s "" "_Yes" "{(check/(name+"-mass")).as_posix()}")',
               f'(command "_.STLOUT" pc-s "" "_No" "{(check/(name+".stl")).as_posix()}")']
script+=['_.QUIT','_Yes',''];(check/'validate.scr').write_text('\n'.join(script),encoding='ascii')
print('PASS:34STLs,114serialized3MFobjects,33unchangedprints;46native checks prepared.')
