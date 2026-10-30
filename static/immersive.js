// Lightweight CSS 3D; no WebGL dependency or continuous rendering loop.
(()=>{
 const root=document.getElementById('app'),motion=matchMedia('(prefers-reduced-motion: reduce)'),pointer=matchMedia('(hover: hover) and (pointer: fine)');
 let frame=0,target=null,point=null;
 const selector='.ed-destination,.ed-promo,.boarding-card';
 function reset(){if(target){target.style.removeProperty('--tilt-x');target.style.removeProperty('--tilt-y');target.style.removeProperty('--spot-x');target.style.removeProperty('--spot-y');target.classList.remove('depth-active')}target=null;point=null;if(frame)cancelAnimationFrame(frame);frame=0}
 function draw(){frame=0;if(!target?.isConnected||!point||motion.matches||!pointer.matches){reset();return}const rect=target.getBoundingClientRect(),x=Math.max(0,Math.min(1,(point.x-rect.left)/rect.width)),y=Math.max(0,Math.min(1,(point.y-rect.top)/rect.height));target.style.setProperty('--tilt-x',`${(0.5-y)*5}deg`);target.style.setProperty('--tilt-y',`${(x-0.5)*6}deg`);target.style.setProperty('--spot-x',`${x*100}%`);target.style.setProperty('--spot-y',`${y*100}%`)}
 root.addEventListener('pointermove',e=>{if(motion.matches||!pointer.matches)return;const card=e.target.closest(selector);if(!card){reset();return}if(card!==target){reset();target=card;target.classList.add('depth-active')}point={x:e.clientX,y:e.clientY};if(!frame)frame=requestAnimationFrame(draw)},{passive:true});
 root.addEventListener('pointerleave',reset);root.addEventListener('focusin',reset);document.addEventListener('visibilitychange',()=>{if(document.hidden)reset()});motion.addEventListener('change',reset);pointer.addEventListener('change',reset);
 const revealObserver='IntersectionObserver' in window?new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){entry.target.classList.add('depth-arrived');revealObserver.unobserve(entry.target)}},{threshold:.08}):null;
 function decorate(){reset();for(const node of root.querySelectorAll('.section'))if(!node.classList.contains('depth-reveal')){node.classList.add('depth-reveal');if(revealObserver&&!motion.matches)revealObserver.observe(node);else node.classList.add('depth-arrived')}}
 new MutationObserver(records=>{if(records.some(r=>r.target===root)){revealObserver?.disconnect();decorate()}}).observe(root,{childList:true});decorate();
})();
