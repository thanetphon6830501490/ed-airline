(()=>{
 const textFields=new Set(['ethnicity','religion','editEthnicity','editReligion']),documentFields=new Set(['document','editDocument']);
 function configure(){for(const id of [...textFields,...documentFields]){const input=document.getElementById(id);if(!input)continue;if(textFields.has(id)){input.setAttribute('pattern','[\\p{L}\\p{M}\\s]*');input.title='กรอกเฉพาะตัวอักษรและช่องว่าง ไม่รับตัวเลข';}else{input.maxLength=13;input.title='กรอกได้สูงสุด 13 ตัว';}}}
 document.addEventListener('input',event=>{const input=event.target;if(event.isComposing)return;if(textFields.has(input.id)){const cleaned=input.value.replace(/[^\p{L}\p{M}\s]/gu,'');if(cleaned!==input.value){const pos=input.selectionStart;input.value=cleaned;input.setSelectionRange(Math.min(pos,cleaned.length),Math.min(pos,cleaned.length));}}else if(documentFields.has(input.id)&&input.value.length>13)input.value=input.value.slice(0,13)});
 document.addEventListener('compositionend',event=>{if(textFields.has(event.target.id))event.target.dispatchEvent(new Event('input',{bubbles:true}))});
 new MutationObserver(records=>{if(records.some(r=>r.type==='childList'))configure()}).observe(document.getElementById('app'),{childList:true,subtree:true});configure();
})();
