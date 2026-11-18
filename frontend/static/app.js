const state = {
  sessionId: 'demo-session',
  expenses: [],
};

let authToken = '';
let authConfig = null;
let authDisplayName = '';
const authTransactionKey = 'finance_auth_transaction';

const elements = {
  incomeValue: document.querySelector('#incomeValue'),
  spendValue: document.querySelector('#spendValue'),
  saveValue: document.querySelector('#saveValue'),
  remainingValue: document.querySelector('#remainingValue'),
  recommendationsList: document.querySelector('#recommendationsList'),
  alertsList: document.querySelector('#alertsList'),
  categoryBreakdown: document.querySelector('#categoryBreakdown'),
  incomeInput: document.querySelector('#incomeInput'),
  currencySelect: document.querySelector('#currencySelect'),
  locationInput: document.querySelector('#locationInput'),
  chatMessages: document.querySelector('#chatMessages'),
  chatForm: document.querySelector('#chatForm'),
  chatInput: document.querySelector('#chatInput'),
  analyzeButton: document.querySelector('#analyzeButton'),
  demoDataButton: document.querySelector('#demoDataButton'),
  authGate: document.querySelector('#authGate'),
  authMessage: document.querySelector('#authMessage'),
  authLoginButton: document.querySelector('#authLoginButton'),
  authLogoutButton: document.querySelector('#authLogoutButton'),
  chatThinking: document.querySelector('#chatThinking'),
};
let chatProcessing = false;

function randomBase64Url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function randomAuthValue() {
  return randomBase64Url(crypto.getRandomValues(new Uint8Array(32)));
}

async function createCodeChallenge(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return randomBase64Url(new Uint8Array(digest));
}

function authDomain() {
  return authConfig.domain.replace(/^https?:\/\//, '').replace(/\/+$/, '');
}

function getIdTokenName(idToken) {
  const encodedPayload = idToken?.split('.')[1];
  if (!encodedPayload) return '';
  const base64 = encodedPayload.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
  const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  const claims = JSON.parse(new TextDecoder().decode(bytes));
  return [
    claims.name,
    claims.nickname,
    claims.preferred_username,
    claims.email,
  ].find((value) => typeof value === 'string' && value.trim())?.trim() || '';
}

async function login() {
  try {
    const verifier = randomAuthValue();
    const state = randomAuthValue();
    const challenge = await createCodeChallenge(verifier);
    localStorage.setItem(authTransactionKey, JSON.stringify({ verifier, state }));
    const authorizeUrl = `https://${authDomain()}/authorize?` + new URLSearchParams({
      response_type: 'code',
      client_id: authConfig.client_id,
      redirect_uri: window.location.origin,
      audience: authConfig.audience,
      scope: 'openid profile email',
      code_challenge: challenge,
      code_challenge_method: 'S256',
      state,
    });
    window.location.href = authorizeUrl;
  } catch (error) {
    elements.authMessage.textContent = error.message || 'Could not start Auth0 sign-in.';
  }
}

async function initializeAuth() {
  try {
    const configResponse = await fetch('/api/auth/config');
    if (!configResponse.ok) throw new Error('Could not load Auth0 configuration.');
    authConfig = (await configResponse.json()).data;
    if (!authConfig?.enabled || !authConfig.domain || !authConfig.client_id || !authConfig.audience) {
      elements.authMessage.textContent = 'Auth0 is not configured on the backend.';
      return;
    }

    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (params.has('error')) throw new Error(params.get('error_description') || 'Auth0 sign-in was not completed.');
    if (code) {
      const transaction = JSON.parse(localStorage.getItem(authTransactionKey) || 'null');
      localStorage.removeItem(authTransactionKey);
      if (!transaction?.state || transaction.state !== params.get('state') || !transaction.verifier) {
        throw new Error('The Auth0 login state could not be verified. Please try again.');
      }
      const response = await fetch(`https://${authDomain()}/oauth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          grant_type: 'authorization_code',
          client_id: authConfig.client_id,
          code,
          code_verifier: transaction.verifier,
          redirect_uri: window.location.origin,
        }),
      });
      const result = await response.json();
      if (!response.ok || !result.access_token) {
        throw new Error(result.error_description || 'Auth0 could not complete sign-in.');
      }
      authToken = result.access_token;
      authDisplayName = getIdTokenName(result.id_token);
      window.history.replaceState({}, document.title, window.location.pathname);
    } else {
      elements.authLoginButton.hidden = false;
      elements.authLoginButton.addEventListener('click', login);
      elements.authMessage.textContent = 'Please sign in with Auth0 to continue.';
      return;
    }

    const identityResponse = await fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${authToken}` },
    });
    const identity = await identityResponse.json();
    if (!identityResponse.ok || !identity?.data?.sub) {
      throw new Error(identity.detail || 'Your login could not be verified.');
    }
    state.sessionId = identity.data.sub;
    authDisplayName = authDisplayName
      || identity.data.display_name
      || identity.data.name
      || identity.data.email
      || 'your account';
    elements.authGate.hidden = true;
    document.querySelector('.app-shell').hidden = false;
    setupEvents();
    addChatMessage('bot', `Signed in securely as ${authDisplayName}.`);
    analyzeBudget();
  } catch (error) {
    authToken = '';
    elements.authMessage.setAttribute('role', 'alert');
    elements.authMessage.textContent = error.message || 'Auth0 sign-in failed.';
    if (authConfig?.enabled) {
      elements.authLoginButton.hidden = false;
      elements.authLoginButton.addEventListener('click', login);
    }
    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

function formatCurrency(amount, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(amount);
}

function renderCategoryBreakdown(categories) {
  const entries = Object.entries(categories || {});
  const max = Math.max(...entries.map(([, value]) => Number(value) || 0), 1);

  if (!entries.length) {
    elements.categoryBreakdown.innerHTML = '<p>No categories yet.</p>';
    return;
  }

  elements.categoryBreakdown.innerHTML = entries
    .map(([name, value]) => {
      const percentage = ((Number(value) || 0) / max) * 100;
      return `
        <div class="category-row">
          <span>${name}</span>
          <div class="progress-bar"><span class="progress-fill" style="width:${percentage}%"></span></div>
          <strong>${formatCurrency(value)}</strong>
        </div>
      `;
    })
    .join('');
}

function setDashboard(data) {
  const income = Number(data.income || 0);
  const spend = Number(data.total_spending || 0);
  const remaining = Number(data.remaining || 0);
  const savingsRate = Number(data.savings_rate || 0);

  elements.incomeValue.textContent = formatCurrency(income, data.currency || 'USD');
  elements.spendValue.textContent = formatCurrency(spend, data.currency || 'USD');
  elements.saveValue.textContent = `${savingsRate}%`;
  elements.remainingValue.textContent = formatCurrency(remaining, data.currency || 'USD');

  elements.recommendationsList.innerHTML = (data.recommendations || [])
    .map((item) => `<li>${item}</li>`)
    .join('');

  elements.alertsList.innerHTML = (data.alerts || []).length
    ? (data.alerts || []).map((alert) => `<li>${alert}</li>`).join('')
    : '<li>No alerts — spending looks balanced.</li>';

  renderCategoryBreakdown(data.categories || {});
}

async function analyzeBudget() {
  const income = Number(elements.incomeInput.value || 0);
  const currency = elements.currencySelect.value;
  const location = elements.locationInput.value.trim();

  const payload = {
    income,
    currency,
    location,
    transactions: state.expenses,
  };

  const response = await fetch('/api/finance/analyze', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    console.error('Budget analysis failed');
    return;
  }

  const result = await response.json();
  const data = result.data;
  setDashboard(data);
  addChatMessage('bot', `Budget analysis complete. Your savings rate is ${data.savings_rate}% and the largest category is ${data.largest_category || 'Other'}.`);
}

function addChatMessage(sender, text) {
  const bubble = document.createElement('div');
  bubble.className = `chat-bubble ${sender}`;
  bubble.textContent = text;
  elements.chatMessages.appendChild(bubble);
  elements.chatMessages.scrollTo({
    top: elements.chatMessages.scrollHeight,
    behavior: 'smooth',
  });
}

async function sendChatMessage() {
  const input = elements.chatInput.value.trim();
  if (!input || chatProcessing) return;

  addChatMessage('user', input);
  elements.chatInput.value = '';
  chatProcessing = true;
  elements.chatThinking.hidden = false;
  elements.chatMessages.appendChild(elements.chatThinking);
  elements.chatInput.disabled = true;
  elements.chatForm.querySelector('button[type="submit"]').disabled = true;
  elements.chatMessages.scrollTo({
    top: elements.chatMessages.scrollHeight,
    behavior: 'smooth',
  });

  const payload = {
    message: input,
    session_id: state.sessionId,
    income: Number(elements.incomeInput.value || 0),
    location: elements.locationInput.value.trim() || null,
    transactions: state.expenses,
  };

  try {
    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authToken}` },
      body: JSON.stringify(payload),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || 'The advisor could not answer that request right now.');
    }

    addChatMessage('bot', result.data.reply || 'I have your numbers and can help you plan.');
  } catch (error) {
    console.error('Chat request failed.', error);
    addChatMessage('bot', error.message || 'The advisor could not answer that request right now.');
  } finally {
    chatProcessing = false;
    elements.chatThinking.hidden = true;
    elements.chatInput.disabled = false;
    elements.chatForm.querySelector('button[type="submit"]').disabled = false;
  }
}

function loadDemoData() {
  elements.incomeInput.value = 6000;
  elements.currencySelect.value = 'USD';
  elements.locationInput.value = 'New York';
  state.expenses = [
    { description: 'Rent', amount: 1800, currency: 'USD' },
    { description: 'Groceries', amount: 540, currency: 'USD' },
    { description: 'Gym membership', amount: 90, currency: 'USD' },
    { description: 'Streaming services', amount: 45, currency: 'USD' },
    { description: 'Dining out', amount: 310, currency: 'USD' },
    { description: 'Fuel', amount: 145, currency: 'USD' },
    { description: 'Travel booking', amount: 500, currency: 'USD' },
  ];

  analyzeBudget();
}

function setupEvents() {
  elements.analyzeButton.addEventListener('click', analyzeBudget);
  elements.demoDataButton.addEventListener('click', loadDemoData);
  elements.authLogoutButton.addEventListener('click', () => {
    const returnTo = encodeURIComponent(window.location.origin);
    window.location.href = `https://${authDomain()}/v2/logout?client_id=${authConfig.client_id}&returnTo=${returnTo}`;
  });
  elements.chatForm.addEventListener('submit', (event) => {
    event.preventDefault();
    sendChatMessage();
  });
}

initializeAuth();
