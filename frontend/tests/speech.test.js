import test from 'node:test';
import assert from 'node:assert/strict';
import {createDictation} from '../src/speech.js';

function setup(initialText=''){
 let recognition,output=initialText,states=[],errors=[];
 class Recognition{
  constructor(){recognition=this;this.stops=0;this.aborts=0}
  start(){this.onstart?.()}
  stop(){this.stops++}
  abort(){this.aborts++}
 }
 const dictation=createDictation({Recognition,initialText,language:'ne-NP',onText:t=>output=t,onState:s=>states.push(s),onError:e=>errors.push(e)});
 const result=(...texts)=>recognition.onresult({results:texts.map(text=>[{transcript:text}])});
 return {dictation,get recognition(){return recognition},get output(){return output},states,errors,result};
}

test('starts only explicitly and configures real interim speech recognition',()=>{
 const s=setup();assert.deepEqual(s.states,[]);s.dictation.start();assert.deepEqual(s.states,['starting','listening']);assert.equal(s.recognition.lang,'ne-NP');assert.equal(s.recognition.interimResults,true);assert.equal(s.recognition.continuous,false);
});
test('interim revisions replace earlier text without duplication and preserve typed prefix',()=>{
 const s=setup('Kalimati.');s.dictation.start();s.result('a build');assert.equal(s.output,'Kalimati. a build');s.result('a building collapsed');assert.equal(s.output,'Kalimati. a building collapsed');s.result('a building collapsed','people are trapped');assert.equal(s.output,'Kalimati. a building collapsed people are trapped');
});
test('silence stops recognition once and accepts final result before finalizing',()=>{
 const s=setup();s.dictation.start();s.result('घर भत्किएको');s.recognition.onspeechend();s.dictation.stop();assert.equal(s.recognition.stops,1);assert.equal(s.states.at(-1),'finishing');s.result('घर भत्किएको छ।');s.recognition.onend();assert.equal(s.output,'घर भत्किएको छ।');assert.equal(s.states.at(-1),'idle');
});
test('manual stop finalizes current transcript without requiring another result',()=>{
 const s=setup();s.dictation.start();s.result('Please investigate');s.dictation.stop();s.recognition.onend();assert.equal(s.output,'Please investigate');assert.equal(s.states.at(-1),'idle');
});
test('denied permission and no-speech preserve an existing report',()=>{
 for(const error of ['not-allowed','no-speech','network']){const s=setup('Existing report');s.dictation.start();s.recognition.onerror({error});s.recognition.onend();assert.equal(s.output,'Existing report');assert.deepEqual(s.errors,[error]);assert.equal(s.states.at(-1),'idle')}
});
test('late callbacks after completion cannot overwrite the transcript',()=>{
 const s=setup();s.dictation.start();s.result('Final words');s.recognition.onend();s.result('Late text');assert.equal(s.output,'Final words');
});
test('unmount aborts recognition and detaches callbacks',()=>{
 const s=setup();s.dictation.start();s.dictation.dispose();assert.equal(s.recognition.aborts,1);assert.equal(s.recognition.onresult,null);assert.equal(s.recognition.onend,null);
});
test('appending dictation respects the API length limit',()=>{
 const s=setup('x'.repeat(4998));s.dictation.start();s.result('more speech');assert.equal(s.output.length,5000);
});
test('browser startup exceptions return to idle without losing input',()=>{
 const s=setup('Existing');s.recognition.start=()=>{throw new Error('Unavailable')};s.dictation.start();assert.equal(s.output,'Existing');assert.deepEqual(s.errors,['start-failed']);assert.equal(s.states.at(-1),'idle');
});
