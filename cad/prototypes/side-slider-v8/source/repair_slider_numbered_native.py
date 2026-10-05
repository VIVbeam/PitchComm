"""Repair four native numeral pockets; preserve all original candidate evidence."""
from probe_internal_assembly import ROOT,volume
import autocad_csg,json,hashlib
STAGE=ROOT/'.tools/cad-runs/side-slider-v7'
OUT=STAGE/'complete-controls-v1/native/numbered-repair';assert not OUT.exists();OUT.mkdir()
DATA=OUT/'data';DATA.mkdir();CHECK=OUT/'reopen';CHECK.mkdir()
env={};exec((STAGE/'mfd-source/builder-prefix.py').read_text(),env)
m=env['m'];p=json.loads((STAGE/'mfd-source/source/profiles.json').read_text());C=m.Case(p,'keypad')
source=json.loads((STAGE/'complete-controls-v1/evidence.json').read_text())
autocad_csg.install(m);seq=[0]
script=['(setvar "FILEDIA" 0)','(setvar "CMDECHO" 0)','(setvar "OSMODE" 0)','(setvar "INSUNITS" 4)',
        '(setvar "FACETRES" 10)','(setvar "DELOBJ" 1)','(setvar "LUPREC" 8)']
rows=[]
for b in C.buttons():
    name='keypad_plunger_'+b['id']+'_head';item=next(r for r in source['parts'] if r['name']==name)
    local,head=m.build_plunger_parts_local(C,b);raw=m.xform(head,C.frame(*C.button_center(b)))
    path=STAGE/'complete-controls-v1/stl'/(name+'.stl');disk=m.trimesh.load(path,force='mesh');disk.apply_transform(item['print_to_assembly'])
    assert max(volume(m.dif(raw,disk)),volume(m.dif(disk,raw)))<.1
    assert abs(volume(raw)-item['source_volume_mm3'])<.1
    T=m.np.eye(4);T[0,3]=item['native_offset_x_mm']
    layer='PART_'+name
    script += [f'(setq pc-old (ssget "_X" (list (cons 8 "{layer}"))))','(command "_.ERASE" pc-old "")',
               f'(command "_.-LAYER" "_Make" "{layer}" "")']
    var=autocad_csg.emit(m,{'kind':'transform','matrix':T.tolist(),'child':raw.metadata['acad_csg']},script,DATA,seq)
    rows.append({'name':name,'corrected_volume_mm3':volume(raw),'canonical_stl_sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
script += ['(command "_.AUDIT" "_Yes")',f'(if (/= (sslength (ssget "_X" (list (cons 0 "3DSOLID")))) {len(source["parts"])}) (quit))']
for part in source['parts']:
    name=part['name'];layer='PART_'+name
    script += [f'(setq pc-set (ssget "_X" (list (cons 8 "{layer}") (cons 0 "3DSOLID"))))',
       '(if (/= (sslength pc-set) 1) (quit))','(setq pc-s (ssname pc-set 0))',
       f'(princ "\\nKERNEL_CHECK_{name}\\n")','(command "_.SOLIDEDIT" "_Body" "_Check" pc-s "" "_eXit")',
       f'(command "_.MASSPROP" pc-s "" "_Yes" "{(CHECK/(name+"-mass")).as_posix()}")',
       f'(command "_.STLOUT" pc-s "" "_No" "{(CHECK/(name+".stl")).as_posix()}")']
draw=OUT/'PitchComm-slider-v7-complete.dwg'
script += [f'(command "_.SAVEAS" "_2018" "{draw.as_posix()}")','_.QUIT','_Yes','']
(OUT/'repair.scr').write_text('\n'.join(script),encoding='ascii')
(OUT/'repair-manifest.json').write_text(json.dumps({'changed_native_parts':rows,'canonical_print_geometry_unchanged':True},indent=2))
print('Prepared four-pocket native repair and full 34-part validation.')
