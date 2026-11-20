// Capture in a viewport-shaped coordinate space. Never stretch recorded ink.
export function captureGeometry(viewWidth,viewHeight){
 const width=1000,height=Math.max(100,Math.min(10000,Math.round(width*viewHeight/Math.max(1,viewWidth))));
 const spacing=56*width/Math.max(1,viewWidth);
 const baseline=Math.min(height-spacing*.5,Math.max(spacing,Math.round(height/2/spacing)*spacing));
 return {width,height,guides:{ascender:baseline-spacing*.85,xheight:baseline-spacing*.5,baseline,descender:baseline+spacing*.25,line_spacing:spacing,line_spacing_px:56,style:'notebook'}};
}
export function capturePoint(clientX,clientY,rect,width,height){
 const scale=Math.min(rect.width/width,rect.height/height);
 const left=rect.left+(rect.width-width*scale)/2,top=rect.top+(rect.height-height*scale)/2;
 return {x:Math.max(0,Math.min(width,(clientX-left)/scale)),y:Math.max(0,Math.min(height,(clientY-top)/scale))};
}
export function randomWordPlacement(width,height,wordWidth,spacing,random=Math.random){
 const unit=spacing/56,margin=Math.min(width*.12,52*unit);
 const maxX=Math.max(margin,width-margin-wordWidth);
 const first=Math.ceil(Math.max(spacing*.95,height*.18)/spacing);
 const last=Math.floor(Math.min(height-spacing*.4,height*.82)/spacing);
 const line=first+Math.floor(Math.min(.999999,Math.max(0,random()))*Math.max(1,last-first+1));
 const baseline=last>=first?line*spacing:Math.max(spacing*.85,Math.min(height-spacing*.25,height*.6));
 return {x:margin+Math.min(1,Math.max(0,random()))*(maxX-margin),baseline};
}
