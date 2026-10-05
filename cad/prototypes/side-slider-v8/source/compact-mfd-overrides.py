"""Isolated parametric prototype of original-footprint landscape control geometry."""
from probe_internal_assembly import ROOT,cad,p
import copy,importlib.util,json
OUT=ROOT/'.tools/cad-runs/side-slider-v7/mfd-source';spec=importlib.util.spec_from_file_location('compact_rotated_cad',OUT/'source/generate_cases.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
q=json.loads((OUT/'source/profiles.json').read_text())
def rot(a):return m.trimesh.transformations.rotation_matrix(a*m.math.pi/180,[0,0,1])
def copy_case(C,sidebar=True,first=True):
    g=copy.deepcopy(C.g)
    if not sidebar:g[C.style]['sidebar']=None
    if not first:g[C.style]['buttons']=[b for b in g[C.style]['buttons']if b['id']!='call_1']
    return m.Case(g,C.style)
old_body=m.build_body;old_lid=m.build_lid;old_deck=m.build_deck;old_parts=m.build_side_plunger_parts_local;old_solid=m.build_side_plunger_solid_local;old_matrix=m.side_plunger_matrix;old_numeral=m.numeral_local;old_style=m.build_style;old_carrier=m.build_carrier
def isx(C):return(C.p.get('sidebar')or{}).get('face')=='x_max'
def body(C):
    if not isx(C):return old_body(C)
    B=old_body(copy_case(C,False,True));sx=C.w;cy=C.p['sidebar']['y'];z=C.p['sidebar']['z']
    # Circular guide and complete head counterbore, centered on the lower edge.
    hole=m.cyl(3.8,C.wall+2.,'x',(sx-C.wall+.5,cy,z))
    well=m.cyl(9.,1.8,'x',(sx-.5,cy,z))
    pocket=m.box(6.85,6.,6.,(sx-C.wall-5.85,cy-3.,z-3.))
    B=m.dif(B,[hole,well,pocket])
    stop=m.box(1.2,6.,z+.5-C.floor+.2,(sx-7.7-1.2,cy-3.,C.floor-.2))
    return m.uni(B,stop)
def lid(C):return old_lid(copy_case(C,False))if isx(C)else old_lid(C)
def deck(C):
    if not isx(C):return old_deck(C)
    D=old_deck(copy_case(C,False));sc=C.comp(C.p['sidebar']['switch'])
    return m.dif(D,m.box(C.w-sc['x']+2.1,sc['length']+.4,7.,(sc['x']-2.,sc['y']-.2,C.deck_z()-3.)))
def proxy(C):
    g=copy.deepcopy(C.g);g[C.style]['length']=C.w
    g['plunger']['face_recess']=C.p['sidebar'].get('face_recess',g['plunger']['face_recess'])
    return m.Case(g,C.style)
def side_parts(C):return old_parts(proxy(C))if isx(C)else old_parts(C)
def side_solid(C):return old_solid(proxy(C))if isx(C)else old_solid(C)
def matrix(C):
    if not isx(C):return old_matrix(C)
    R=rot(-90);R[1,3]=C.p['sidebar']['y'];R[2,3]=C.p['sidebar']['z'];return R
def numeral(C,b,z0,z1,clearance=0):
    mesh=old_numeral(C,b,z0,z1,clearance)
    return m.xform(mesh,rot(90))if C.style=='keypad'else mesh
def carrier(C,mount):
    old=m.Case(p,C.style)
    if C.style=='receiver':
        # Keep screw-driver bores surrounded by a complete lower bridge.
        original=C.g['carrier'].get('loop_x_inset');C.g['carrier']['loop_x_inset']=0.
        G=old_carrier(C,mount)
        for x,y in C.p['fasteners']:
            ring=m.dif(m.cyl_at(8.4,-5.7,-4.55,x,y),m.cyl_at(6.2,-6.,-4.,x,y))
            G=m.uni(G,ring)
        if original is None:C.g['carrier'].pop('loop_x_inset',None)
        return G
    return old_carrier(C,mount)
m.build_body=body;m.build_lid=lid;m.build_deck=deck;m.build_side_plunger_parts_local=side_parts;m.build_side_plunger_solid_local=side_solid;m.side_plunger_matrix=matrix;m.numeral_local=numeral;m.build_carrier=carrier
def style(*args):
    C,report,prints,colors,items=old_style(*args)
    if C.style=='keypad':
        R=rot(-90);R[1,3]=C.w;items=[(m.xform(mesh,R),color)for mesh,color in items]
        report['user_frame']=C.p['user_frame']
    return C,report,prints,colors,items
m.build_style=style
