import { useEffect, useState } from 'react';
import { API } from './useProctoring';
import './ai.css';

const words = value => String(value || 'waiting').replaceAll('_', ' ');

export function StatusPanel({ ai, compact = false }) {
  const s = ai.state;
  return <section className="ai-panel" aria-label="AI camera observations">
    <h3>{compact ? 'Camera check status' : 'Prepare your camera'}</h3>
    {ai.error && <p role="alert" className="ai-error">{ai.error}</p>}
    {!s ? <p>Waiting for camera checks.</p> : <>
      {!s.frame_fresh && <p className="ai-error">Waiting for fresh camera evidence.</p>}
      <dl className="ai-status">
        <dt>Reference comparison</dt><dd>{s.frame_fresh ? words(s.identity.identity_status) : 'unknown'}</dd>
        <dt>Identity and liveness</dt><dd>{words(s.verification.status)} ({words(s.verification.stage)})</dd>
        <dt>Head / eye direction</dt><dd>{s.frame_fresh ? words(s.gaze.status) : 'unknown'}</dd>
        <dt>Objects</dt><dd>{words(s.objects.status)}</dd>
      </dl>
      {!compact && <p>Face the camera alone and look at the screen center. Hold still for calibration. If eye calibration stays uncertain, try the head-only option below.</p>}
      {s.gaze.status === 'calibrating' && <p>Calibration: {s.gaze.calibration_samples} usable samples. {words(s.gaze.reason)}.</p>}
      {s.verification.status !== 'verified' && <p>Face the camera for verification. Attempt {s.verification.attempt}/3: {words(s.verification.reason)}.</p>}
      {s.frame_fresh && s.objects.counts && <p>Last object result: people {s.objects.counts.person}, phones {s.objects.counts['cell phone']}, books {s.objects.counts.book}.</p>}
      <p className="ai-note">AI results are observations for review. Uncertainty does not add to the existing browser-warning counter.</p>
      {compact && <details><summary>Recent AI observations</summary><ul>{s.events.slice(-8).reverse().map(e =>
        <li key={e.id}>{words(e.event)}</li>)}</ul></details>}
    </>}
  </section>;
}

export function Preparation({ ai, onBegin, onCancel, headOnly, setHeadOnly }) {
  return <main className="ai-preparation">
    <h2>Before your exam</h2>
    <video ref={node => ai.attachVideo(node)} autoPlay muted playsInline aria-label="Camera preview" />
    <StatusPanel ai={ai} />
    <label><input type="checkbox" checked={headOnly} onChange={e => setHeadOnly(e.target.checked)} /> Head pose only when eye calibration is unavailable</label>
    <div className="ai-actions">
      <button onClick={() => ai.command('retry', { head_only: headOnly })}>Retry checks / recalibrate</button>
      <button disabled={!ai.state?.ready} onClick={onBegin}>Begin exam</button>
      <button onClick={onCancel}>Cancel camera checks</button>
    </div>
    <p>If verification remains uncertain, ask your teacher for supervised verification.</p>
  </main>;
}

export function TeacherAIEvents() {
  const [rows, setRows] = useState([]);
  const [message, setMessage] = useState('Loading AI review observations…');
  useEffect(() => {
    let disposed = false;
    const load = async () => {
      try {
        const response = await fetch(`${API}/api/ai/review`, { credentials: 'include' });
        if (!response.ok) throw new Error('Sign in to Django admin to view private AI observations.');
        const data = await response.json();
        if (!disposed) { setRows(data); setMessage(data.length ? '' : 'No AI observations recorded yet.'); }
      } catch (e) { if (!disposed) setMessage(e.message); }
    };
    void load(); const timer = setInterval(load, 5000);
    return () => { disposed = true; clearInterval(timer); };
  }, []);
  return <section className="ai-panel">
    <h3>AI observations for review</h3>
    <p>These are separate from the existing violation logs. <a href="/admin/" target="_blank" rel="noreferrer">Staff sign-in</a></p>
    {message && <p>{message}</p>}
    {!!rows.length && <div className="ai-scroll"><table><thead><tr><th>Student</th><th>Phase</th><th>Observation</th><th>Time</th></tr></thead>
      <tbody>{rows.map(row => <tr key={row.id}><td>{row.student_id}</td><td>{words(row.phase)}</td><td>{words(row.event)}</td><td>{new Date(row.time).toLocaleString()}</td></tr>)}</tbody>
    </table></div>}
  </section>;
}
