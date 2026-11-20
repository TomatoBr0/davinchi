// Replace Augur's old service worker and clear its cached UI. No personal data is cached.
self.addEventListener('install',()=>self.skipWaiting());
self.addEventListener('activate',event=>event.waitUntil((async()=>{for(const key of await caches.keys())await caches.delete(key);await self.clients.claim();})()));
self.addEventListener('push',event=>{
 let message={};try{message=event.data?.json()||{};}catch{}
 event.waitUntil(self.registration.showNotification(message.title||'Da Vinci',{body:message.body||'Got five minutes? Do a quick writing session.',icon:'/icon.svg',tag:message.tag||'davinci-writing',data:{url:'/'}}));
});
self.addEventListener('notificationclick',event=>{
 event.notification.close();
 event.waitUntil((async()=>{const windows=await self.clients.matchAll({type:'window',includeUncontrolled:true});for(const client of windows){if(new URL(client.url).origin===self.location.origin){await client.focus();return;}}await self.clients.openWindow('/');})());
});
