import fs from 'node:fs/promises';
import {Presentation,PresentationFile} from '@oai/artifact-tool';
const pages=JSON.parse(await fs.readFile(new URL('./deck.json',import.meta.url),'utf8'));
const p=Presentation.create({slideSize:{width:1280,height:720}});
for(const [index,page]of pages.entries()){
 const s=p.slides.add();s.background.fill='#F7F5F0';const nodes=[];
 for(const q of page.shapes){const isNode=q.geometry==='roundRect';const shape=s.shapes.add({geometry:isNode?'roundRect':'textbox',position:q.position,fill:isNode?'#E8E4DA':'none',line:{fill:isNode?'#C8C1B4':'none',width:isNode?1:0}});if(isNode)nodes.push(shape);if(q.text){shape.text=q.text;let size=q.position.top<100?22:q.position.top<260?38:24;if(index===0)size=q.text==='OrgForms'?76:q.position.top===244?32:q.position.height<=35?17:24;shape.text.style={fontSize:size,color:'#292A27',bold:q.text==='OrgForms'||isNode};}}
 if([0,2,3,4,7].includes(index)){for(let i=0;i<nodes.length-1;i++){const a=nodes[i],b=nodes[i+1];s.shapes.connect(a,b,{kind:'elbow',fromSide:b.position.top>a.position.top?'bottom':'right',toSide:b.position.top>a.position.top?'top':'left',line:{fill:'#817967',width:2},tail:{type:'arrow',width:'med',length:'med'}});}}
}
await (await PresentationFile.exportPptx(p)).save('/Volumes/Workflow/python agent /output/OrgForms-updated-pitch.pptx');
await fs.writeFile('/Volumes/Workflow/python agent /output/OrgForms-cover.png',new Uint8Array(await (await p.slides.items[0].export({format:'png',scale:1})).arrayBuffer()));
