import { test, expect } from '@playwright/test';

async function fixture(page, { ready = true } = {}) {
  const calls = [];
  let stage = 'precheck';
  let frames = 0;
  const status = () => ({ session_id: 'test-session', token: 'test-only-session-token', stage,
    ready: ready && frames > 0, frame_fresh: frames > 0,
    identity: { identity_status: 'reference_match' },
    verification: { status: ready ? 'verified' : 'checking', stage: 'pre_exam', attempt: 1, reason: 'face_camera' },
    gaze: { status: 'ready', head_only: false, calibration_samples: 15 },
    objects: { status: 'disabled_by_consent', counts: null },
    events: stage === 'exam' ? [{ id: 1, event: 'identity_mismatch_review' }] : [],
  });
  await page.route('**/api/**', async route => {
    const path = new URL(route.request().url()).pathname;
    calls.push({ path, body: route.request().postData(), headers: route.request().headers() });
    let response;
    if (path.endsWith('/capabilities')) response = { enabled: true, cloud_configured: true, liveness_acknowledged: true };
    else if (path === '/api/ai/sessions') response = status();
    else if (path.endsWith('/frames')) { frames++; response = status(); }
    else if (path.endsWith('/begin')) { stage = 'exam'; response = status(); }
    else if (path.endsWith('/stop')) response = { stage: 'ended' };
    else if (path.endsWith('/retry')) response = status();
    else if (path.endsWith('/questions')) response = [{ id: 1, question_text: 'First existing question' }, { id: 2, question_text: 'Second existing question' }];
    else if (path.endsWith('/events')) response = [];
    else if (path.endsWith('/review')) { await route.fulfill({ status: 403, json: { error: 'Sign in' } }); return; }
    else response = { message: 'Saved' };
    await route.fulfill({ status: path === '/api/ai/sessions' ? 201 : 200, json: response });
  });
  await page.goto('/');
  return calls;
}

async function prepare(page) {
  await page.getByPlaceholder('e.g. BCS-21F-045').fill('TEST-1');
  await page.getByLabel('Exam access code').fill('private-test-code');
  await page.getByLabel('I agree to webcam processing', { exact: false }).check();
  await page.getByRole('button', { name: 'Check camera before exam' }).click();
  await expect(page.getByRole('heading', { name: 'Before your exam' })).toBeVisible();
}

test('precheck gates timer; exam answers, snapshots and submission remain available', async ({ page }) => {
  const calls = await fixture(page);
  await prepare(page);
  await expect(page.getByText('Time Left:', { exact: false })).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Begin exam', exact: true })).toBeEnabled();
  expect(JSON.parse(calls.find(c => c.path === '/api/ai/sessions').body).cloud_consent).toBe(false);
  await page.getByRole('button', { name: 'Begin exam', exact: true }).click();
  await expect(page.getByText('First existing question')).toBeVisible();
  await page.getByPlaceholder('Type your answer here...').fill('My existing answer');
  await page.getByRole('button', { name: 'Next Question' }).click();
  await expect(page.getByText('Second existing question')).toBeVisible();
  await page.getByRole('button', { name: 'Previous', exact: true }).click();
  await expect(page.getByPlaceholder('Type your answer here...')).toHaveValue('My existing answer');
  await expect.poll(() => calls.some(c => c.path.endsWith('/save-snapshot'))).toBe(true);
  await expect(page.getByText('Live Warning Logs (0/3)')).toBeVisible();
  await page.screenshot({ path: 'test-results/integrated-exam.png', fullPage: true });
  await page.getByRole('button', { name: 'Next Question' }).click();
  await page.getByRole('button', { name: 'Submit Exam', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Exam Submitted Successfully!' })).toBeVisible();
  await expect.poll(() => calls.some(c => c.path.endsWith('/stop'))).toBe(true);
});

test('uncertain precheck cannot begin and cancellation stops capture', async ({ page }) => {
  const calls = await fixture(page, { ready: false });
  await prepare(page);
  await expect(page.getByRole('button', { name: 'Begin exam', exact: true })).toBeDisabled();
  await page.getByRole('button', { name: 'Cancel camera checks' }).click();
  await expect(page.getByRole('button', { name: 'Check camera before exam' })).toBeVisible();
  await expect.poll(() => calls.some(c => c.path.endsWith('/stop'))).toBe(true);
});

test('existing copy-warning behavior remains separate from AI observations', async ({ page }) => {
  const calls = await fixture(page);
  await prepare(page);
  await expect(page.getByRole('button', { name: 'Begin exam', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: 'Begin exam', exact: true }).click();
  await expect(page.getByText('First existing question')).toBeVisible();
  await page.evaluate(() => document.dispatchEvent(new Event('copy', { cancelable: true })));
  await expect(page.getByText('Live Warning Logs (1/3)')).toBeVisible();
  await expect.poll(() => calls.some(c => c.path.endsWith('/log-event') && JSON.parse(c.body).event_type === 'Copy-Attempt')).toBe(true);
});

test('teacher view preserves old logs while private AI review requires staff login', async ({ page }) => {
  await fixture(page);
  await page.getByRole('button', { name: 'Open Teacher / Admin Dashboard', exact: false }).click();
  await expect(page.getByText('Violation Logs (0)')).toBeVisible();
  await expect(page.getByText('Sign in to Django admin to view private AI observations.')).toBeVisible();
});
