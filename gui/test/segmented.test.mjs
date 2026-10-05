import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {command,describe,pitchCode} from '../core.js';
const catalog=JSON.parse(readFileSync(new URL('../catalog.json',import.meta.url),'utf8'));
const counts={rows:catalog.rows.length,cols:catalog.cols.length,maxPitch:catalog.pitchFlow.maxCode,
  maxPlay:catalog.plays.length,pitchFlow:catalog.pitchFlow};
const session={client:'1a2b3c4d',boot:'0011223344556677',dictionary:catalog.dictionary,clock:5000};
test('legacy complete-pitch commands remain bounded by full-pitch range',()=>{
  assert.match(command(1,1,9,3,3,session,counts),/ p 9 3 3 /);
  assert.throws(()=>command(1,1,10,1,1,session,counts));
});
test('all two-part pitch commands and labels preserve pitch identity',()=>{
  for(const p of catalog.pitches){
    assert.match(command(1,1,p.key,0,0,session,counts,'type'),new RegExp(` t ${p.key} `));
    assert.equal(describe(catalog,1,counts.pitchFlow.typeBase+p.key),`${p.speech} · awaiting nod`);
    for(const row of catalog.rows)for(const col of catalog.cols){
      assert.match(command(1,1,p.key,row.key,col.key,session,counts,'placement'),new RegExp(` l ${p.key} ${row.key} ${col.key} `));
      const code=counts.pitchFlow.placementBase+pitchCode(p.key,row.key,col.key,counts.rows,counts.cols);
      const loc=catalog.locations.find(l=>l.row===row.key&&l.col===col.key);
      assert.equal(describe(catalog,1,code),`${p.speech} · ${loc.speech} (placement)`);
    }
  }
});
test('two-part commands reject invalid pitch, height, side and stage',()=>{
  for(const type of [0,10,1.5,NaN]){
    assert.throws(()=>command(1,1,type,1,1,session,counts,'type'));
    assert.throws(()=>command(1,1,type,1,1,session,counts,'placement'));
  }
  for(const [row,col] of [[0,1],[4,1],[1,0],[1,4]])assert.throws(()=>command(1,1,1,row,col,session,counts,'placement'));
  assert.throws(()=>command(1,1,1,1,1,session,counts,'unknown'));
});
