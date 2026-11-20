const enable=document.getElementById('enable-reminders'),disable=document.getElementById('disable-reminders'),test=document.getElementById('test-reminder'),status=document.getElementById('reminder-status');
const supported='serviceWorker' in navigator&&'PushManager' in window&&'Notification' in window;
const ios=/iPad|iPhone|iPod/.test(navigator.userAgent)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
const installed=matchMedia('(display-mode: standalone)').matches||navigator.standalone;
let subscription=null;
function show(text,error=false){status.textContent=text;status.classList.toggle('error',error);}
function buttons(){disable.hidden=test.hidden=!subscription;enable.hidden=!!subscription;}
async function api(path,sub){const res=await fetch(path,{method:sub?'POST':'GET',headers:sub?{'Content-Type':'application/json'}:{},body:sub?JSON.stringify(sub.toJSON()):undefined});const data=await res.json();if(!res.ok)throw new Error(data.error||'Could not update reminders. Try again.');return data;}
function bytes(value){return Uint8Array.from(atob(value.replace(/-/g,'+').replace(/_/g,'/')+'='.repeat((4-value.length%4)%4)),c=>c.charCodeAt(0));}
const ready=supported?navigator.serviceWorker.register('/sw.js').then(()=>navigator.serviceWorker.ready):null;
if(!supported){enable.disabled=true;show(ios&&!installed?'On iPhone or iPad: Share → Add to Home Screen, then open Da Vinci there to enable reminders.':'This browser does not support push notifications. Try a current browser or the installed web app.');}
else if(ios&&!installed){enable.disabled=true;show('Share → Add to Home Screen, then open Da Vinci there to enable reminders.');}
else ready.then(async registration=>{
 subscription=await registration.pushManager.getSubscription();
 if(subscription){await api('/api/push/subscribe',subscription);show('Reminders are on for this device.');}
 else if(Notification.permission==='denied')show('Notifications are blocked. Allow Da Vinci in your browser or device notification settings.');
 buttons();
}).catch(()=>show('Could not check reminders. Reopen the app and try again.',true));
enable.onclick=async()=>{
 enable.disabled=true;
 try{
  const permission=await Notification.requestPermission();
  if(permission!=='granted')throw new Error('Notifications were not allowed. Enable Da Vinci notifications in your browser or device settings to receive reminders.');
  const registration=await ready,{publicKey}=await api('/api/push/key');
  subscription=await registration.pushManager.getSubscription()||await registration.pushManager.subscribe({userVisibleOnly:true,applicationServerKey:bytes(publicKey)});
  await api('/api/push/subscribe',subscription);buttons();show('Reminders are on for this device. Use Send test to check delivery.');
 }catch(e){show(e.message,true);}finally{enable.disabled=false;}
};
disable.onclick=async()=>{
 disable.disabled=true;
 try{if(subscription){await api('/api/push/unsubscribe',subscription);await subscription.unsubscribe();}subscription=null;buttons();show('Writing reminders are off on this device.');}
 catch(e){show(e.message,true);}finally{disable.disabled=false;}
};
test.onclick=async()=>{test.disabled=true;try{await api('/api/push/test',subscription);show('Test sent. Check your device notifications.');}catch(e){show(e.message,true);}finally{test.disabled=false;}};
