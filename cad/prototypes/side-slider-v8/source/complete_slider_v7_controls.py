"""Complete the v6 case/controls set, audit motion, and prepare a native assembly."""
from probe_internal_assembly import ROOT,board_parts,oled,volume,sweep
import copy,json,math,hashlib
import autocad_csg
from PIL import Image,ImageDraw,ImageFont
STAGE=ROOT/'.tools/cad-runs/side-slider-v7'
OUT=STAGE/'complete-controls-v1';assert not OUT.exists();OUT.mkdir()
for n in ('stl','native','plates','assemblies'):(OUT/n).mkdir()
DATA=OUT/'native/data';DATA.mkdir()
env={};exec((STAGE/'mfd-source/builder-prefix.py').read_text(),env)
m=env['m'];p=json.loads((STAGE/'mfd-source/source/profiles.json').read_text())
defs=(STAGE/'study_side_slider_v7.py').read_text();defs=defs[defs.index('def contact('):defs.index('evidence={')]
state={'cad':m,'p':p,'copy':copy,'math':math,'volume':volume,'LIMIT':.001,
       'shift':lambda mesh,d:m.xform(mesh,m.trimesh.transformations.translation_matrix(d))}
exec(compile(defs,'frozen-slider','exec'),state)
autocad_csg.install(m)
report={'released':False,'hardware_measured':False,'styles':{},'parts':[],'failures':[]}
script=['(setvar "FILEDIA" 0)','(setvar "CMDECHO" 0)','(setvar "OSMODE" 0)','(setvar "INSUNITS" 4)',
        '(setvar "FACETRES" 10)','(setvar "DELOBJ" 1)','(setvar "LUPREC" 8)',
        '(command "_.ERASE" "_ALL" "")']
seq=[0];scenes=[]
def trans(d):
    T=m.np.eye(4);T[:3,3]=d;return T
def rot(deg,axis):return m.trimesh.transformations.rotation_matrix(math.radians(deg),axis)
I=m.np.eye(4)
def plain_transform(mesh,T):
    out=mesh.copy();out.apply_transform(T);return out
for idx,style in enumerate(('receiver','wrist','keypad')):
    q=copy.deepcopy(p)
    if style=='wrist':
        c=next(c for c in q[style]['components'] if c['name']==q[style]['cell'])
        c['y']+=6.5;q[style]['deck']['y1']=c['y']+c['length']+.5
    C=m.Case(q,style);parts=state['build'](C)
    items=[];case_report={'component_contacts':{},'control_motion':{},'support_witnesses':{},'part_names':[]}
    def add(suffix,asm,color,orientation=I):
        stem=style+'_'+suffix;turned=m.xform(asm,orientation)
        T=trans(-turned.bounds[0])@orientation;print_mesh=m.prepare_export(m.xform(asm,T))
        path=OUT/'stl'/(stem+'.stl');print_mesh.export(path)
        disk=m.trimesh.load(path,force='mesh');disk_asm=plain_transform(disk,m.np.linalg.inv(T))
        assert disk.is_watertight and disk.is_winding_consistent and disk.volume>0 and len(disk.split(only_watertight=False))==1,stem
        assert abs(disk.bounds[0]).max()<.0001,stem
        extra=volume(m.dif(disk_asm,asm));missing=volume(m.dif(asm,disk_asm));assert max(extra,missing)<.1,(stem,extra,missing)
        row={'name':stem,'style':style,'color':color,'source_volume_mm3':volume(asm),'assembly_bounds_mm':asm.bounds.tolist(),
             'print_to_assembly':m.np.linalg.inv(T).tolist(),'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
             'stl_extra_mm3':extra,'stl_missing_mm3':missing,'watertight':True,'single_shell':True}
        report['parts'].append(row);case_report['part_names'].append(stem)
        items.append((stem,disk,disk_asm,color))
        offset=trans([72*idx,0,0]);tree={'kind':'transform','matrix':offset.tolist(),'child':asm.metadata['acad_csg']}
        script.append(f'(command "_.-LAYER" "_Make" "PART_{stem}" "")')
        var=autocad_csg.emit(m,tree,script,DATA,seq)
        script.append(f'(setq pc-s {var})')
        script.append(f'(command "_.MASSPROP" pc-s "" "_Yes" "{(OUT/"native"/(stem+"-mass")).as_posix()}")')
        row['native_offset_x_mm']=72*idx
    for n in ('body','lid','deck','panel'):
        orientation=rot(180,[1,0,0]) if n=='lid' else I
        if n=='panel':orientation=rot(90,[0,1,0] if style=='wrist' else [1,0,0])
        add(n,parts[n],q['palette']['pink' if n=='lid' else 'white' if n=='panel' else 'cyan'],orientation)
    fixed={n:parts[n] for n in ('body','lid','deck')}
    electronics=board_parts(C)
    if C.p.get('oled'):electronics['oled']=oled(C)
    controls={};switches={}
    for b in C.buttons():
        cx,cy=C.button_center(b);F=C.frame(cx,cy);local,head=m.build_plunger_parts_local(C,b)
        suffix='plunger_'+b['id'];stem=m.xform(local,F);controls[suffix]=stem
        add(suffix,stem,q['palette']['white'],m.np.linalg.inv(F))
        if head is not None:
            asm=m.xform(head,F);controls[suffix+'_head']=asm
            add(suffix+'_head',asm,q['palette']['white'],rot(180,[1,0,0])@m.np.linalg.inv(F))
        if b.get('head')=='numbered':
            asm=m.xform(m.build_label_local(C,b),m.label_matrix(C,b));controls['label_'+b['id']]=asm
            add('label_'+b['id'],asm,q['palette']['cyan'],m.np.linalg.inv(m.label_matrix(C,b)))
        sc=C.switch_of(b);L=C.local_depth(cx,cy);bh=C.sw['body'][2];ah=C.sw['actuator'][1];fh=C.pl['flange_height']
        body=m.box(sc['width'],sc['length'],bh,(-sc['width']/2,-sc['length']/2,-L-fh-ah-bh))
        act=m.box(C.sw['actuator'][0],C.sw['actuator'][0],ah,(-C.sw['actuator'][0]/2,-C.sw['actuator'][0]/2,-L-fh-ah))
        switches[b['id']]=m.xform(m.uni(body,act),F)
        moving=m.xform(m.build_plunger_local(C,b),F)
        delta=(F[:3,:3]@m.np.array([0,0,-(C.sw['nominal_travel']+C.pl['travel_clearance'])])).tolist()
        sweep_mesh=sweep(moving,delta)
        obstacles={**fixed,**electronics,**{n:v for n,v in controls.items() if not n.startswith(suffix) and n!='label_'+b['id']}}
        case_report['control_motion'][b['id']]=state['hits'](sweep_mesh,obstacles)
        # An exact central support witness immediately below the switch body.
        base=C.hb-(bh+ah+fh)
        witness=m.box(3.,3.,.2,(cx-1.5,cy-1.5,base-.2))
        case_report['support_witnesses'][b['id']]={'expected_mm3':volume(witness),'missing_mm3':volume(m.dif(witness,parts['body']))}
    if C.p.get('sidebar'):
        sb=C.p['sidebar'];F=m.side_plunger_matrix(C);local,head=m.build_side_plunger_parts_local(C)
        asm=m.xform(local,F);controls['back_stem']=asm;add('plunger_back',asm,q['palette']['pink'],rot(90,[1,0,0])@m.np.linalg.inv(F))
        if head is not None:
            asm=m.xform(head,F);controls['back_head']=asm;add('plunger_back_head',asm,q['palette']['pink'],rot(-90,[1,0,0])@m.np.linalg.inv(F))
        sw=C.comp(sb['switch']);switches['back']=m.box(sw['width'],sw['length'],6.,(sw['x'],sw['y'],sb['z']-3))
        moving=m.xform(m.build_side_plunger_local(C),F)
        delta=[-(C.sw['nominal_travel']+C.pl['travel_clearance']),0,0] if sb['face']=='x_max' else [0,0,0]
        case_report['control_motion']['back']=state['hits'](sweep(moving,delta),{**fixed,**electronics})
    if C.p.get('bezel'):
        F=m.bezel_matrix(C);asm=m.xform(m.build_bezel_local(C),F)
        add('display_bezel',asm,q['palette']['pink'],m.np.linalg.inv(F))
    for mount in C.mounts():add(mount['name']+'_carrier',m.build_carrier(C,mount),q['palette']['cyan'],rot(180,[0,1,0]))
    for n,component in {**electronics,**switches}.items():
        obstacles=fixed if n in electronics else {**fixed,**electronics}
        case_report['component_contacts'][n]=state['hits'](component,obstacles)
    for kind,groups in (('component',case_report['component_contacts']),('motion',case_report['control_motion'])):
        for name,hits in groups.items():
            for part,v in hits.items():
                if v>.001:report['failures'].append(f'{style} {kind} {name}/{part}: {v:.8f}mm3')
    for name,witness in case_report['support_witnesses'].items():
        if witness['missing_mm3']>.001:report['failures'].append(f'{style} unsupported switch {name}: {witness}')
    # Separate on-bed print plates, with a 4mm bounding-box gap.
    arranged=[];px=py=4.;row_h=0.
    for stem,disk,asm,col in items:
        w,l,h=disk.extents
        if px+w>196:px=4.;py+=row_h+4.;row_h=0.
        assert py+l<196
        placed=disk.copy();placed.apply_translation([px,py,0]);arranged.append((stem,placed,col));px+=w+4.;row_h=max(row_h,l)
    m.write_3mf(OUT/'plates'/f'{style}_print_plate.3mf',arranged)
    m.write_3mf(OUT/'assemblies'/f'{style}_complete_assembly.3mf',[(stem,asm,col) for stem,disk,asm,col in items])
    case_report['case_profile']=q[style];report['styles'][style]=case_report
    R=rot(-90,[0,0,1]) if style=='keypad' else rot(180,[0,0,1]);R[:2,3]=[0,C.w] if style=='keypad' else [C.w,C.l]
    scenes.append([(plain_transform(asm,R),m.hex_rgb(col)) for stem,disk,asm,col in items])
    print(style,len(items),'parts; failures so far',len(report['failures']),flush=True)
report['passed']=not report['failures']
(OUT/'evidence.json').write_text(json.dumps(report,indent=2))
assert report['passed'],report['failures']
draw_path=OUT/'native/PitchComm-slider-v6-complete.dwg'
script+=['(command "_.AUDIT" "_Yes")','(command "_.ZOOM" "_Extents")',f'(command "_.SAVEAS" "_2018" "{draw_path.as_posix()}")','_.QUIT','_Yes','']
(OUT/'native/build.scr').write_text('\n'.join(script),encoding='ascii')
img=Image.new('RGB',(1500,480),'#f7f8fa');draw=ImageDraw.Draw(img);font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',22)
for i,items in enumerate(scenes):
    img.paste(m.render_mesh_array(items,495,390,ss=2),(500*i,50));draw.text((500*i+16,12),('Pitcher','Watch','Catcher — landscape')[i],font=font,fill='#202a34')
img.save(OUT/'complete-controls-preview.png')
print('PASS: complete control support/motion checks; prepared native build and print plates.',flush=True)
