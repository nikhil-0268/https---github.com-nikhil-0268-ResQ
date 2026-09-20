// Small browser-dictation adapter. Acoustic WAV recording remains in Signals.jsx.
// Recognition results are browser-provided speech text, never simulated detections.
export function createDictation({Recognition, initialText='', language='en-US', onText, onState, onError}) {
  const recognition=new Recognition();
  recognition.lang=language;
  recognition.continuous=false;
  recognition.interimResults=true;
  recognition.maxAlternatives=1;
  let disposed=false, stopping=false, ended=false, text=initialText;
  const base=initialText.trimEnd();
  const stop=()=>{
    if(disposed||stopping||ended)return;
    stopping=true;onState('finishing');
    try{recognition.stop()}catch{finish()}
  };
  const finish=()=>{
    if(disposed||ended)return;
    ended=true;
    onText(text);onState('idle');
  };
  recognition.onstart=()=>{if(!disposed&&!ended&&!stopping)onState('listening')};
  recognition.onresult=event=>{
    if(disposed||ended)return;
    // Rebuild from this session's result list: interim revisions replace, not append.
    const spoken=Array.from(event.results,r=>r[0]?.transcript||'').join(' ').trim();
    if(spoken){text=[base,spoken].filter(Boolean).join(' ').slice(0,5000);onText(text)}
  };
  recognition.onspeechend=stop;
  recognition.onend=finish;
  recognition.onerror=event=>{
    if(disposed||ended)return;
    onError(event.error||'unknown');finish();
  };
  return {
    start(){onState('starting');try{recognition.start()}catch{onError('start-failed');finish()}},
    stop,
    dispose(){disposed=true;recognition.onstart=recognition.onresult=recognition.onspeechend=recognition.onend=recognition.onerror=null;try{recognition.abort()}catch{}},
  };
}
