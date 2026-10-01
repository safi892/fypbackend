const $ = (id) => document.getElementById(id);
const examples = {
  starter: `#include <iostream>

int main() {
    std::cout << "Hello, world!" << std::endl;
    return 0;
}`,
  search: `int binarySearch(int arr[], int n, int target) {
    int left = 0, right = n - 1;
    while (left <= right) {
        int mid = left + (right - left) / 2;
        if (arr[mid] == target) return mid;
        if (arr[mid] < target) left = mid + 1;
        else right = mid - 1;
    }
    return -1;
}`,
  sum: `int sumArray(const int numbers[], int size) {
    int total = 0;
    for (int i = 0; i < size; ++i) {
        total += numbers[i];
    }
    return total;
}`,
  factorial: `int factorial(int n) {
    if (n <= 1) return 1;
    return n * factorial(n - 1);
}`,
};
let busy = false;
let result = null;
let submittedCode = '';
let submittedLanguage = '';
let validatedCode = null;
let validationVersion = 0;
let validationTimer;
let errorLine = null;
let currentFix = null;

function canAnalyze() {
  return !busy && validatedCode !== null && validatedCode === $('code').value;
}

function showValidation(state, title, message, line = null) {
  $('validation-feedback').dataset.state = state;
  $('validation-title').textContent = title;
  $('validation-message').textContent = message;
  $('code').setAttribute('aria-invalid', String(state === 'invalid'));
  $('validation-retry').hidden = state !== 'unavailable';
  $('go-to-error').hidden = line === null;
  $('preview-fix').hidden = !currentFix;
  errorLine = line;
  $('analyze-button').disabled = !canAnalyze();
  if ($('optimize-button')) $('optimize-button').disabled = !canAnalyze();
}

function isFixPayload(fix) {
  return Boolean(fix) && typeof fix.code === 'string' && Array.isArray(fix.edits);
}

function hideFixPreview() {
  $('fix-preview').hidden = true;
  $('fix-preview-diff').textContent = '';
}

function showFixPreview() {
  if (!isFixPayload(currentFix)) return;
  $('fix-preview-desc').textContent = typeof currentFix.description === 'string' ? currentFix.description : '';
  const diff = $('fix-preview-diff');
  diff.textContent = '';
  // Untrusted server text goes in as text nodes, never HTML.
  for (const edit of currentFix.edits) {
    const row = document.createElement('div');
    row.className = 'fix-edit';
    const number = document.createElement('span');
    number.className = 'fix-edit-line';
    number.textContent = String(edit.line);
    row.appendChild(number);
    const lines = document.createElement('div');
    lines.className = 'fix-edit-lines';
    if (typeof edit.before === 'string' && edit.before) {
      const before = document.createElement('div');
      before.className = 'fix-line before';
      before.textContent = `- ${edit.before}`;
      lines.appendChild(before);
    }
    if (typeof edit.after === 'string' && edit.after) {
      const after = document.createElement('div');
      after.className = 'fix-line after';
      after.textContent = `+ ${edit.after}`;
      lines.appendChild(after);
    }
    row.appendChild(lines);
    diff.appendChild(row);
  }
  $('preview-fix').hidden = true;
  $('fix-preview').hidden = false;
}

function applyFix() {
  if (!isFixPayload(currentFix)) return;
  const textarea = $('code');
  textarea.focus();
  textarea.select();
  // insertText keeps the replacement on the undo stack; the direct
  // assignment below is only the fallback when execCommand is unavailable.
  let applied = false;
  try { applied = document.execCommand('insertText', false, currentFix.code); } catch { applied = false; }
  if (!applied || textarea.value !== currentFix.code) textarea.value = currentFix.code;
  hideFixPreview();
  updateEditor();
  $('announcement').textContent = 'Suggested fix applied. Checking the code again.';
}

async function validateEditor(version) {
  const code = $('code').value;
  if (version !== validationVersion || !code.trim()) return;
  try {
    const data = await request('/validate-code', { code }, 15000);
    // A late response must never unlock a newer, unchecked edit.
    if (version !== validationVersion) return;
    if (typeof data.valid !== 'boolean' || typeof data.message !== 'string') throw new Error('Invalid validation response');
    validatedCode = data.valid ? code : null;
    currentFix = data.valid ? null : (isFixPayload(data.suggested_fix) ? data.suggested_fix : null);
    showValidation(data.valid ? 'valid' : 'invalid', data.valid ? 'Ready to analyze' : 'Check your C++ code', data.message, data.line ?? null);
  } catch {
    if (version !== validationVersion) return;
    validatedCode = null;
    showValidation('unavailable', 'Couldn’t check your code', 'Check your connection and try again. Analyze stays locked until C++ validation is available.');
  }
}

function scheduleValidation() {
  clearTimeout(validationTimer);
  const version = ++validationVersion;
  validatedCode = null;
  // Any edit or re-check invalidates a fix proposed for the previous text.
  currentFix = null;
  hideFixPreview();
  if (!$('code').value.trim()) {
    showValidation('empty', 'Start with C++', 'Write C++ code or load an example. Analyze unlocks when the syntax check passes.');
    return;
  }
  if ($('code').value.length > 100000) {
    showValidation('invalid', 'Snippet is too long', 'Use a snippet of 100,000 characters or fewer.');
    return;
  }
  showValidation('checking', 'Checking C++ syntax…', 'Keep writing. Your code is checked after you pause.');
  validationTimer = setTimeout(() => validateEditor(version), 450);
}

$('validation-retry').addEventListener('click', scheduleValidation);
$('preview-fix').addEventListener('click', showFixPreview);
$('cancel-fix').addEventListener('click', () => { hideFixPreview(); if (currentFix) $('preview-fix').focus(); });
$('apply-fix').addEventListener('click', applyFix);
$('go-to-error').addEventListener('click', () => {
  const lines = $('code').value.split('\n');
  const lineIndex = Math.min(lines.length - 1, Math.max(0, errorLine - 1));
  const start = lines.slice(0, lineIndex).reduce((sum, line) => sum + line.length + 1, 0);
  $('code').focus();
  $('code').setSelectionRange(start, start + lines[lineIndex].length);
  $('code').scrollTop = Math.max(0, (lineIndex - 2) * parseFloat(getComputedStyle($('code')).lineHeight));
  $('line-numbers').scrollTop = $('code').scrollTop;
});

async function request(path, body, timeout = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(path, {
      method: body === undefined ? 'GET' : 'POST',
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      signal: controller.signal,
    });
    let data;
    try { data = await response.json(); } catch { throw new Error('The server returned an unreadable response. Please try again.'); }
    if (!response.ok) {
      let message = typeof data.detail === 'string' ? data.detail : 'The request could not be completed. Please try again.';
      if (Array.isArray(data.detail)) message = data.detail.map((item) => item.msg).join(' ');
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return data;
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('The request took too long. Try a smaller snippet. The server may still be processing your previous request.');
    if (error instanceof TypeError) throw new Error('Could not reach the server. Check your connection and that the backend is running.');
    throw error;
  } finally { clearTimeout(timer); }
}

function updateEditor() {
  const code = $('code').value;
  const lines = code ? code.split('\n').length : 0;
  $('line-numbers').textContent = Array.from({ length: Math.max(1, lines) }, (_, i) => i + 1).join('\n');
  $('line-numbers').scrollTop = $('code').scrollTop;
  $('code-count').textContent = `${lines} ${lines === 1 ? 'line' : 'lines'} · ${code.length.toLocaleString()} characters`;
  $('code').setCustomValidity('');
  updateStale();
  scheduleValidation();
}
function updateStale() {
  $('stale-notice').hidden = !result || (submittedCode === $('code').value && submittedLanguage === $('output-language').value);
}
$('code').addEventListener('input', updateEditor);
$('code').addEventListener('scroll', () => { $('line-numbers').scrollTop = $('code').scrollTop; });
$('output-language').addEventListener('change', updateStale);
$('example').addEventListener('change', () => {
  if (!examples[$('example').value]) return;
  $('code').value = examples[$('example').value];
  updateEditor();
  $('code').focus();
  $('example').value = '';
});
$('clear').addEventListener('click', () => {
  $('code').value = '';
  updateEditor();
  $('code').focus();
  if ($('optimization-section')) $('optimization-section').hidden = true;
});
document.addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && !busy) {
    event.preventDefault();
    if (canAnalyze()) $('analyze-form').requestSubmit();
    else { $('code').focus(); $('announcement').textContent = $('validation-message').textContent; }
  }
});

$('analyze-form').addEventListener('submit', (event) => {
  event.preventDefault();
  if (!$('code').value.trim()) {
    $('code').setCustomValidity('Enter some C++ code before analyzing.');
    $('code').reportValidity();
    return;
  }
  if (!canAnalyze()) return;
  runAnalysis();
});

async function runAnalysis() {
  if (!canAnalyze()) return;
  busy = true;
  result = null;
  submittedCode = $('code').value;
  submittedLanguage = $('output-language').value;
  $('analyze-button').disabled = true;
  $('analyze-button').textContent = 'Analyzing…';
  $('empty-state').hidden = $('error-state').hidden = $('result-content').hidden = $('result-badge').hidden = true;
  $('loading-state').hidden = false;
  document.querySelector('.results-panel').setAttribute('aria-busy', 'true');
  $('result-meta').textContent = 'Working on your snippet';
  $('announcement').textContent = 'Analysis started.';
  const started = performance.now();
  $('loading-message').textContent = 'The model is preparing your explanation and comments.';
  const timer = setInterval(() => {
    $('loading-message').textContent = `Still working · ${Math.floor((performance.now() - started) / 1000)} seconds elapsed.`;
  }, 1000);
  try {
    const data = await request('/analyze', { code: submittedCode, language: 'cpp', output_language: submittedLanguage, source: 'web' }, 600000);
    if (typeof data.explanation !== 'string' || typeof data.commented_code !== 'string' || typeof data.needs_review !== 'boolean') throw new Error('The server returned an incomplete analysis. Please try again.');
    result = data;
    // Model output and source code are untrusted text, never HTML.
    $('explanation').textContent = data.explanation || 'No explanation was returned for this snippet.';
    $('commented-code').textContent = data.commented_code || 'No commented code was returned.';

    const optChecked = $('include-optimization') && $('include-optimization').checked;
    if (optChecked) {
      try {
        $('loading-message').textContent = 'Generating iterative loop optimization…';
        const optData = await request('/optimize', { code: submittedCode, source: 'web', mode: 'loop' }, 600000);
        result.optimization = optData;
        if (optData.code && optData.changed) {
          $('optimized-code').textContent = optData.code;
          $('optimization-note').textContent = optData.note || (optData.verified ? 'Verified: identical output on test inputs.' : 'Loop rewrite generated by model.');
          $('optimization-badge').hidden = false;
          if (optData.verified) {
            $('optimization-badge').textContent = optData.speedup > 1.0 ? `Verified ${optData.speedup}x faster` : 'Verified equivalent';
            $('optimization-badge').className = 'result-badge';
          } else {
            $('optimization-badge').textContent = 'Candidate (unverified)';
            $('optimization-badge').className = 'result-badge review';
          }
          $('optimization-section').hidden = false;
        } else {
          $('optimization-section').hidden = true;
        }
      } catch (optErr) {
        console.warn('Optimization error:', optErr);
        $('optimization-section').hidden = true;
      }
    } else {
      $('optimization-section').hidden = true;
    }

    $('raw-response').textContent = JSON.stringify(result, null, 2);
    $('review-notice').hidden = !data.needs_review;
    $('result-badge').textContent = data.needs_review ? 'Review needed' : 'Complete';
    $('result-badge').classList.toggle('review', data.needs_review);
    $('result-badge').hidden = false;
    $('result-meta').textContent = `${submittedLanguage === 'english' ? 'English' : 'Roman Urdu'} · ${((performance.now() - started) / 1000).toFixed(1)}s`;
    $('result-content').hidden = false;
    updateStale();
    $('announcement').textContent = 'Analysis complete. Your explanation and commented code are ready.';
  } catch (error) {
    $('error-state').hidden = false;
    $('error-heading').textContent = error.status === 422 ? 'Check your C++ code' : 'We couldn’t finish the analysis.';
    $('error-message').textContent = error.message;
    $('result-meta').textContent = 'Analysis not completed';
  } finally {
    clearInterval(timer);
    busy = false;
    $('loading-state').hidden = true;
    $('analyze-button').disabled = !canAnalyze();
    $('analyze-button').textContent = 'Analyze code →';
    if ($('optimize-button')) {
      $('optimize-button').disabled = !canAnalyze();
      $('optimize-button').textContent = 'Optimize to loop ⚡';
    }
    document.querySelector('.results-panel').setAttribute('aria-busy', 'false');
  }
}

async function runOptimization() {
  if (!canAnalyze()) return;
  busy = true;
  submittedCode = $('code').value;
  submittedLanguage = $('output-language').value;
  $('analyze-button').disabled = true;
  if ($('optimize-button')) {
    $('optimize-button').disabled = true;
    $('optimize-button').textContent = 'Optimizing…';
  }
  $('empty-state').hidden = $('error-state').hidden = $('result-content').hidden = $('result-badge').hidden = true;
  $('loading-state').hidden = false;
  document.querySelector('.results-panel').setAttribute('aria-busy', 'true');
  $('result-meta').textContent = 'Converting recursion to loop';
  $('announcement').textContent = 'Optimization started.';
  const started = performance.now();
  $('loading-message').textContent = 'The model is analyzing recursion and rewriting to an iterative loop / DP table…';
  const timer = setInterval(() => {
    $('loading-message').textContent = `Still working · ${Math.floor((performance.now() - started) / 1000)} seconds elapsed.`;
  }, 1000);

  try {
    const data = await request('/optimize', { code: submittedCode, source: 'web', mode: 'loop' }, 600000);
    result = data;
    $('raw-response').textContent = JSON.stringify(data, null, 2);

    if (data.code && data.changed) {
      $('optimized-code').textContent = data.code;
      $('optimization-note').textContent = data.note || (data.verified ? 'Verified: identical output on test inputs.' : 'Loop rewrite generated by model.');
      $('optimization-badge').hidden = false;
      if (data.verified) {
        $('optimization-badge').textContent = data.speedup > 1.0 ? `Verified ${data.speedup}x faster` : 'Verified equivalent';
        $('optimization-badge').className = 'result-badge';
      } else {
        $('optimization-badge').textContent = 'Candidate (unverified)';
        $('optimization-badge').className = 'result-badge review';
      }
      $('optimization-section').hidden = false;
      $('explanation').textContent = `Recursion to Loop Optimization:\n• Algorithm converted to iterative execution.\n• Status: ${data.verified ? 'Verified mathematically equivalent on test inputs' : 'Generated model candidate'}\n• Note: ${data.note || 'Loop conversion'}`;
      $('commented-code').textContent = data.code;
    } else {
      $('optimization-section').hidden = true;
      $('explanation').textContent = data.note ? `No rewrite applied: ${data.note}` : 'The model did not suggest an iterative loop transformation for this snippet.';
      $('commented-code').textContent = submittedCode;
    }

    $('review-notice').hidden = !data.changed || data.verified;
    $('result-badge').textContent = data.verified ? 'Complete' : (data.changed ? 'Candidate' : 'Unchanged');
    $('result-badge').classList.toggle('review', !data.verified && data.changed);
    $('result-badge').hidden = false;
    $('result-meta').textContent = `Loop optimization · ${((performance.now() - started) / 1000).toFixed(1)}s`;
    $('result-content').hidden = false;
    updateStale();
    $('announcement').textContent = 'Optimization complete. Result is ready.';
  } catch (error) {
    $('error-state').hidden = false;
    $('error-heading').textContent = 'We couldn’t finish the optimization.';
    $('error-message').textContent = error.message;
    $('result-meta').textContent = 'Optimization not completed';
  } finally {
    clearInterval(timer);
    busy = false;
    $('loading-state').hidden = true;
    $('analyze-button').disabled = !canAnalyze();
    $('analyze-button').textContent = 'Analyze code →';
    if ($('optimize-button')) {
      $('optimize-button').disabled = !canAnalyze();
      $('optimize-button').textContent = 'Optimize to loop ⚡';
    }
    document.querySelector('.results-panel').setAttribute('aria-busy', 'false');
  }
}

async function copyToClipboard(text) {
  if (!text) return false;
  // 1. Try modern Async Clipboard API first (supported in secure contexts)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch {
      // Fall through to textarea execCommand fallback
    }
  }
  // 2. Fallback for non-secure contexts (e.g. LAN IPs), older browsers, and WebViews
  try {
    const textarea = document.createElement('textarea');
    textarea.value = text;
    textarea.style.position = 'fixed';
    textarea.style.top = '0';
    textarea.style.left = '-9999px';
    textarea.style.opacity = '0';
    textarea.setAttribute('readonly', '');
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    textarea.setSelectionRange(0, textarea.value.length);
    const success = document.execCommand('copy');
    document.body.removeChild(textarea);
    return success;
  } catch {
    return false;
  }
}

function bindCopyButton(buttonId, getTextFn, defaultLabel) {
  const button = $(buttonId);
  if (!button) return;

  button.addEventListener('click', async (event) => {
    event.stopPropagation();
    const text = getTextFn();
    if (!text) return;

    const success = await copyToClipboard(text);
    if (success) {
      button.classList.remove('copy-failed');
      button.classList.add('copied');
      button.textContent = '✓ Copied!';
      $('announcement').textContent = 'Copied to clipboard.';
    } else {
      button.classList.remove('copied');
      button.classList.add('copy-failed');
      button.textContent = 'Copy failed';
      $('announcement').textContent = 'Clipboard unavailable. Select text manually.';
    }

    setTimeout(() => {
      button.classList.remove('copied', 'copy-failed');
      button.textContent = defaultLabel;
    }, 2200);
  });
}

bindCopyButton('copy-explanation', () => result?.explanation || $('explanation').textContent, 'Copy');
bindCopyButton('copy-code', () => result?.commented_code || $('commented-code').textContent, 'Copy code');
bindCopyButton('copy-optimized-code', () => $('optimized-code').textContent, 'Copy code');
bindCopyButton('copy-api-response', () => (result ? JSON.stringify(result, null, 2) : $('raw-response').textContent), 'Copy');

if ($('optimize-button')) {
  $('optimize-button').addEventListener('click', (event) => {
    event.preventDefault();
    if (!canAnalyze()) return;
    runOptimization();
  });
}


async function checkService() {
  $('retry-service').disabled = true;
  try {
    const data = await request('/ready', undefined, 15000);
    $('service-status').textContent = data.ready ? 'Model ready' : 'Model needs attention';
    $('service-status').className = data.ready ? 'ready' : 'unavailable';
    $('service-notice').hidden = data.ready;
    $('service-message').textContent = 'The model is not ready. Start the model server, then check again.';
  } catch {
    $('service-status').textContent = 'Backend unavailable';
    $('service-status').className = 'unavailable';
    $('service-message').textContent = 'Cannot reach the backend. Check that the API server is running, then try again.';
    $('service-notice').hidden = false;
  } finally { $('retry-service').disabled = false; }
}
$('retry-service').addEventListener('click', checkService);
updateEditor();
checkService();
