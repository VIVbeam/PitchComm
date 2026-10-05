"""Publish matching v8 development fit package with explicitly nonprinted references."""
from pathlib import Path
import json,hashlib,shutil,zipfile
ROOT=Path(__file__).resolve().parents[2];SRC=ROOT/'.tools/cad-runs/pull-sling-v3'
BASE=ROOT/'cad/prototypes/side-slider-v7';OUT=ROOT/'cad/prototypes/side-slider-v8'
assert not OUT.exists()
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
old=json.loads((BASE/'manifest.json').read_text())
protected=old['preserved_v20_files_sha256'];assert all(sha(ROOT/n)==h for n,h in protected.items())
checks=[SRC/'evidence.json',SRC/'serialized-evidence.json',SRC/'native/reopen/evidence.json']
assert all(json.loads(p.read_text())['passed'] for p in checks)
data=json.loads(checks[0].read_text());native=json.loads(checks[2].read_text())
assert sha(SRC/'native/PitchComm-v8-battery-access-fit.dwg')==native['drawing_sha256']
OUT.mkdir();(OUT/'evidence').mkdir()
for folder in ('stl','plates','assemblies','references'):shutil.copytree(SRC/folder,OUT/folder)
shutil.copytree(BASE/'source',OUT/'source')
for name in ('build_pull_sling_v3.py','verify_pull_sling_v3.py','check_pull_sling_native.py','render_pull_sling_pack.py','package_pull_sling.py'):
    shutil.copyfile(ROOT/'.tools/cad-source'/name,OUT/'source'/name)
shutil.copyfile(SRC/'native/PitchComm-v8-battery-access-fit.dwg',OUT/'PitchComm-v8-battery-access-fit.dwg')
for path,dest in ((SRC/'evidence.json','pull-sling-evidence.json'),(SRC/'serialized-evidence.json','serialized-evidence.json'),
                  (SRC/'native/reopen/evidence.json','native-saved-evidence.json'),
                  (BASE/'evidence/wall-stock-evidence.json','inherited-v7-wall-stock-evidence.json'),
                  (BASE/'evidence/sliding-motion-evidence.json','inherited-v7-sliding-motion-evidence.json'),
                  (BASE/'evidence/evidence.json','inherited-v7-controls-evidence.json')):
    shutil.copyfile(path,OUT/'evidence'/dest)
for path,dest in ((SRC/'pull-sling-cutaway.png','pull-sling-cutaway.png'),(SRC/'complete-closed-open-v3.png','closed-open.png'),
                  (SRC/'print-plates-preview-v3.png','print-plates.png'),(BASE/'landscape-controls.png','landscape-controls.png')):
    shutil.copyfile(path,OUT/dest)
guide=(BASE/'PRINT_AND_ASSEMBLY.txt').read_text(encoding='utf-8')
if json.loads((ROOT/'gui/catalog.json').read_text(encoding='utf-8'))['dictionary']=='94b7a24a':
    guide=guide.replace('Separate two-segment pitch firmware/console/audio changes are still staged, not shipped.',
                        'Current workspace firmware/console/audio uses two-segment dictionary 94b7a24a.\nHost and simulated browser checks pass; real Nordic SDK build and hardware operation remain unverified.')
guide=guide.replace('SIDE-SLIDER v7','SIDE-SLIDER v8 BATTERY ACCESS')
guide=guide.replace('PitchComm-slider-v7-complete.dwg:34 editable native solids, reopened/kernel and geometry checked.',
                    'PitchComm-v8-battery-access-fit.dwg:46 editable native solids:34 printed parts plus12 nonprinted references.\nPART_ layers are printed parts; REF_ layers are soft film, adhesive, cell and assumed connector.\nreferences/:three assembled battery-access 3MFs with nonprinted references. NEVER slice these as print plates.')
guide=guide.replace('Previews show the actual meshes. Grey cells are dimensional placeholders; connector/leads are not rendered.',
                    'Previews show actual meshes. Grey cells and red connector blocks are dimensional assumptions; leads are not rendered.\nOrange is a thin nonconductive film sling; yellow is its case-floor adhesive, both NONPRINTED.')
guide=guide.replace('Full factory lead length/slack, solder joints, strain relief, pull ribbon and connector grip access remain unqualified.',
                    'Full factory lead length/slack, solder joints, strain relief, actual connector grip access and sling material/adhesion remain unqualified.')
guide=guide.replace('This supersedes the v5 case-only review prototype. It remains a development fit package.',
                    'This supersedes the v7 fit package for the optional pull-sling study. It remains a development fit package.')
guide=guide.replace('All34STLs and683MF mesh objects read back with correct shell, winding, volume and placement.',
                    'All34STLs and1143MF mesh objects read back;33 printable shapes are byte-identical to v7.\nThe watch body alone changes: an anchor land plus local clearance pocket, with no outside-size growth.')
guide=guide.replace('Native saved drawing:34valid ShapeManager solids,audit0,mass/bounds and34closed exported boundaries match.',
                    'Saved native drawing:46 valid ShapeManager solids,AUDIT0; all mass/bounds and exported boundaries match.\nThe changed watch body also clears the exact continuously released-panel sweep.')
intro=['','OPTIONAL CASE-ANCHORED PULL SLING — FIRST FIT STUDY',
       'This is a geometric removal aid; adhesion, bending and actual pull force have not been tested.',
       'Use smooth, electrically insulating flexible film, modeled6mm wide and0.1mm thick maximum.',
       'No metallic tape or stiff printed strap. No qualified film/adhesive product is specified.',
       'The folded strip goes beneath the cell, around its far end, and above the cell toward the hatch.',
       'Fix ONLY the lower strip to the designated CASE FLOOR anchor. Do not glue it to the battery pouch.',
       'Modeled adhesive thickness0.1mm maximum. Sling and adhesive replace the prior0.2mm floor allowance.',
       'Do not add them on top of an existing foam stack. Account for actual film, adhesive, pouch and folds.',
       'Pitcher/catcher anchor6x8mm (48mm2); watch6x3mm (18mm2). Small anchor strength is unmeasured.',
       f'Watch adds{data["watch_added_material_mm3"]:.2f}mm3 net case material within the existing bounds.',
       'The free end stays0.15mm behind the nominal inward release-tab envelope while closed.',
       'Open panel, disconnect by the connector housings, and park leads clear before pulling the strip.',
       'Housing extraction and film deployment clear the modeled parts; actual leads have not been modeled.',
       'The rectilinear U model lets the cell protrude6mm beyond the outer guides for hand removal.',
       'Do not continue pulling after that handoff; grasp the cell without pinching or levering its pouch.',
       'Feed the loop back into place when inserting the replacement cell; keep strip and leads out of guides.',
       'This ideal model reserves no bend radius or printed tolerance. Prototype with an inert dummy first.',
       'Reject the sling if it jams, loads leads, abrades the pouch, detaches, or obstructs panel release.',
       'Do not treat the modeled path as proof of safe force, swelling allowance or repeated-use durability.',
       'Reference connector box8.4x5.4x4.4mm is still assumed, not measured.',
       'Pitcher/catcher box moves0.1mm downward versus v7 to clear the top strip; watch pose is unchanged.',
       'Rectilinear lengths below are modeled budgets, not qualified cutting dimensions:']
for style,label in (('receiver','Pitcher'),('wrist','Watch'),('keypad','Catcher')):
    r=data['styles'][style]
    intro.append(f'{label}: film path{r["film_rectilinear_length_budget_mm"]:.2f}mm; cell travel{r["handoff_cell_displacement_mm"]:.2f}mm; free-end travel{r["free_tip_travel_mm"]:.2f}mm.')
intro+=['Include practical bend/handling requirements only after measuring the real assembly.','']
guide=guide.replace('\nMATCHED FILE SET\n','\n'+'\n'.join(intro)+'\nMATCHED FILE SET\n')
(OUT/'PRINT_AND_ASSEMBLY.txt').write_text(guide,encoding='utf-8')
assert all(sha(ROOT/n)==h for n,h in protected.items())
files={str(p.relative_to(OUT)).replace('\\','/'):sha(p) for p in OUT.rglob('*') if p.is_file()}
manifest={'development_fit_prototype':True,'hardware_measured':False,'unique_printed_parts':34,'field_set_printed_pieces':41,
          'quantity_by_style':{'receiver':1,'wrist':2,'keypad':1},'nonprinted_references':12,'changed_printed_part':'wrist_body',
          'watch_added_material_mm3':data['watch_added_material_mm3'],'verification':{'native_solids':46,'native_audit_errors':0,'readback_3mf_objects':114},
          'preserved_v20_files_sha256':protected,'files_sha256':files}
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2))
archive=ROOT/'cad/prototypes/PitchComm-side-slider-v8-battery-access-fit.zip';assert not archive.exists()
with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
    for p in OUT.rglob('*'):
        if p.is_file():z.write(p,str(p.relative_to(OUT)).replace('\\','/'))
with zipfile.ZipFile(archive) as z:
    assert z.testzip() is None
    for name,digest in files.items():assert hashlib.sha256(z.read(name)).hexdigest()==digest
print('PASS: complete matched v8 development package, every archive hash verified:',archive)
