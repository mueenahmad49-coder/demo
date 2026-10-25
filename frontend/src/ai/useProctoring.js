import { useCallback, useEffect, useRef, useState } from 'react';

export const API = import.meta.env.VITE_API_BASE || '';

async function responseJson(response) {
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || 'Camera checks are temporarily unavailable.');
  return data;
}

export function useProctoring(videoRef) {
  const [capabilities, setCapabilities] = useState(null);
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const streamRef = useRef(null);
  const sessionRef = useRef(null);
  const timerRef = useRef(null);
  const stoppedRef = useRef(false);
  const pausedRef = useRef(false);
  const inFlightRef = useRef(null);
  const sequenceRef = useRef(0);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${API}/api/ai/capabilities`, { signal: controller.signal })
      .then(responseJson).then(setCapabilities)
      .catch(e => { if (e.name !== 'AbortError') setError('Cannot reach the backend. Start Django and try again.'); });
    return () => controller.abort();
  }, []);

  const attachVideo = useCallback(node => {
    videoRef.current = node;
    if (node && streamRef.current && node.srcObject !== streamRef.current) node.srcObject = streamRef.current;
  }, [videoRef]);

  const stop = useCallback(async () => {
    stoppedRef.current = true;
    clearTimeout(timerRef.current);
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
    const session = sessionRef.current;
    sessionRef.current = null;
    if (session) {
      try {
        await inFlightRef.current;
        await fetch(`${API}/api/ai/sessions/${session.id}/stop`, {
          method: 'POST', headers: { Authorization: `Bearer ${session.token}` }, keepalive: true,
        });
      } catch { /* Server also expires disconnected sessions after two minutes. */ }
    }
  }, []);

  useEffect(() => {
    const onPageHide = () => { void stop(); };
    window.addEventListener('pagehide', onPageHide);
    return () => { window.removeEventListener('pagehide', onPageHide); void stop(); };
  }, [stop]);

  const start = async ({ studentId, accessCode, consent, cloudConsent, headOnly }) => {
    setError(''); setState(null); setBusy(true); stoppedRef.current = false;
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720 }, audio: false });
      if (stoppedRef.current) { stream.getTracks().forEach(track => track.stop()); return; }
      streamRef.current = stream;
      if (videoRef.current) videoRef.current.srcObject = stream;
      if (capabilities?.enabled === false) return true;
      const data = await responseJson(await fetch(`${API}/api/ai/sessions`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ student_id: studentId, access_code: accessCode,
          consent, cloud_consent: cloudConsent, head_only: headOnly }),
      }));
      sessionRef.current = { id: data.session_id, token: data.token };
      if (stoppedRef.current) { await stop(); return; }
      sequenceRef.current = 0;
      setState(data);
      const pump = async () => {
        if (stoppedRef.current || !sessionRef.current) return;
        if (pausedRef.current) { timerRef.current = setTimeout(pump, 100); return; }
        const video = videoRef.current;
        if (video?.readyState >= 2 && video.videoWidth) {
          const canvas = document.createElement('canvas');
          canvas.width = Math.min(960, video.videoWidth);
          canvas.height = Math.round(video.videoHeight * canvas.width / video.videoWidth);
          canvas.getContext('2d').drawImage(video, 0, 0, canvas.width, canvas.height);
          const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/jpeg', .85));
          if (!blob || stoppedRef.current || !sessionRef.current) return;
          const form = new FormData();
          form.append('frame', blob, 'frame.jpg');
          form.append('sequence', String(sequenceRef.current++));
          const session = sessionRef.current;
          inFlightRef.current = (async () => {
            try {
              const response = await fetch(`${API}/api/ai/sessions/${session.id}/frames`, {
                method: 'POST', headers: { Authorization: `Bearer ${session.token}` }, body: form,
                signal: AbortSignal.timeout(20000),
              });
              if ([403, 410].includes(response.status)) {
                setError('Camera-check session ended. Return to the start page and check again.');
                stoppedRef.current = true;
                streamRef.current?.getTracks().forEach(track => track.stop());
                setState(old => old && ({ ...old, ready: false, frame_fresh: false }));
                return;
              }
              const result = await responseJson(response);
              if (!stoppedRef.current) { setState(result); setError(''); }
            } catch {
              if (!stoppedRef.current) {
                setError('Camera checks are temporarily unavailable. Retrying; this is not a misconduct finding.');
                setState(old => old && ({ ...old, ready: false, frame_fresh: false }));
              }
            }
          })();
          await inFlightRef.current;
        }
        if (!stoppedRef.current) timerRef.current = setTimeout(pump, 400);
      };
      timerRef.current = setTimeout(pump, 100);
      return true;
    } catch (e) {
      setError(e.name === 'NotAllowedError' ? 'Allow webcam access to run the camera checks.' : e.message);
      await stop();
      return false;
    } finally { setBusy(false); }
  };

  const command = async (action, body = {}) => {
    const session = sessionRef.current;
    if (!session) return false;
    pausedRef.current = true;
    try {
      await inFlightRef.current;
      const data = await responseJson(await fetch(`${API}/api/ai/sessions/${session.id}/${action}`, {
        method: 'POST', headers: { Authorization: `Bearer ${session.token}`, 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      }));
      setState(data); setError('');
      return true;
    } catch (e) { setError(e.message); return false; }
    finally { pausedRef.current = false; }
  };

  return { capabilities, state, error, busy, start, stop, command, attachVideo };
}
