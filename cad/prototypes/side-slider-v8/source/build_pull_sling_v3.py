"""Case-anchored soft pull sling, modeled deployment and matching fit artifacts."""
from probe_internal_assembly import ROOT,volume,board_parts,oled,sweep
import copy,json,math,hashlib,shutil,zipfile,xml.etree.ElementTree as ET
import autocad_csg
from PIL import Image,ImageDraw,ImageFont
BASE=ROOT/'.tools/cad-runs/side-slider-v7';SRC=BASE/'complete-controls-v1'
OUT=ROOT/'.tools/cad-runs/pull-sling-v3';assert not OUT.exists();OUT.mkdir()
for n in ('stl','plates','assemblies'):shutil.copytree(SRC/n,OUT/n)
for n in ('references','native'):(OUT/n).mkdir()
DATA=OUT/'native/data';DATA.mkdir()
env={};exec((BASE/'mfd-source/builder-prefix.py').read_text(),env)
m=env['m'];p=json.loads((BASE/'mfd-source/source/profiles.json').read_text())
defs=(BASE/'study_side_slider_v7.py').read_text();defs=defs[defs.index('def contact('):defs.index('evidence={')]
state={'cad':m,'p':p,'copy':copy,'math':math,'volume':volume,'LIMIT':.001,
       'shift':lambda mesh,d:m.xform(mesh,m.trimesh.transformations.translation_matrix(d))}
exec(compile(defs,'frozen-slider','exec'),state)
autocad_csg.install(m)
manifest=copy.deepcopy(json.loads((SRC/'evidence.json').read_text()))
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
report={'released':False,'hardware_measured':False,'film_width_mm':6.,'film_thickness_mm':.1,
        'adhesive_stack_mm':.1,'printed_parts':manifest['parts'],'reference_parts':[], 'styles':{},
        'scope':'Rectilinear U-sling clearance and constant-length deployment. Film bending, adhesion strength, grasp force, actual housing/wires, pouch shape and manual fit are unmeasured.'}
script=['(setvar "FILEDIA" 0)','(setvar "CMDECHO" 0)','(setvar "OSMODE" 0)','(setvar "INSUNITS" 4)',
        '(setvar "FACETRES" 10)','(setvar "DELOBJ" 1)','(setvar "LUPREC" 8)'];seq=[0];scenes=[]
def transform(mesh,T):
    out=mesh.copy();out.apply_transform(T);return out
def translation(d):
    T=m.np.eye(4);T[:3,3]=d;return T
def native(name,mesh,idx,replace=False):
    layer=('PART_' if replace else 'REF_')+name
    if replace:script.extend([f'(setq pc-old (ssget "_X" (list (cons 8 "{layer}"))))','(command "_.ERASE" pc-old "")'])
    script.append(f'(command "_.-LAYER" "_Make" "{layer}" "")')
    T=translation([72*idx,0,0]);autocad_csg.emit(m,{'kind':'transform','matrix':T.tolist(),'child':mesh.metadata['acad_csg']},script,DATA,seq)
    return {'name':name,'layer':layer,'volume_mm3':volume(mesh),'bounds_mm':mesh.bounds.tolist(),'offset_x_mm':72*idx}
for idx,style in enumerate(('receiver','wrist','keypad')):
    q=copy.deepcopy(p);q[style]=manifest['styles'][style]['case_profile'];C=m.Case(q,style);parts=state['build'](C)
    x0,y0,x1,y1=C.cell_rect();cell=m.box(x1-x0,y1-y0,C.cell_h(),(x0,y0,C.cell_z()))
    T=parts['transform'];inv=m.np.linalg.inv(T);local_cell=m.xform(cell,T);lo,hi=local_cell.bounds
    center=(lo[0]+hi[0])/2;a,b=lo[1],hi[1];bottom,top=lo[2],hi[2]
    length=C.w if style=='wrist' else C.l;back=length+(2.35 if style=='receiver' else .7);end=back-.4
    anchor_len=3. if style=='wrist' else 8.
    anchor_end=length+.7 if style=='wrist' else b-.2
    anchor_start=anchor_end-anchor_len
    if style=='wrist':
        # Floor land extends under the existing side-guide projection; no
        # outside size growth or extra printed piece. Its top stays at1.4mm.
        pad=m.xform(m.rbox(6.5,3.5,1.4,.25,.1,(center-3.25,anchor_start-.25,0)),inv)
        old=parts['body'];parts['body']=m.uni(old,pad)
        # The old exit corridor starts at1.45mm. Flatten only the anchor
        # footprint to1.4mm so the0.1mm adhesive does not overlap its lip.
        anchor_clearance=m.xform(m.box(6.1,anchor_len+.1,.15,(center-3.05,anchor_start-.05,bottom-.2)),inv)
        parts['body']=m.dif(parts['body'],anchor_clearance)
        growth=volume(parts['body'])-volume(old)
        assert 0<growth<40 and abs(parts['body'].bounds-old.bounds).max()<.0001
        item=next(r for r in report['printed_parts'] if r['name']=='wrist_body')
        bed=m.prepare_export(m.xform(parts['body'],m.np.linalg.inv(m.np.array(item['print_to_assembly']))))
        bed.export(OUT/'stl/wrist_body.stl')
        disk=m.trimesh.load(OUT/'stl/wrist_body.stl',force='mesh')
        assert disk.is_watertight and disk.is_winding_consistent and len(disk.split(only_watertight=False))==1
        restored=transform(disk,item['print_to_assembly'])
        assert max(volume(m.dif(restored,parts['body'])),volume(m.dif(parts['body'],restored)))<.1
        item.update(source_volume_mm3=volume(parts['body']),assembly_bounds_mm=parts['body'].bounds.tolist(),source_sha256=hashlib.sha256((OUT/'stl/wrist_body.stl').read_bytes()).hexdigest())
        report['changed_printed_part']=native('wrist_body',parts['body'],idx,True)
        report['watch_added_material_mm3']=growth
    def sling(delta=0):
        start=a+delta;free=end+2*delta
        lower=m.box(6,anchor_end-start+.1,.1,(center-3,start-.1,bottom-.1))
        upper=m.box(6,free-start+.1,.1,(center-3,start-.1,top))
        cap=m.box(6,.1,top-bottom+.2,(center-3,start-.1,bottom-.1))
        return m.xform(m.uni(lower,upper,cap),inv)
    film=sling();anchor=m.xform(m.box(6,anchor_len,.1,(center-3,anchor_start,bottom-.2)),inv)
    if style=='wrist':connector=m.box(5.4,8.4,4.4,(x1+.35,y0+.3,C.cell_z()-.05))
    else:connector=m.box(8.4,5.4,4.4,((x0+x1)/2-4.2,y1+.3,C.cell_z()-.15))
    opening_outer=length+(3.5 if style!='receiver' else 5.15)
    handoff=opening_outer+6-b
    assert a+handoff<anchor_start-.25,(style,a+handoff,anchor_start)
    d=[handoff,0,0] if style=='wrist' else [0,handoff,0]
    # Exact union of all U-sling positions: lower shrinks, cap translates,
    # upper grows at two times the cell displacement. No sampled-only claim.
    lower=m.box(6,anchor_end-a+.1,.1,(center-3,a-.1,bottom-.1))
    upper=m.box(6,end+2*handoff-a+.1,.1,(center-3,a-.1,top))
    cap_sweep=m.box(6,handoff+.1,top-bottom+.2,(center-3,a-.1,bottom-.1))
    continuous=m.xform(m.uni(lower,upper,cap_sweep),inv)
    current={}
    for item in report['printed_parts']:
        if item['style']==style:
            mesh=m.trimesh.load(OUT/'stl'/(item['name']+'.stl'),force='mesh');current[item['name']]=transform(mesh,item['print_to_assembly'])
    fixed={name:mesh for name,mesh in current.items() if name!=style+'_panel'}
    fixed['open_panel']=state['shift'](parts['panel'],[0,0,parts['travel']]);fixed.update(board_parts(C))
    if C.p.get('oled'):fixed['oled']=oled(C)
    for i,(sx,sy) in enumerate(C.p['fasteners']):fixed['screw_'+str(i)]=m.cyl_at(2.5,1.,C.hb-.1,sx,sy)
    fixed['parked_connector']=connector
    hits=state['hits'](continuous,fixed);assert all(v<.001 for v in hits.values()),(style,hits)
    release=state['contact'](sweep(parts['released_panel'],[0,0,parts['travel']]),film)
    assert release<.001 and state['contact'](parts['panel'],film)<.001
    # Adhesive is above the floor; a separate solid below it proves its land.
    land=m.xform(m.box(6,anchor_len,.1,(center-3,anchor_start,bottom-.3)),inv)
    missing=volume(m.dif(land,parts['body']));assert missing<.001,(style,missing)
    samples=[]
    for n in range(13):
        delta=handoff*n/12;S=sling(delta);pack=state['shift'](cell,[delta,0,0] if style=='wrist' else [0,delta,0])
        hit=state['contact'](S,pack);dv=abs(volume(S)-volume(film));assert hit<.001 and dv<.01
        samples.append({'delta_mm':delta,'sling_cell_penetration_mm3':hit,'film_volume_delta_mm3':dv})
    # Controls prove that the test detects cap/pouch and connector/film hits.
    intrusion=m.xform(m.box(6,.1,top-bottom,(center-3,a-.05,bottom)),inv)
    cap_control=state['contact'](intrusion,cell);assert cap_control>1.
    old_connector_control=None
    if style!='wrist':
        old_connector_control=state['contact'](state['shift'](connector,[0,0,.1]),film);assert old_connector_control>.01
    # Disconnect the housing before pulling the cell. Independent housing exit
    # is checked against the stationary sling and all fitted components.
    exits=sweep(connector,[length+10,0,0] if style=='wrist' else [0,length+10,0])
    obstacles={k:v for k,v in fixed.items() if k!='parked_connector'};obstacles.update(film=film,cell=cell,anchor=anchor)
    exit_hits=state['hits'](exits,obstacles);assert all(v<.001 for v in exit_hits.values()),(style,exit_hits)
    row={'handoff_cell_displacement_mm':handoff,'pack_protrusion_beyond_outer_guides_mm':6.,
        'free_tip_travel_mm':2*handoff,'continuous_sling_contacts_mm3':hits,'connector_exit_contacts_mm3':exit_hits,
        'release_sling_contact_mm3':release,'anchor_land_missing_mm3':missing,'anchor_area_mm2':6*anchor_len,
        'connector_bounds_mm':connector.bounds.tolist(),'normalized_anchor':[center-3,anchor_start,bottom-.2,6,anchor_len,.1],
        'film_rectilinear_length_budget_mm':anchor_end-a+end-a+top-bottom+.2,
        'samples':samples,'negative_controls':{'cap_pouch_penetration_mm3':cap_control,'raised_connector_film_penetration_mm3':old_connector_control}}
    report['styles'][style]=row
    refs=[]
    for name,mesh,color in (('cell',cell,'#6A7179'),('pull_sling',film,'#F29329'),('anchor',anchor,'#EFC438'),('connector_assumed',connector,'#A64655')):
        stem=style+'_'+name;canonical=m.prepare_export(mesh);assert canonical.is_watertight and canonical.is_winding_consistent and canonical.volume>0
        ref=native(stem,mesh,idx);ref['color']=color;report['reference_parts'].append(ref);refs.append((stem,canonical,color))
    group=[(name,mesh,next(r['color'] for r in report['printed_parts'] if r['name']==name)) for name,mesh in current.items()]
    m.write_3mf(OUT/'references'/f'{style}_battery_access.3mf',group+refs)
    if style=='wrist':
        m.write_3mf(OUT/'assemblies/wrist_complete_assembly.3mf',group)
        with zipfile.ZipFile(SRC/'plates/wrist_print_plate.3mf') as z:root=ET.fromstring(z.read('3D/3dmodel.model'))
        objs=[]
        for obj in root.findall('c:resources/c:object',NS):
            if obj.attrib['name']=='assembly':continue
            name=obj.attrib['name'];vs=[[float(v.attrib[k]) for k in ('x','y','z')] for v in obj.findall('c:mesh/c:vertices/c:vertex',NS)]
            fs=[[int(t.attrib[k]) for k in ('v1','v2','v3')] for t in obj.findall('c:mesh/c:triangles/c:triangle',NS)]
            mesh=m.trimesh.Trimesh(vertices=vs,faces=fs,process=False)
            if name=='wrist_body':
                new=m.trimesh.load(OUT/'stl/wrist_body.stl',force='mesh');new.apply_translation(mesh.bounds[0]-new.bounds[0]);mesh=new
            objs.append((name,mesh,next(r['color'] for r in report['printed_parts'] if r['name']==name)))
        m.write_3mf(OUT/'plates/wrist_print_plate.3mf',objs)
    R=m.trimesh.transformations.rotation_matrix(math.pi,[0,0,1]);R[:2,3]=[C.w,C.l]
    for label,delta in (('Ready to pull',0),('Cell at handoff',handoff)):
        # A cutaway of the case floor and open panel; the lid/deck are omitted
        # for visibility, while collision checks above retain them.
        base=m.dif(parts['body'],m.box(200,200,50,(-50,-50,6.3)))
        objects=[(base,m.hex_rgb(q['palette']['cyan'])),(fixed['open_panel'],(.94,.94,.96)),
                 (state['shift'](cell,[delta,0,0] if style=='wrist' else [0,delta,0]),(.42,.45,.49)),
                 (sling(delta),(1.,.55,.13)),(anchor,(.94,.78,.2)),(connector,(.65,.28,.34))]
        scenes.append((style,label,[(transform(mesh,R),col) for mesh,col in objects]))
    print(style,'PASS: continuous deployment, housing exit, anchor land; handoff',round(handoff,3),flush=True)
report['passed']=True
(OUT/'evidence.json').write_text(json.dumps(report,indent=2))
script += ['(command "_.AUDIT" "_Yes")',f'(if (/= (sslength (ssget "_X" (list (cons 0 "3DSOLID")))) 46) (quit))',
           '(command "_.ZOOM" "_Extents")',f'(command "_.SAVEAS" "_2018" "{(OUT/"native/PitchComm-v8-battery-access-fit.dwg").as_posix()}")','_.QUIT','_Yes','']
(OUT/'native/build.scr').write_text('\n'.join(script),encoding='ascii')
img=Image.new('RGB',(1530,920),'#f7f8fa');draw=ImageDraw.Draw(img);font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',22)
for i,(style,label,items) in enumerate(scenes):
    tile=m.render_mesh_array(items,500,380,ss=2,pad=.83);x=i//2*510;y=i%2*450;img.paste(tile,(x,y+48))
    draw.text((x+16,y+10),{'receiver':'Pitcher','wrist':'Watch','keypad':'Catcher'}[style]+' — '+label,font=font,fill='#202a34')
draw.text((16,894),'Orange: soft pull sling • yellow: case-floor anchor • red: assumed connector • cutaway, not print parts',font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16),fill='#485764')
img.save(OUT/'pull-sling-cutaway.png')
print('Staged complete matching prints and 12 nonprinted native references:',OUT,flush=True)
