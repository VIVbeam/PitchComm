"""Private battery-side sliding-panel study; never writes released CAD assets."""
from probe_internal_assembly import ROOT,cad,p,board_parts,oled,shift,sweep,volume
import copy,hashlib,json,math,shutil
from pathlib import Path

OUT=ROOT/'.tools/cad-runs/side-slider-v7'
assert not OUT.exists(),'Use a fresh study directory; preserve previous evidence.'
OUT.mkdir(parents=True)
for name in ('generate_cases.py','profiles.json','study_side_slider_v7.py'):
    shutil.copyfile(ROOT/'.tools/cad-source'/name,OUT/name)
baseline={str(f.relative_to(ROOT)):hashlib.sha256(f.read_bytes()).hexdigest() for f in
          (ROOT/'.tools/cad-source/profiles.json',ROOT/'.tools/cad-source/generate_cases.py')}
# Preserve and load the compact landscape MFD candidate for the catcher.
MFD=OUT/'mfd-source';(MFD/'source').mkdir(parents=True)
source=ROOT/'.tools/cad-runs/v21-compact-rotated-mfd/source'
for name in ('profiles.json','generate_cases.py'):shutil.copyfile(source/name,MFD/'source'/name)
# Keep the horizontal four-key row inside the same shell, clear of headers.
profile_path=MFD/'source/profiles.json'
candidate=json.loads(profile_path.read_text())
for i,button in enumerate(candidate['keypad']['buttons']):
    yy=20.2+9.5*i;button['y']=yy
    next(c for c in candidate['keypad']['components'] if c['name']==button['switch'])['y']=yy
candidate['keypad']['plunger']['head_numbered']=[7.8,.85]
candidate['keypad']['well']['diameter']=8.6
candidate['revision']='side-slider-v7-compact-supported-controls-candidate'
candidate['keypad']['note']='Compact horizontal four-key row; 9.5mm pitch, 7.8mm heads, 0.9mm well webs. First key shifted off PCB/header reservation so its floor pedestal can be retained. Nominal geometry only.'
profile_path.write_text(json.dumps(candidate,indent=2))
prefix=(ROOT/'.tools/cad-source/build_rotated_mfd.py').read_text().split("stage=OUT/'prints'")[0]
prefix=prefix.replace("ROOT/'.tools/cad-runs/v21-compact-rotated-mfd'", "ROOT/'.tools/cad-runs/side-slider-v7/mfd-source'")
prefix=prefix.replace('sx-C.wall-5.', 'sx-C.wall-5.85').replace('pocket=m.box(6.,6.,6.', 'pocket=m.box(6.85,6.,6.')
prefix=prefix.replace('old_body(copy_case(C,False,False))','old_body(copy_case(C,False,True))')
(MFD/'builder-prefix.py').write_text(prefix,encoding='utf-8')
env={};exec(compile(prefix,str(MFD/'builder-prefix.py'),'exec'),env)
cad=env['m'];p=json.loads((MFD/'source/profiles.json').read_text())
LIMIT=.001

def contact(a,b):
    if not len(a.faces) or not len(b.faces):return 0.
    if cad.np.any(cad.np.minimum(a.bounds[1],b.bounds[1])-cad.np.maximum(a.bounds[0],b.bounds[0])<=0):return 0.
    v=volume(cad.inter(a,b));assert math.isfinite(v);return v

def hits(a,parts):return {key:contact(a,b) for key,b in parts.items()}

def build(C):
    world=C
    x0,y0,x1,y1=C.cell_rect();z=C.cell_z();h=C.cell_h()
    # Slide through the nearest short side below the fixed electronics deck.
    # Close the exterior USB opening; board USB stays accessible under the lid.
    old_port,old_seat=cad.charge_port_tool,cad.charge_seat_tool
    far=lambda *args:cad.box(.1,.1,.1,(-100,-100,-100))
    cad.charge_port_tool=cad.charge_seat_tool=far
    try:B=cad.build_body(C);L=cad.build_lid(C)
    finally:cad.charge_port_tool, cad.charge_seat_tool=old_port,old_seat
    D=cad.build_deck(C)
    # Keep USB housing space inside the closed wall, without restoring an
    # exterior charge hole. Header pockets remove local collar corner hits.
    from probe_internal_assembly import board_parts as modeled_board_parts
    electronics=modeled_board_parts(C)
    for name in ('usb','header0','header1','fillet0','fillet1'):
        envelope=electronics[name];lo=envelope.bounds[0]-.15;size=envelope.extents+.3
        tool=cad.box(*size,lo)
        B=cad.dif(B,tool);L=cad.dif(L,tool)
    transform=cad.np.eye(4)
    if C.style=='wrist':
        # Wrist hatch uses x_max, keeping both NATO end bars intact.
        transform=cad.trimesh.transformations.rotation_matrix(math.pi/2,[0,0,1])
        transform[0,3]=C.l
        B,L,D=[cad.xform(m,transform) for m in (B,L,D)]
        g=copy.deepcopy(C.g);q=g[C.style];q['width'],q['length']=C.l,C.w
        cc=next(c for c in q['components'] if c['name']==q['cell'])
        cc.update(x=C.l-y1,y=x0,width=y1-y0,length=x1-x0)
        C=cad.Case(g,C.style);x0,y0,x1,y1=C.cell_rect()
    a,b=x0-.15,x1+.15;bottom,top=z-.15,z+h+.15
    # Clear the entire exit corridor, including the old bay rail and ledge.
    corridor=cad.box(b-a,C.l-y0+15,top-bottom,(a,y0-.15,bottom))
    B=cad.dif(B,corridor)
    dx0,dx1=a-1.2,b+1.2;db,dt=bottom-.3,top+.3
    travel=top+.3-db
    open_top=dt+travel;back=C.l+(2.35 if C.style=="receiver" else .7)
    guides=[];stops=[];ears=[]
    for left in (True,False):
        xx=dx0-1.5 if left else dx1-1.
        rail=cad.box(2.5,back+2.8-(C.l-.4),C.hb-.1-.8,(xx,C.l-.4,.8))
        gx=dx0-.2 if left else dx1-1.2
        channel=cad.box(1.4,2.,C.hb+1-db+.02,(gx,back+.15,db-.02))
        guides.append(cad.dif(rail,channel))
        ears.append(cad.box(2.5,back+2.8-(C.l-.3),C.g['lid']-.05,(xx,C.l-.3,C.hb+.05)))
        stops.append(cad.box(1.35,1.95,C.hb+.1-open_top-.2,(gx+.025,back+.175,open_top+.2)))
    # Outer bridge catches the panel's flexible tab, without blocking its plate.
    strike=cad.box(dx1-dx0-1.6,.7,1.,(dx0+.8,back+2.1,dt-.1))
    # Support the connector pocket while reserving the tab release envelope.
    # This is a clearance closure; sealing is not claimed.
    sill=cad.box(dx1-dx0,back+.15-(C.l-.4),db-.82,(dx0,C.l-.4,.8))
    roof=cad.box(dx1-dx0,back-.45-(C.l-.4),C.hb-dt-.05,(dx0,C.l-.4,dt+.05))
    B=cad.uni(B,*guides,strike,sill,roof)
    L=cad.uni(L,*ears,*stops)
    panel=cad.box(dx1-dx0,1.2,dt-db,(dx0,back+.4,db))
    root,free=dx0+2.,dx1-2.
    tab_lo,tab_hi=db+2.,dt-.45
    slots=[cad.box(free-root+.5,2.,.45,(root,back+.2,tab_lo-.45)),
           cad.box(free-root+.5,2.,.45,(root,back+.2,tab_hi)),
           cad.box(.45,2.,tab_hi-tab_lo+.9,(free,back+.2,tab_lo-.45))]
    panel=cad.dif(panel,slots)
    # Thinner long tab, rooted at one end; nominal release travel is 0.65 mm.
    panel=cad.dif(panel,cad.box(free-root+.05,.4,tab_hi-tab_lo,(root,back+1.2,tab_lo)))
    tooth=cad.box(1.5,1.4,.5,(free-1.7,back+1.15,tab_hi-.55))
    pad=cad.box(2.2,1.4,.9,(free-2.4,back+1.15,tab_lo+.1))
    panel=cad.uni(panel,tooth,pad)
    # Release is a conditional envelope, not a printed-fatigue measurement.
    flex_region=cad.box(free-root+.45,3.,tab_hi-tab_lo+.1,(root,back+.1,tab_lo-.05))
    tab=cad.inter(panel,flex_region)
    released=cad.uni(cad.dif(panel,flex_region),shift(tab,[0,-.65,0]))
    inv=cad.np.linalg.inv(transform)
    B,L,D,panel,released,tab,pad=[cad.xform(m,inv) for m in (B,L,D,panel,released,tab,pad)]
    return {'body':B,'lid':L,'deck':D,'panel':panel,'released_panel':released,
            'travel':travel,'port':[a,b,bottom,top],'guide_stop_top':open_top+.2,
            'tab_nominal':tab,'finger_pad':pad,'transform':transform}

evidence={'released':False,'hardware_measured':False,'baseline_revision':p['revision'],
          'concept':'Captive battery-side panel slides upward; press flexible tab then lift. Battery pulls sideways through its nearest short end. Main lid/deck/strap/mount remain fitted.',
          'contact_limit_mm3':LIMIT,'source_hashes':baseline,'styles':{},
          'scope':'Nominal maximum cell with 0.1mm allowance; closed/open panel and fixed electronics. Actual JST housing, leads/slack, pull ribbon, release force, printed fit, cycle life and mounted hand access remain unqualified.'}
scenes=[]
for style in ('receiver','wrist','keypad'):
    q=copy.deepcopy(p)
    if style=='wrist':
        # Move the bay clear of the front screw; preserve screw and NATO datums.
        cell=next(c for c in q[style]['components'] if c['name']==q[style]['cell'])
        cell['y']+=6.5;q[style]['deck']['y1']=cell['y']+cell['length']+.5
    C=cad.Case(q,style);parts=build(C)
    fixed={key:parts[key] for key in ('body','lid','deck')};fixed.update(board_parts(C))
    if C.p.get('oled'):fixed['oled']=oled(C)
    # Real screw shafts must remain fitted during battery exchange.
    for i,(sx,sy) in enumerate(C.p['fasteners']):
        fixed[f'screw_{i}']=cad.cyl_at(2.5,1.,C.hb-.1,sx,sy)
    x0,y0,x1,y1=C.cell_rect();z=C.cell_z();h=C.cell_h()
    cell=cad.box(x1-x0+.2,y1-y0+.2,h+.2,(x0-.1,y0-.1,z-.1))
    move=(C.w-x0+5.) if style=='wrist' else C.l-y0+5.
    # Axis-aligned maximum-pack box gives an exact straight extraction sweep.
    extraction=cad.box(x1-x0+.2+(move if style=='wrist' else 0),
                       y1-y0+.2+(move if style!='wrist' else 0),h+.2,(x0-.1,y0-.1,z-.1))
    normal=[1.,0,0] if style=='wrist' else [0,1.,0]
    row={'case_frame_mm':[C.w,C.l,C.lid_top()], 'port_face':'x_max' if style=='wrist' else 'y_max', 'cell_pose_mm':[x0,y0,z], 'panel_travel_mm':parts['travel'],
         'fixed_parts_retained':list(fixed),'cell_exit_contacts_mm3':hits(extraction,fixed),
         'panel_closed_contacts_mm3':hits(parts['panel'],fixed),
         'panel_open_contacts_mm3':hits(shift(parts['panel'],[0,0,parts['travel']]),fixed),
         'released_slide_contacts_mm3':{},'mesh_checks':{},
         'latch_engagement_witness_mm3':contact(shift(parts['panel'],[0,0,.9]),parts['body']),
         'upper_stop_witness_mm3':contact(shift(parts['panel'],[0,0,parts['travel']+.65]),parts['lid']),
         'outer_capture_witness_mm3':contact(shift(parts['panel'],normal),parts['body'])}
    for n in range(13):
        dz=parts['travel']*n/12
        row['released_slide_contacts_mm3'][f'{dz:.4f}']=hits(shift(parts['released_panel'],[0,0,dz]),fixed)
    # Exact continuous surface sweep, independent of the sampled poses above.
    continuous=sweep(parts['released_panel'],[0,0,parts['travel']])
    row['continuous_released_slide_contacts_mm3']=hits(continuous,fixed)
    row['body_lid_contacts_mm3']=contact(parts['body'],parts['lid'])
    if C.p.get('sidebar'):
        sb=C.p['sidebar'];sw=C.comp(sb['switch'])
        back_switch=cad.box(sw['width'],sw['length'],6.,(sw['x'],sw['y'],sb['z']-3.))
        row['back_switch_contacts_mm3']=hits(back_switch,{k:parts[k] for k in ('body','lid','deck')})
    if style=='wrist':
        wb=C.g['watch_bars'];cx=C.w/2.;bd=wb['bar'];arm=wb['arm_width'];span=wb['clear_width']+2*arm
        preserved=[]
        for yc,sgn in ((0.,-1.),(C.l,1.)):
            bar=cad.cyl(bd,span,'x',(cx,yc+sgn*(bd/2-wb['bite']),wb['standoff']+bd/2))
            preserved.append(volume(cad.dif(bar,parts['body'])))
        row['missing_NATO_bar_stock_mm3']=preserved
    # A conditional connector envelope, not a manufacturer measured housing.
    # It stays outside the cell, below the deck and can be pulled out first.
    if style=='wrist':
        connector=cad.box(5.4,8.4,4.4,(x1+.35,y0+.3,z-.05))
        connector_exit=cad.box(5.4+move,8.4,4.4,(x1+.35,y0+.3,z-.05))
    else:
        # Park the mating housing behind the short battery edge. The pitcher
        # needs a deeper local pocket; other case dimensions are preserved.
        cx=(x0+x1)/2-4.2;cy=y1+.3
        connector=cad.box(8.4,5.4,4.4,(cx,cy,z-.05))
        connector_exit=cad.box(8.4,5.4+move,4.4,(cx,cy,z-.05))
    row['conditional_connector_static_contacts_mm3']=hits(connector,{**fixed,'cell':cell})
    row['conditional_connector_exit_contacts_mm3']=hits(connector_exit,{**fixed,'cell':cell})
    row['body_material_mm3']=volume(parts['body'])
    row['lid_material_mm3']=volume(parts['lid'])
    row['panel_material_mm3']=volume(parts['panel'])
    row['baseline_body_lid_material_mm3']=volume(cad.build_body(C))+volume(cad.build_lid(C))
    row['net_material_delta_mm3']=row['body_material_mm3']+row['lid_material_mm3']+row['panel_material_mm3']-row['baseline_body_lid_material_mm3']
    for name in ('body','lid','deck','panel'):
        mesh=parts[name];bed=cad.prepare_export(cad.sit_on_bed(mesh))
        path=OUT/f'{style}_{name}.stl';bed.export(path)
        raw=cad.trimesh.load(path,force='mesh',process=True)
        row['mesh_checks'][name]={'watertight':bool(raw.is_watertight),
            'winding_consistent':bool(raw.is_winding_consistent),'single_shell':len(raw.split(only_watertight=False))==1,
            'positive_finite_volume':bool(math.isfinite(raw.volume) and raw.volume>0),
            'source_volume_mm3':volume(mesh),'stl_volume_mm3':volume(raw),'volume_delta_mm3':abs(volume(raw)-volume(mesh))}
    groups=[row['cell_exit_contacts_mm3'],row['panel_closed_contacts_mm3'],row['panel_open_contacts_mm3']]
    groups+=list(row['released_slide_contacts_mm3'].values())
    groups.append(row['continuous_released_slide_contacts_mm3'])
    groups+=[row['conditional_connector_static_contacts_mm3'],row['conditional_connector_exit_contacts_mm3']]
    row['geometry_contacts_pass']=all(v<LIMIT for values in groups for v in values.values())
    row['mesh_pass']=all(all(v[k] for k in ('watertight','winding_consistent','single_shell','positive_finite_volume')) for v in row['mesh_checks'].values())
    row['capture_witnesses_present']=all(row[k]>LIMIT for k in ('latch_engagement_witness_mm3','upper_stop_witness_mm3','outer_capture_witness_mm3'))
    evidence['styles'][style]=row
    print(style, json.dumps({k:row[k] for k in ('geometry_contacts_pass','mesh_pass','capture_witnesses_present','net_material_delta_mm3')}),flush=True)
    rotation=cad.trimesh.transformations.rotation_matrix(math.pi,[0,0,1]);rotation[:2,3]=[C.w,C.l]
    if style=='keypad':
        rotation=cad.trimesh.transformations.rotation_matrix(-math.pi/2,[0,0,1]);rotation[1,3]=C.w
    for state,dz in (('Closed',0.),('Open',parts['travel'])):
        items=[(parts['body'],cad.hex_rgb(p['palette']['cyan'])),(parts['lid'],cad.hex_rgb(p['palette']['pink'])),
               (parts['deck'],(.65,.72,.78)),(shift(parts['panel'],[0,0,dz]),(.94,.94,.96)),
               (cell,(.45,.48,.5))]
        for b in C.buttons():
            cx,cy=C.button_center(b)
            items.append((cad.xform(cad.build_plunger_local(C,b),C.frame(cx,cy)),(.94,.94,.96)))
        if C.p.get('sidebar'):
            items.append((cad.xform(cad.build_side_plunger_local(C),cad.side_plunger_matrix(C)),(.94,.94,.96)))
        if C.p.get('bezel'):
            items.append((cad.xform(cad.build_bezel_local(C),cad.bezel_matrix(C)),cad.hex_rgb(p['palette']['pink'])))
        scenes.append((style+' / '+state,[(cad.xform(m,rotation),color) for m,color in items]))
assert baseline=={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in baseline}
(OUT/'evidence.json').write_text(json.dumps(evidence,indent=2),encoding='utf-8')
from PIL import Image,ImageDraw
image=Image.new('RGB',(1440,780),'white');draw=ImageDraw.Draw(image)
for i,(label,items) in enumerate(scenes):
    tile=cad.render_mesh_array(items,470,345,ss=2)
    x=(i//2)*480;y=(i%2)*390
    image.paste(tile,(x,y+35));draw.text((x+16,y+12),label,fill='black')
image.save(OUT/'sliding-panel-study.png')
print('Evidence and renders:',OUT,flush=True)
