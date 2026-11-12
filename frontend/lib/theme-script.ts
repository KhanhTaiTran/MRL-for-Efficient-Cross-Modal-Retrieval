// Runs before paint so saved appearance also applies to native form controls.
export const themeScript = `(function(){try{var t=localStorage.getItem('aurafind-theme')||'system';var d=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);document.documentElement.style.colorScheme=d?'dark':'light'}catch(e){}})()`;
