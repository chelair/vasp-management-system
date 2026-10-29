import { useEffect, useState } from 'react';

let loading: Promise<void> | undefined;

function load3Dmol(): Promise<void> {
  if (window.$3Dmol) return Promise.resolve();
  if (!loading) {
    loading = new Promise<void>((resolve, reject) => {
      const script = document.createElement('script');
      script.src = '/3dmol/3Dmol-min.js';
      script.async = true;
      script.onload = () => {
        if (window.$3Dmol) resolve();
        else { script.remove(); loading = undefined; reject(new Error('3D 视图加载失败，请重新打开')); }
      };
      script.onerror = () => {
        script.remove(); loading = undefined;
        reject(new Error('3D 视图加载失败，请重新打开'));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}

export default function use3Dmol(enabled: boolean) {
  const [ready, setReady] = useState(() => Boolean(window.$3Dmol));
  const [error, setError] = useState('');
  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    void load3Dmol().then(() => { if (!cancelled) setReady(true); })
      .catch(e => { if (!cancelled) setError(e.message); });
    return () => { cancelled = true; };
  }, [enabled]);
  return { ready, error };
}
