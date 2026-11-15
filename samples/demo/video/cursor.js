module.exports.CURSOR = `
(() => {
  const add = () => {
    if (document.getElementById('__cur')) return;
    const st = document.createElement('style');
    st.textContent = \`
      #__cur{position:fixed;left:0;top:0;width:26px;height:26px;z-index:2147483647;pointer-events:none;
             transform:translate(-3px,-2px);transition:none;filter:drop-shadow(0 1px 2px rgba(0,0,0,.6))}
      .__rip{position:fixed;width:34px;height:34px;margin:-17px 0 0 -17px;border-radius:50%;z-index:2147483646;
             pointer-events:none;border:3px solid rgba(255,214,10,.95);animation:__r .55s ease-out forwards}
      @keyframes __r{from{transform:scale(.3);opacity:1}to{transform:scale(1.6);opacity:0}}\`;
    document.head.appendChild(st);
    const c = document.createElement('div');
    c.id = '__cur';
    c.innerHTML = '<svg width="26" height="26" viewBox="0 0 26 26"><path d="M3 2 L3 21 L8 16 L11.5 24 L15 22.5 L11.5 14.8 L18.5 14.8 Z" fill="white" stroke="black" stroke-width="1.6" stroke-linejoin="round"/></svg>';
    document.body.appendChild(c);
    const pos = window.__curpos || {x: 960, y: 540};
    c.style.left = pos.x + 'px'; c.style.top = pos.y + 'px';
    document.addEventListener('mousemove', (e) => {
      c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px';
      window.__curpos = {x: e.clientX, y: e.clientY};
    }, true);
    document.addEventListener('mousedown', (e) => {
      const r = document.createElement('div');
      r.className = '__rip'; r.style.left = e.clientX + 'px'; r.style.top = e.clientY + 'px';
      document.body.appendChild(r); setTimeout(() => r.remove(), 600);
    }, true);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', add); else add();
})();`;
