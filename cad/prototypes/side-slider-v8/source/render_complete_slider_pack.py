"""Render serialized full assemblies and actual print-plate positions."""
from probe_internal_assembly import ROOT,cad as m
import json,math,zipfile,xml.etree.ElementTree as ET,inspect
from PIL import Image,ImageDraw,ImageFont
OUT=ROOT/'.tools/cad-runs/side-slider-v7/complete-controls-v1'
src=json.loads((OUT/'evidence.json').read_text());study=json.loads((OUT.parent/'evidence.json').read_text())
NS={'c':'http://schemas.microsoft.com/3dmanufacturing/core/2015/02'}
# Center the projected extents, since tall parts at one end of a plate make
# its 3-D bounding-box center an inaccurate center for the rendered image.
source=inspect.getsource(m.render_mesh_array)
source=source.replace('ex, ey = px.max() - px.min(), py.max() - py.min()',
    'px -= (px.max() + px.min()) / 2; py -= (py.max() + py.min()) / 2\n    ex, ey = px.max() - px.min(), py.max() - py.min()')
exec(compile(source,'centered-preview-only','exec'),m.__dict__)
def read(path):
    with zipfile.ZipFile(path) as z:r=ET.fromstring(z.read('3D/3dmodel.model'))
    items=[]
    for obj in r.findall('c:resources/c:object',NS):
        if 'assembly'==obj.attrib['name']:continue
        name=obj.attrib['name'];vs=[[float(v.attrib[k]) for k in ('x','y','z')] for v in obj.findall('c:mesh/c:vertices/c:vertex',NS)]
        fs=[[int(f.attrib[k]) for k in ('v1','v2','v3')] for f in obj.findall('c:mesh/c:triangles/c:triangle',NS)]
        mesh=m.trimesh.Trimesh(vertices=vs,faces=fs,process=False)
        color=next(p['color'] for p in src['parts'] if p['name']==name)
        items.append((name,mesh,m.hex_rgb(color)))
    return items
font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',22)
img=Image.new('RGB',(1530,920),'#f7f8fa');draw=ImageDraw.Draw(img)
plates=Image.new('RGB',(1530,480),'#f7f8fa');pd=ImageDraw.Draw(plates)
for idx,style in enumerate(('receiver','wrist','keypad')):
    name=('Pitcher','Watch','Catcher')[idx];q=src['styles'][style]['case_profile'];W,L=q['width'],q['length']
    R=m.trimesh.transformations.rotation_matrix(math.pi,[0,0,1]);R[:2,3]=[W,L]
    asm=read(OUT/'assemblies'/f'{style}_complete_assembly.3mf')
    for opened in (False,True):
        items=[]
        for stem,mesh,col in asm:
            mesh=mesh.copy()
            if opened and stem==style+'_panel':mesh.apply_translation([0,0,study['styles'][style]['panel_travel_mm']])
            mesh.apply_transform(R);items.append((mesh,col))
        if opened:
            cell=next(c for c in q['components'] if c['name']==q['cell'])
            z=study['styles'][style]['cell_pose_mm'][2]
            model=m.box(cell['width'],cell['length'],4.3,(cell['x'],cell['y'],z))
            model.apply_translation([W-cell['x']-cell['width']+15,0,0] if style=='wrist' else [0,L-cell['y']-cell['length']+15,0])
            model.apply_transform(R);items.append((model,(.46,.49,.51)))
        x=idx*510;y=int(opened)*450
        img.paste(m.render_mesh_array(items,500,380,ss=2),(x,y+48))
        draw.text((x+18,y+12),name+(' — panel up / battery out' if opened else ' — closed'),font=font,fill='#202a34')
    pi=read(OUT/'plates'/f'{style}_print_plate.3mf')
    plates.paste(m.render_mesh_array([(mesh,col) for stem,mesh,col in pi],500,390,ss=2),(idx*510,50))
    pd.text((idx*510+16,12),name+' — arranged print plate',font=font,fill='#202a34')
draw.text((18,895),'Complete matching case parts • geometry verified • printed fit, latch durability and full wiring remain untested',font=ImageFont.truetype('C:/Windows/Fonts/segoeui.ttf',16),fill='#485764')
for image,path in ((img,OUT/'complete-closed-open-v2.png'),(plates,OUT/'print-plates-preview-v2.png')):
    assert not path.exists();image.save(path)
print('Rendered complete serialized assemblies and arranged print plates.')
