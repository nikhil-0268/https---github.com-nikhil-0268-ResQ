import React,{useEffect,useRef,useState} from 'react';
import {Mic,Square,Keyboard,Check} from 'lucide-react';
import {createDictation} from './speech';
import {useApp} from './common';

export default function VoiceReportInput({value,onChange,onActiveChange,disabled=false}){
  const {t,lang}=useApp();
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;
  const [state,setState]=useState('idle'),[editing,setEditing]=useState(!Recognition),[error,setError]=useState(''),[speechLang,setSpeechLang]=useState(lang==='ne'?'ne-NP':'en-US');
  const control=useRef(null),field=useRef(null);
  const active=state!=='idle';
  useEffect(()=>()=>control.current?.dispose(),[]);
  const errors={
    'not-allowed':t('Microphone access was denied. Allow it in your browser or type below.','माइक्रोफोन अनुमति छैन। ब्राउजरमा अनुमति दिनुहोस् वा तल लेख्नुहोस्।'),
    'service-not-allowed':t('Speech recognition is disabled by this browser. You can type below.','यो ब्राउजरमा वाक् पहिचान बन्द छ। तल लेख्न सक्नुहुन्छ।'),
    'audio-capture':t('No microphone is available. Connect one or type below.','माइक्रोफोन उपलब्ध छैन। जडान गर्नुहोस् वा तल लेख्नुहोस्।'),
    'no-speech':t('No speech was captured. Tap the mic to try again, or type below.','बोली सुनिएन। फेरि प्रयास गर्नुहोस् वा तल लेख्नुहोस्।'),
    'network':t('The speech service could not connect. Your text is kept; typing works offline.','वाक् सेवामा जडान भएन। लेखिएको सुरक्षित छ; अफलाइन लेख्न सकिन्छ।'),
    'language-not-supported':t('This speech language is unavailable in your browser. Choose another or type below.','यो भाषा उपलब्ध छैन। अर्को भाषा छान्नुहोस् वा तल लेख्नुहोस्।'),
  };
  function updateState(next){setState(next);onActiveChange(next!=='idle')}
  function start(){
    if(!Recognition||disabled)return;
    control.current?.dispose();setError('');setEditing(false);
    control.current=createDictation({Recognition,initialText:value,language:speechLang,onText:onChange,onState:updateState,onError:code=>{setError(errors[code]||t('Voice input could not start. Your text is kept; type below or try again.','आवाज सुरु भएन। लेखिएको सुरक्षित छ; तल लेख्नुहोस् वा फेरि प्रयास गर्नुहोस्।'));setEditing(true)}});
    control.current.start();
  }
  return <div className={'voice-report-input '+(active?'is-listening':'')}>
    <div className="voice-toolbar">
      <button type="button" className={'voice-mic '+(active?'active':'')} aria-label={active?t('Stop listening','सुन्न रोक्नुहोस्'):t('Start voice report','आवाजबाट रिपोर्ट सुरु गर्नुहोस्')} aria-pressed={active} disabled={disabled||!Recognition||state==='finishing'} onClick={()=>active?control.current?.stop():start()}>{active?<Square size={25} fill="currentColor"/>:<Mic size={32}/>}</button>
      <div className="voice-instruction"><strong>{state==='starting'?t('Opening microphone…','माइक्रोफोन खोल्दै…'):state==='finishing'?t('Finishing your transcript…','बोलीको पाठ पूरा गर्दै…'):active?t('Listening. Tell us what happened.','सुन्दैछ। के भयो बताउनुहोस्।'):t('Tap the mic. Tell us what happened.','माइक थिच्नुहोस्। के भयो बताउनुहोस्।')}</strong><span>{active?t('Pause to finish, or tap to stop.','रोकिएपछि पाठ पूरा हुन्छ वा रोक्न थिच्नुहोस्।'):t('Speak naturally. Review the text before sending.','सहज रूपमा बोल्नुहोस्। पठाउनुअघि पाठ जाँच्नुहोस्।')}</span></div>
      <div className={'voice-wave '+(active?'active':'')} aria-hidden="true">{[0,1,2,3,4].map(i=><i key={i} style={{'--bar':i}}/>)}</div>
    </div>
    <div className="voice-options"><label htmlFor="speech-language">{t('Spoken language','बोल्ने भाषा')}</label><select id="speech-language" value={speechLang} disabled={active||disabled} onChange={e=>setSpeechLang(e.target.value)}><option value="en-US">English</option><option value="ne-NP">नेपाली</option></select><span className="voice-status" role="status">{active?t('LIVE TRANSCRIPT','प्रत्यक्ष पाठ'):value?t('READY TO REVIEW','समीक्षाका लागि तयार'):t('VOICE FIRST','आवाजबाट सुरु')}</span></div>
    <label className="transcript-label" htmlFor="report-transcript">{t('Report transcript','रिपोर्टको पाठ')}<textarea ref={field} id="report-transcript" required minLength={3} maxLength={5000} rows={3} value={value} readOnly={!editing||active} onChange={e=>onChange(e.target.value)} placeholder={t('Your words will appear here as you speak…','बोल्दा तपाईंको शब्द यहाँ देखिन्छ…')}/></label>
    <div className="voice-backup"><button type="button" disabled={active||disabled} className="typing-backup" onClick={()=>{setEditing(!editing);if(!editing)requestAnimationFrame(()=>field.current?.focus())}}>{editing?<Check size={14}/>:<Keyboard size={15}/>} {editing?t('Done editing','सम्पादन सकियो'):value?t('Edit transcript','पाठ सच्याउनुहोस्'):t('Prefer to type instead?','बरु लेख्न चाहनुहुन्छ?')}</button><span>{t('Never sent automatically','स्वतः पठाइँदैन')}</span></div>
    <p className="voice-service-note">{!Recognition?t('Voice input is unavailable in this browser. Use the typing backup below.','यो ब्राउजरमा आवाज उपलब्ध छैन। पाठ लेख्नुहोस्।'):t('Browser speech recognition may use an online service. Availability varies by browser and language.','ब्राउजरको वाक् पहिचानले अनलाइन सेवा प्रयोग गर्न सक्छ। उपलब्धता ब्राउजर र भाषाअनुसार फरक हुन्छ।')}</p>
    {error&&<p className="voice-error" role="alert">{error}</p>}
    <span className="sr-only" aria-live="polite" aria-atomic="true">{active?value:''}</span>
  </div>;
}
