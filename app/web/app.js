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
  errorLine = line;
  $('analyze-button').disabled = !canAnalyze();
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
$('clear').addEventListener('click', () => { $('code').value = ''; updateEditor(); $('code').focus(); });
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
    $('raw-response').textContent = JSON.stringify(data, null, 2);
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
    document.querySelector('.results-panel').setAttribute('aria-busy', 'false');
  }
}

for (const [button, field] of [['copy-explanation', 'explanation'], ['copy-code', 'commented_code']]) {
  $(button).addEventListener('click', async () => {
    if (!result) return;
    const label = $(button).textContent;
    try {
      await navigator.clipboard.writeText(result[field]);
      $(button).textContent = 'Copied!';
      $('announcement').textContent = 'Copied to clipboard.';
    } catch {
      $('announcement').textContent = 'Clipboard unavailable. Select the result text to copy it manually.';
      $(button).textContent = 'Select text to copy';
    }
    setTimeout(() => { $(button).textContent = label; }, 2500);
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
