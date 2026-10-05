"""Check local closed USB wall stock and catcher well-web witnesses."""
from probe_internal_assembly import ROOT,cad as m,board_parts,volume
import copy,json,math
OUT=ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1'
report=json.loads((OUT/'evidence.json').read_text())
env={};exec((OUT.parent/'mfd-source/builder-prefix.py').read_text(),env)
p=json.loads((OUT.parent/'mfd-source/source/profiles.json').read_text());rows={}
for style in ('receiver','wrist','keypad'):
    q=copy.deepcopy(p);q[style]=report['styles'][style]['case_profile'];C=env['m'].Case(q,style)
    def part(name):
        item=next(r for r in report['parts'] if r['name']==style+'_'+name)
        mesh=m.trimesh.load(OUT/'stl'/(item['name']+'.stl'),force='mesh');mesh.apply_transform(item['print_to_assembly']);return mesh
    body=part('body');lid=part('lid');usb=board_parts(C)['usb'];center=usb.bounds.mean(axis=0);face=C.p['charge']['face']
    if face=='y_max':
        skin=C.l-usb.bounds[1][1]-.15;witness=m.box(2.,.6,2.,(center[0]-1,C.l-1.55,center[2]-1))
    elif face=='x_max':
        skin=C.w-usb.bounds[1][0]-.15;witness=m.box(.6,2.,2.,(C.w-1.55,center[1]-1,center[2]-1))
    elif face=='x_min':
        skin=usb.bounds[0][0]-.15;witness=m.box(.6,2.,2.,(.95,center[1]-1,center[2]-1))
    else:raise ValueError(face)
    # The USB shell crosses the body/lid seam; stock belongs to both parts.
    missing=volume(m.dif(witness,m.uni(body,lid)));assert missing<.001,(style,skin,missing)
    roof=C.lid_top()-usb.bounds[1][2]-.15
    assert skin>=1.55 and roof>=.6,(style,skin,roof)
    row={'USB_flat_face_skin_after_clearance_mm':float(skin),'USB_top_skin_after_clearance_mm':float(roof),
         'inboard_0_6mm_assembled_wall_witness_missing_mm3':missing,
         'witness_location':'0.95 to 1.55mm inside the exterior datum, avoiding the existing 0.9mm lid bevel'}
    if style=='keypad':
        web=[]
        for a,b in zip(C.buttons(),C.buttons()[1:]):
            cx,ya=C.button_center(a);_,yb=C.button_center(b);gap=yb-ya-C.well_params()['diameter']
            witness=m.box(.3,gap-.2,.4,(cx-.15,ya+C.well_params()['diameter']/2+.1,C.lid_top()-.6))
            absent=volume(m.dif(witness,lid));assert absent<.001
            web.append({'minimum_nominal_web_mm':gap,'central_stock_witness_missing_mm3':absent})
        row['well_webs']=web
    rows[style]=row
path=OUT/'wall-stock-evidence.json';assert not path.exists();path.write_text(json.dumps({'passed':True,'styles':rows,'scope':'Local nominal stock, not measured printed strength.'},indent=2))
print(json.dumps(rows,indent=2))
