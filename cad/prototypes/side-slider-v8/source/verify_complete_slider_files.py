"""Readback verification of every serialized part, assembly and print plate."""
from probe_internal_assembly import ROOT,cad as m,volume
import json,hashlib,zipfile,xml.etree.ElementTree as ET,math
OUT=ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1'
src=json.loads((OUT/'evidence.json').read_text());assert src['passed']
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
rows=[];contacts={};canonical={}
for item in src['parts']:
    path=OUT/'stl'/(item['name']+'.stl');assert hashlib.sha256(path.read_bytes()).hexdigest()==item['source_sha256']
    mesh=m.trimesh.load(path,force='mesh');canonical[item['name']]=mesh
def moved(mesh,T):
    out=mesh.copy();out.apply_transform(T);return out
for style in ('receiver','wrist','keypad'):
    names={r['name'] for r in src['parts'] if r['style']==style}
    group=[]
    for category,filename in (('assemblies',style+'_complete_assembly.3mf'),('plates',style+'_print_plate.3mf')):
        with zipfile.ZipFile(OUT/category/filename) as z:
            assert z.testzip() is None;root=ET.fromstring(z.read('3D/3dmodel.model'))
        assert root.attrib['unit']=='millimeter'
        objects={o.attrib['name']:o for o in root.findall('c:resources/c:object',NS)}
        assert set(objects)==names|{'assembly'}
        ids={objects[n].attrib['id'] for n in names}
        assert ids=={o.attrib['objectid'] for o in objects['assembly'].findall('c:components/c:component',NS)}
        for name in names:
            obj=objects[name];vs=[[float(v.attrib[k]) for k in ('x','y','z')] for v in obj.findall('c:mesh/c:vertices/c:vertex',NS)]
            fs=[[int(f.attrib[k]) for k in ('v1','v2','v3')] for f in obj.findall('c:mesh/c:triangles/c:triangle',NS)]
            mesh=m.trimesh.Trimesh(vertices=vs,faces=fs,process=False)
            assert mesh.is_watertight and mesh.is_winding_consistent and mesh.volume>0 and len(mesh.split(only_watertight=False))==1,name
            item=next(r for r in src['parts'] if r['name']==name)
            expected=moved(canonical[name],item['print_to_assembly']) if category=='assemblies' else canonical[name]
            if category=='plates':
                assert mesh.bounds[0][2]>=-.0001 and abs(mesh.bounds[0][2])<.0001
                assert mesh.bounds[0][:2].min()>=0 and mesh.bounds[1][:2].max()<=200
                expected=expected.copy();expected.apply_translation(mesh.bounds[0]-expected.bounds[0])
            extra=volume(m.dif(mesh,expected));missing=volume(m.dif(expected,mesh))
            assert math.isfinite(extra+missing) and max(extra,missing)<.1,(filename,name,extra,missing)
            assert abs(mesh.bounds-expected.bounds).max()<.0001
            rows.append({'file':filename,'name':name,'extra_mm3':extra,'missing_mm3':missing})
            if category=='assemblies':group.append((name,mesh))
    pair_hits={}
    for i,(a,A) in enumerate(group):
        for b,B in group[i+1:]:
            if m.np.any(m.np.minimum(A.bounds[1],B.bounds[1])-m.np.maximum(A.bounds[0],B.bounds[0])<=0):continue
            hit=volume(m.inter(A,B));assert math.isfinite(hit)
            if hit>.001:pair_hits[a+'/'+b]=hit
    contacts[style]=pair_hits
    print(style,'all objects/plates read back; part overlaps',pair_hits,flush=True)
result={'passed':not any(contacts.values()),'serialized_mesh_objects':len(rows),'stl_parts':len(canonical),'readbacks':rows,'assembled_pair_contacts_mm3':contacts}
(OUT/'serialized-evidence.json').write_text(json.dumps(result,indent=2))
assert result['passed'],contacts
# Prepare saved drawing reopen and per-part kernel / shape verification.
native=OUT/'native';reopen=native/'reopen';assert not reopen.exists();reopen.mkdir()
script=['(setvar "FILEDIA" 0)','(setvar "CMDECHO" 0)','(setvar "FACETRES" 10)','(setvar "LUPREC" 8)',
        '(command "_.AUDIT" "_Yes")',f'(if (/= (sslength (ssget "_X" (list (cons 0 "3DSOLID")))) {len(canonical)}) (quit))']
for row in src['parts']:
    name=row['name']
    script += [f'(setq pc-set (ssget "_X" (list (cons 8 "PART_{name}") (cons 0 "3DSOLID"))))',
        '(if (/= (sslength pc-set) 1) (quit))','(setq pc-s (ssname pc-set 0))',
        f'(princ "\\nKERNEL_CHECK_{name}\\n")','(command "_.SOLIDEDIT" "_Body" "_Check" pc-s "" "_eXit")',
        f'(command "_.MASSPROP" pc-s "" "_Yes" "{(reopen/(name+"-mass")).as_posix()}")',
        f'(command "_.STLOUT" pc-s "" "_No" "{(reopen/(name+".stl")).as_posix()}")']
script+=['_.QUIT','_Yes',''];(reopen/'validate.scr').write_text('\n'.join(script),encoding='ascii')
print('PASS: all 34 STLs and 68 3MF mesh objects; saved native validation prepared.',flush=True)
