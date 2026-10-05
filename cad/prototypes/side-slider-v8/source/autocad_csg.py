"""Capture source construction primitives and emit native AutoCAD solid operations."""
import math
import inspect

def install(cad):
    def tagged(mesh,node):
        mesh.metadata['acad_csg']=node
        return mesh
    def tree(mesh):
        if 'acad_csg' not in mesh.metadata:
            raise ValueError('Uncaptured construction primitive')
        return mesh.metadata['acad_csg']
    old_bop=cad.bop
    def bop(op,meshes):
        meshes=list(meshes)
        if any('acad_csg' not in m.metadata for m in meshes):
            return old_bop(op,meshes) # Independent serialization comparisons.
        node={'kind':op,'children':[tree(m) for m in meshes]}
        return tagged(old_bop(op,meshes),node)
    cad.bop=bop
    old_box=cad.box
    def box(w,l,h,pos=(0,0,0)):
        return tagged(old_box(w,l,h,pos),{'kind':'box','size':[w,l,h],'pos':list(pos)})
    cad.box=box
    old_prism=cad.prism_axis
    def prism(poly,axis,a0,a1,offset=(0,0,0)):
        mesh=old_prism(poly,axis,a0,a1,offset)
        if axis=='x':
            pts=[[a0,x,y] for x,y in poly]; delta=[a1-a0,0,0]
        elif axis=='y':
            pts=[[x,a0,y] for x,y in poly]; delta=[0,a1-a0,0]
        else:
            pts=[[x,y,a0] for x,y in poly]; delta=[0,0,a1-a0]
        pts=(cad.np.array(pts)+offset).tolist()
        return tagged(mesh,{'kind':'prism','points':pts,'delta':delta})
    cad.prism_axis=prism
    old_extrude=cad.extrude_poly
    def extrude(poly,z0,z1):
        return tagged(old_extrude(poly,z0,z1),{'kind':'prism',
            'points':[[float(x),float(y),z0] for x,y in poly],'delta':[0,0,z1-z0]})
    cad.extrude_poly=extrude
    old_cyl=cad.cyl
    def cyl(d,h,axis='z',pos=(0,0,0),sections=cad.SECTIONS):
        mesh=old_cyl(d,h,axis,pos,sections)
        T=cad.np.eye(3)
        if axis=='x': T=cad.trimesh.transformations.rotation_matrix(math.pi/2,[0,1,0])[:3,:3]
        if axis=='y': T=cad.trimesh.transformations.rotation_matrix(math.pi/2,[1,0,0])[:3,:3]
        pts=[T@cad.np.array([d/2*math.cos(k*2*math.pi/sections),d/2*math.sin(k*2*math.pi/sections),-h/2])+pos for k in range(sections)]
        return tagged(mesh,{'kind':'prism','points':cad.np.array(pts).tolist(),'delta':(T@cad.np.array([0,0,h])).tolist()})
    cad.cyl=cyl
    old_rbox=cad.rbox
    def rbox(w,l,h,rv,rh,pos=(0,0,0)):
        mesh=old_rbox(w,l,h,rv,rh,pos)
        # rbox translates its three intersecting prisms in-place.
        node=tree(mesh)
        T=cad.np.eye(4);T[:3,3]=pos
        return tagged(mesh,{'kind':'transform','matrix':T.tolist(),'child':node})
    cad.rbox=rbox
    old_xform=cad.xform
    def xform(mesh,T):
        return tagged(old_xform(mesh,T),{'kind':'transform','matrix':T.tolist(),'child':tree(mesh)})
    cad.xform=xform
    # The numeral pocket used an in-place move, which changed the mesh but
    # left its construction tree at the old depth. Route that move through
    # xform so native solids cut the same pocket as the printable mesh.
    if hasattr(cad,'build_plunger_solid_local'):
        source=inspect.getsource(cad.build_plunger_solid_local)
        needle='pocket.apply_translation((0, 0, z_top))'
        if needle in source:
            source=source.replace(needle,'T = np.eye(4); T[2, 3] = z_top; pocket = xform(pocket, T)')
            exec(compile(source,'tracked-numeral-pocket','exec'),cad.__dict__)
    old_hull=cad.trimesh.convex.convex_hull
    def hull(points,*args,**kwargs):
        mesh=old_hull(points,*args,**kwargs)
        # All source hull primitives are convex; a mesh conversion is robust
        # here and does not inherit the thin Boolean triangulation slivers.
        return tagged(mesh,{'kind':'convex','vertices':mesh.vertices.tolist(),'faces':mesh.faces.tolist()})
    cad.trimesh.convex.convex_hull=hull

def emit(cad,node,script,data_dir,sequence):
    def number(v):return format(float(v),'.10f')
    def point(v):return "'("+' '.join(number(x) for x in v)+')'
    def new():
        sequence[0]+=1
        return 'pc-csg-'+str(sequence[0])
    kind=node['kind']
    var=new()
    if kind=='box':
        pos=node['pos'];w,l,h=node['size']
        end=[pos[0]+w,pos[1]+l,pos[2]]
        script.append(f'(command "_.BOX" {point(pos)} {point(end)} {number(h)})')
        script.append(f'(setq {var} (entlast))')
    elif kind=='prism':
        pts=node['points'];delta=node['delta']
        path=data_dir/(var+'.points')
        path.write_text('('+' '.join('('+' '.join(number(x) for x in p)+')' for p in pts)+')\n')
        script.extend([f'(setq pc-input (open "{path.as_posix()}" "r"))',
            '(setq pc-points (read (read-line pc-input)))','(close pc-input)',
            '(apply \'command (append (list "_.3DPOLY") pc-points (list "_Close")))',
            '(setq pc-curve (entlast))',
            f'(command "_.EXTRUDE" pc-curve "" "_Direction" \'(0 0 0) {point(delta)})',
            f'(setq {var} (entlast))'])
    elif kind=='convex':
        mesh=cad.trimesh.Trimesh(vertices=node['vertices'],faces=node['faces'])
        entries=['(0 . "MESH")','(100 . "AcDbEntity")','(100 . "AcDbSubDMesh")',
                 '(71 . 2)','(72 . 0)','(91 . 0)',f'(92 . {len(mesh.vertices)})']
        entries+=['(10 '+' '.join(number(v) for v in p)+')' for p in mesh.vertices]
        entries+=[f'(93 . {4*len(mesh.faces)})']
        for f in mesh.faces:entries+=['(90 . 3)']+[f'(90 . {int(v)})' for v in f]
        entries+=['(94 . 0)','(95 . 0)','(90 . 0)']
        path=data_dir/(var+'.hull')
        path.write_text('('+' '.join(entries)+')\n')
        script.extend([f'(setq pc-input (open "{path.as_posix()}" "r"))',
            '(setq pc-m (entmakex (read (read-line pc-input))))','(close pc-input)',
            '(command "_.CONVTOSOLID" pc-m "")',f'(setq {var} (entlast))'])
    elif kind=='transform':
        child=emit(cad,node['child'],script,data_dir,sequence)
        T=cad.np.array(node['matrix']);R=T[:3,:3].copy()
        if cad.np.linalg.det(R)<0:
            script.extend([f'(command "_.MIRROR3D" {child} "" "_XY" \'(0 0 0) "_Yes")',f'(setq {child} (entlast))'])
            R=R@cad.np.diag([1,1,-1])
        angle=math.acos(max(-1,min(1,(cad.np.trace(R)-1)/2)))
        if angle>1e-8:
            values,vectors=cad.np.linalg.eig(R)
            axis=cad.np.real(vectors[:,cad.np.argmin(cad.np.abs(values-1))])
            cross=cad.np.array([R[2,1]-R[1,2],R[0,2]-R[2,0],R[1,0]-R[0,1]])
            if axis@cross<0:axis=-axis
            script.append(f'(command "_.ROTATE3D" {child} "" "_2points" \'(0 0 0) {point(axis)} {number(math.degrees(angle))})')
        if cad.np.linalg.norm(T[:3,3])>1e-9:
            script.append(f'(command "_.MOVE" {child} "" \'(0 0 0) {point(T[:3,3])})')
        script.append(f'(setq {var} {child})')
    else:
        children=[emit(cad,ch,script,data_dir,sequence) for ch in node['children']]
        cmd={'union':'UNION','intersection':'INTERSECT','difference':'SUBTRACT'}[kind]
        if len(children)>1:
            if kind=='difference':
                args=children[0]+' "" '+' '.join(children[1:])+' ""'
            else:args=' '.join(children)+' ""'
            script.append(f'(command "_.{cmd}" {args})')
            for consumed in children[1:]:
                script.append(f'(if (entget {consumed}) (progn (princ "\\nCSG_BOOLEAN_FAILED_{var}\\n") (quit)))')
        script.append(f'(setq {var} {children[0]})')
    script.append(f'(if (or (null (entget {var})) (/= (cdr (assoc 0 (entget {var}))) "3DSOLID")) (progn (princ "CSG_NODE_FAILED_{var}") (quit)))')
    return var
