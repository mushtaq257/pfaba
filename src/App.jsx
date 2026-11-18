import { useEffect, useMemo, useRef, useState } from 'react';
import { readSheet } from 'read-excel-file/browser';
import writeExcelFile from 'write-excel-file/browser';
import { getUpcomingTransactions } from './upcomingTransactionReminders.js';
import AdminDashboard from './AdminDashboard.jsx';

const MONTHLY_TRANSACTIONS_STORAGE_KEY = 'finance_monthly_transactions';
const MONTHLY_INCOME_STORAGE_KEY = 'finance_monthly_income';
const MONTHLY_CREDITS_STORAGE_KEY = 'finance_monthly_credits';
const GOALS_STORAGE_KEY = 'finance_goals';
const LOCATION_OVERRIDE_STORAGE_KEY = 'finance_location_override';
const AUTH_TRANSACTION_KEY = 'finance_auth_transaction';
const AUTH_VERIFICATION_TIMEOUT_MS = 15000;
const HISTORICAL_DATA_RESTRICTION_MESSAGE = 'You do not have permission to change data from previous months.';
const DEFAULT_MONTHLY_INCOME = 0;
const EMPTY_TRANSACTIONS = [];
const currencies = ['INR', 'USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'SGD', 'AED'];
const expenseCategories = ['Housing', 'Loan', 'Food', 'Transport', 'Utilities', 'Shopping', 'Entertainment', 'Health', 'Travel', 'Investment', 'Other'];
const themes = [
  { value: 'midnight', label: 'Midnight' },
  { value: 'ocean', label: 'Ocean Blue' },
  { value: 'forest', label: 'Forest' },
  { value: 'plum', label: 'Royal Plum' },
  { value: 'saffron', label: 'India Saffron' },
  { value: 'light', label: 'Light' },
  { value: 'ivory', label: 'Warm Ivory' },
  { value: 'rose', label: 'Rose' },
  { value: 'mint', label: 'Mint' },
  { value: 'graphite', label: 'Graphite' },
  { value: 'royal-blue', label: 'Royal Blue' },
  { value: 'aurora', label: 'Aurora' },
  { value: 'sunset', label: 'Sunset Glow' },
  { value: 'royal-purple', label: 'Royal Purple' },
];

function formatCurrency(value, currency = 'USD') {
  const locale = currency === 'INR' ? 'en-IN' : 'en-US';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency,
    maximumFractionDigits: 2,
  }).format(Number(value || 0));
}

function createChatEntry(sender, text, metadata = {}) {
  return {
    sender,
    text,
    timestamp: new Date().toISOString(),
    ...metadata,
  };
}

function buildBudgetHighlights(analysis) {
  const currency = analysis.currency || 'USD';
  const categoryAmount = analysis.largest_category_amount
    ?? analysis.categories?.[analysis.largest_category]
    ?? 0;
  const keyPoint = analysis.alerts?.[0]
    || analysis.recommendations?.[1]
    || 'Keep tracking expenses to build a reliable budget.';

  return [
    `Income: ${formatCurrency(analysis.income, currency)}; spending: ${formatCurrency(analysis.total_spending, currency)}.`,
    `Remaining: ${formatCurrency(analysis.remaining, currency)}; savings rate: ${Number(analysis.savings_rate || 0).toFixed(1)}%.`,
    `Largest category: ${analysis.largest_category || 'Other'} (${formatCurrency(categoryAmount, currency)}).`,
    `Key point: ${keyPoint}`,
  ].join('\n');
}

function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

function periodKey(year, month) {
  return `${year}-${String(month).padStart(2, '0')}`;
}

function currentPeriodKey() {
  const now = new Date();
  return periodKey(now.getFullYear(), now.getMonth() + 1);
}

function hasAdminRole(user) {
  return Array.isArray(user?.roles)
    && user.roles.some((role) => typeof role === 'string' && role.trim().toLowerCase() === 'admin');
}

function dateForPeriod(key) {
  if (key === currentPeriodKey()) return formatLocalDate(new Date());
  return `${key}-01`;
}

function downloadBlob(blob, fileName) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function createTransactionId() {
  return globalThis.crypto?.randomUUID?.()
    || `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

function normalizeStoredCredits(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Saved monthly credits have an invalid format.');
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, entries]) => {
      if (!/^\d{4}-\d{2}$/.test(key) || !Array.isArray(entries)) {
        throw new Error(`Saved credits for ${key} have an invalid format.`);
      }
      return [
        key,
        entries.map((entry) => ({
          ...entry,
          id: entry.id || createTransactionId(),
          date: entry.date || dateForPeriod(key),
        })),
      ];
    }),
  );
}

function normalizeStoredTransactions(value) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new Error('Saved monthly transactions have an invalid format.');
  }

  return Object.fromEntries(
    Object.entries(value).map(([key, entries]) => {
      if (!/^\d{4}-\d{2}$/.test(key) || !Array.isArray(entries)) {
        throw new Error(`Saved transactions for ${key} have an invalid format.`);
      }
      return [
        key,
        entries.map((entry) => ({
          ...entry,
          id: entry.id || createTransactionId(),
          date: entry.date || dateForPeriod(key),
        })),
      ];
    }),
  );
}

function userStorageKey(key, subject) {
  return `${key}:${encodeURIComponent(subject)}`;
}

function getFinanceLocation(manualLocation, detectedLocation) {
  const override = manualLocation.trim();
  if (override) return override;

  const city = detectedLocation?.city;
  const qualifier = detectedLocation?.region || detectedLocation?.country;
  return [city, qualifier].filter(Boolean).join(', ') || null;
}

function loadMonthlyTransactions(storageKey) {
  const stored = localStorage.getItem(storageKey);
  if (stored !== null) {
    try {
      return normalizeStoredTransactions(JSON.parse(stored));
    } catch (error) {
      console.error('Could not load saved monthly transactions.', error);
      return {};
    }
  }

  return {};
}

function loadMonthlyCredits(storageKey) {
  const stored = localStorage.getItem(storageKey);
  if (stored !== null) {
    try {
      return normalizeStoredCredits(JSON.parse(stored));
    } catch (error) {
      console.error('Could not load saved monthly credits.', error);
    }
  }

  return {};
}

function loadMonthlyIncome(storageKey) {
  const stored = localStorage.getItem(storageKey);
  if (stored !== null) {
    try {
      const values = JSON.parse(stored);
      if (!values || typeof values !== 'object' || Array.isArray(values)) {
        throw new Error('Saved monthly income has an invalid format.');
      }
      return Object.fromEntries(
        Object.entries(values).map(([key, value]) => {
          const amount = Number(value);
          if (!/^\d{4}-\d{2}$/.test(key) || !Number.isFinite(amount) || amount < 0) {
            throw new Error(`Saved income for ${key} is invalid.`);
          }
          return [key, amount];
        }),
      );
    } catch (error) {
      console.error('Could not load saved monthly income.', error);
      return {};
    }
  }

  return {};
}

function loadGoals(storageKey) {
  const stored = localStorage.getItem(storageKey);
  if (stored === null) return [];
  const goals = JSON.parse(stored);
  if (!Array.isArray(goals)) {
    throw new Error('Saved goals have an invalid format.');
  }
  return goals;
}

function randomBase64Url(bytes) {
  return btoa(String.fromCharCode(...bytes))
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');
}

function randomAuthValue() {
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return randomBase64Url(bytes);
}

async function createCodeChallenge(verifier) {
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
  return randomBase64Url(new Uint8Array(digest));
}

function getIdTokenProfile(idToken) {
  const encodedPayload = idToken?.split('.')[1];
  if (!encodedPayload) return { name: '', username: '', email: '' };
  const base64 = encodedPayload.replace(/-/g, '+').replace(/_/g, '/');
  const padded = base64.padEnd(Math.ceil(base64.length / 4) * 4, '=');
  const bytes = Uint8Array.from(atob(padded), (character) => character.charCodeAt(0));
  const claims = JSON.parse(new TextDecoder().decode(bytes));
  const firstClaim = (values) => (
    values.find((value) => typeof value === 'string' && value.trim())?.trim() || ''
  );
  return {
    name: firstClaim([
      claims.name,
      claims.nickname,
      claims.preferred_username,
      claims.email,
    ]),
    username: firstClaim([
      claims.preferred_username,
      claims.nickname,
      claims.email,
    ]),
    email: firstClaim([claims.email]),
  };
}

function previousPeriodKey(key) {
  const [year, month] = key.split('-').map(Number);
  return month === 1 ? periodKey(year - 1, 12) : periodKey(year, month - 1);
}

function monthlySpendingTotal(entries, budgetCurrency) {
  return entries.reduce((sum, entry) => {
    if (entry.converted_currency === budgetCurrency) {
      return sum + Number(entry.converted_amount || 0);
    }
    if (!entry.currency || entry.currency === budgetCurrency) {
      return sum + Number(entry.amount || 0);
    }
    return sum;
  }, 0);
}

function monthlyCreditTotal(entries, budgetCurrency) {
  return entries.reduce((sum, entry) => {
    if (entry.converted_currency === budgetCurrency) {
      return sum + Number(entry.converted_amount || 0);
    }
    if (!entry.currency || entry.currency === budgetCurrency) {
      return sum + Number(entry.amount || 0);
    }
    return sum;
  }, 0);
}

function calculateCarryForward(key, transactionsByMonth, incomeByMonth, creditsByMonth, budgetCurrency, depth = 0) {
  if (depth >= 120) return 0;
  const previousKey = previousPeriodKey(key);
  const hasPreviousData = Object.prototype.hasOwnProperty.call(transactionsByMonth, previousKey)
    || Object.prototype.hasOwnProperty.call(incomeByMonth, previousKey)
    || Object.prototype.hasOwnProperty.call(creditsByMonth, previousKey);
  if (!hasPreviousData) return 0;

  const previousCarry = calculateCarryForward(
    previousKey,
    transactionsByMonth,
    incomeByMonth,
    creditsByMonth,
    budgetCurrency,
    depth + 1,
  );
  const previousIncome = incomeByMonth[previousKey] ?? DEFAULT_MONTHLY_INCOME;
  const previousCredits = monthlyCreditTotal(creditsByMonth[previousKey] || EMPTY_TRANSACTIONS, budgetCurrency);
  const previousSpending = monthlySpendingTotal(
    transactionsByMonth[previousKey] || EMPTY_TRANSACTIONS,
    budgetCurrency,
  );
  return Math.max(previousIncome + previousCredits + previousCarry - previousSpending, 0);
}

function parseCsv(text) {
  const rows = [];
  let row = [];
  let cell = '';
  let inQuotes = false;
  const source = text.replace(/^\uFEFF/, '');

  for (let index = 0; index < source.length; index += 1) {
    const character = source[index];
    if (character === '"') {
      if (inQuotes && source[index + 1] === '"') {
        cell += '"';
        index += 1;
      } else {
        inQuotes = !inQuotes;
      }
    } else if (character === ',' && !inQuotes) {
      row.push(cell.trim());
      cell = '';
    } else if ((character === '\n' || character === '\r') && !inQuotes) {
      if (character === '\r' && source[index + 1] === '\n') index += 1;
      row.push(cell.trim());
      if (row.some((value) => value !== '')) rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += character;
    }
  }

  if (inQuotes) throw new Error('The CSV file contains an unclosed quoted field.');
  row.push(cell.trim());
  if (row.some((value) => value !== '')) rows.push(row);
  return rows;
}

function normalizeHeader(value) {
  return String(value ?? '')
    .replace(/^\uFEFF/, '')
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '');
}

function parseNumeric(value) {
  if (typeof value === 'number') return value;
  if (value === null || value === undefined || String(value).trim() === '') return Number.NaN;
  const cleaned = String(value)
    .replace(/[₹$€£¥,%\s]/g, '')
    .replace(/,/g, '')
    .replace(/[^0-9.-]/g, '');
  return cleaned ? Number(cleaned) : Number.NaN;
}

function parseTransactionDate(value, fallbackPeriod) {
  if (value === null || value === undefined || String(value).trim() === '') {
    return dateForPeriod(fallbackPeriod);
  }
  const date = value instanceof Date ? value : new Date(String(value).trim());
  if (Number.isNaN(date.getTime())) return null;
  return formatLocalDate(date);
}

function buildCategorySummary(items, budgetCurrency) {
  const map = {};
  for (const item of items) {
    const category = item.category || 'Other';
    const amount = item.converted_currency === budgetCurrency
      ? Number(item.converted_amount || 0)
      : (!item.currency || item.currency === budgetCurrency ? Number(item.amount || 0) : 0);
    if (amount > 0) map[category] = (map[category] || 0) + amount;
  }
  return Object.fromEntries(Object.entries(map).sort((a, b) => b[1] - a[1]));
}

function AuthScreen({ loading, configured, error, onLogin, onLogout }) {
  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="auth-brand">
          <span className="auth-brand-mark" aria-hidden="true">₹</span>
          <span>
            <strong>Personal Finance &amp; Budget Advisor</strong>
            <small>PERSONAL FINANCE</small>
          </span>
        </div>

        <div className="auth-illustration" aria-hidden="true">
          <div className="auth-illustration-heading">
            <span>YOUR FINANCIAL SNAPSHOT</span>
            <span className="auth-chart-trend">↗</span>
          </div>
          <div className="auth-chart">
            {[34, 48, 41, 65, 53, 78, 70, 96, 82, 100, 88, 112].map((height, index) => (
              <i key={index} style={{ height: `${height}px` }} />
            ))}
          </div>
          <div className="auth-illustration-footer">
            <span className="auth-ring">₹</span>
            <span><strong>Plan with confidence</strong><small>Budgets · Goals · Insights</small></span>
            <span className="auth-arrow">↗</span>
          </div>
        </div>

        <div className="auth-copy">
          <span className="auth-eyebrow">YOUR MONEY, MADE CLEAR</span>
          <h1>Build a better relationship with your money.</h1>
          <p>Get a clear view of your spending, shape a budget that works, and keep your goals in sight.</p>
        </div>

        {error && <p className="auth-error" role="alert">{error}</p>}
        {loading ? (
          <div className="auth-loading" role="status">
            <span className="auth-spinner" />
            Verifying your secure sign-in…
          </div>
        ) : configured && onLogin ? (
          <button className="auth-login-button" type="button" onClick={onLogin}>
            <span>Continue securely with Auth0</span>
            <span aria-hidden="true">→</span>
          </button>
        ) : !configured ? (
          <p className="auth-error" role="alert">
            Auth0 is not configured. Set AUTH0_DOMAIN, AUTH0_CLIENT_ID, and AUTH0_AUDIENCE on the backend.
          </p>
        ) : null}
        {onLogout && (
          <button className="auth-logout-button" type="button" onClick={onLogout}>
            Sign out of Auth0
          </button>
        )}

        <div className="auth-security">
          <span className="auth-security-icon" aria-hidden="true">✓</span>
          <span>Your financial data stays private and secure</span>
        </div>
      </section>
      <p className="auth-page-note">A calmer, clearer way to manage your finances.</p>
    </main>
  );
}

function App() {
  const [selectedMonth, setSelectedMonth] = useState(() => new Date().getMonth() + 1);
  const [selectedYear, setSelectedYear] = useState(() => new Date().getFullYear());
  const selectedPeriod = periodKey(selectedYear, selectedMonth);
  const [monthlyTransactions, setMonthlyTransactions] = useState({});
  const [monthlyIncome, setMonthlyIncome] = useState({});
  const [monthlyCredits, setMonthlyCredits] = useState({});
  const [userDataLoaded, setUserDataLoaded] = useState(false);
  const transactions = monthlyTransactions[selectedPeriod] || EMPTY_TRANSACTIONS;
  const credits = monthlyCredits[selectedPeriod] || EMPTY_TRANSACTIONS;
  const income = monthlyIncome[selectedPeriod] ?? DEFAULT_MONTHLY_INCOME;
  const setTransactions = (nextValue) => {
    setMonthlyTransactions((previous) => {
      const current = previous[selectedPeriod] || EMPTY_TRANSACTIONS;
      const updated = typeof nextValue === 'function' ? nextValue(current) : nextValue;
      const next = { ...previous };
      if (updated.length) next[selectedPeriod] = updated;
      else delete next[selectedPeriod];
      return next;
    });
  };
  const setIncome = (nextValue) => {
    setMonthlyIncome((previous) => {
      const current = previous[selectedPeriod] ?? DEFAULT_MONTHLY_INCOME;
      const updated = typeof nextValue === 'function' ? nextValue(current) : nextValue;
      return { ...previous, [selectedPeriod]: updated };
    });
  };
  const setCredits = (nextValue) => {
    setMonthlyCredits((previous) => {
      const current = previous[selectedPeriod] || EMPTY_TRANSACTIONS;
      const updated = typeof nextValue === 'function' ? nextValue(current) : nextValue;
      const next = { ...previous };
      if (updated.length) next[selectedPeriod] = updated;
      else delete next[selectedPeriod];
      return next;
    });
  };
  const [currency, setCurrency] = useState('INR');
  const [location, setLocation] = useState('');
  const [currentLocation, setCurrentLocation] = useState(null);
  const [locationStatus, setLocationStatus] = useState('loading');
  const [locationError, setLocationError] = useState('');
  const [currentTime, setCurrentTime] = useState(() => new Date());
  const [theme, setTheme] = useState(() => localStorage.getItem('finance_theme') || 'midnight');
  const [transactionDraft, setTransactionDraft] = useState({
    description: '',
    amount: '',
    category: 'Food',
    currency: 'INR',
    date: '',
  });
  const [transactionError, setTransactionError] = useState('');
  const [importError, setImportError] = useState('');
  const [importing, setImporting] = useState(false);
  const [editingTransactionId, setEditingTransactionId] = useState(null);
  const [editingDraft, setEditingDraft] = useState(null);
  const [transactionSaving, setTransactionSaving] = useState(false);
  const [creditDraft, setCreditDraft] = useState({
    amount: '',
    currency: 'INR',
    source: '',
    date: '',
  });
  const [creditError, setCreditError] = useState('');
  const [creditSaving, setCreditSaving] = useState(false);
  const [creditCurrencyChanging, setCreditCurrencyChanging] = useState(false);
  const [editingCreditId, setEditingCreditId] = useState(null);
  const [editingCreditDraft, setEditingCreditDraft] = useState(null);
  const [conversionAmount, setConversionAmount] = useState('1');
  const [conversionFrom, setConversionFrom] = useState('USD');
  const [conversionTo, setConversionTo] = useState('INR');
  const [currencyConversion, setCurrencyConversion] = useState(null);
  const [conversionError, setConversionError] = useState('');
  const [conversionLoading, setConversionLoading] = useState(false);
  const [goals, setGoals] = useState([]);
  const [goalDraft, setGoalDraft] = useState({ name: '', target: '', saved: '' });
  const [analysis, setAnalysis] = useState(null);
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState(() => [
    createChatEntry('bot', 'Welcome! I can help review spending, budgets, and savings goals.'),
  ]);
  const [chatProcessing, setChatProcessing] = useState(false);
  const chatMessagesRef = useRef(null);
  const analysisRequestId = useRef(0);
  const [loading, setLoading] = useState(false);
  const [authConfig, setAuthConfig] = useState({ enabled: false, domain: null, audience: null, client_id: null });
  const [authConfigLoaded, setAuthConfigLoaded] = useState(false);
  const [authToken, setAuthToken] = useState('');
  const [authDisplayName, setAuthDisplayName] = useState('');
  const [authUsername, setAuthUsername] = useState('');
  const [authEmail, setAuthEmail] = useState('');
  const [authUser, setAuthUser] = useState(null);
  const [authStatus, setAuthStatus] = useState('checking');
  const [authError, setAuthError] = useState('');
  const callbackInProgress = useRef(false);
  const isAdmin = hasAdminRole(authUser);
  const historicalPermissions = authUser?.historical_permissions || {};
  const isHistoricalMonth = selectedPeriod !== currentPeriodKey();
  const canEditSelectedPeriod = !isHistoricalMonth
    || isAdmin
    || historicalPermissions.can_edit_previous_month;
  const canDeleteSelectedPeriod = !isHistoricalMonth
    || isAdmin
    || historicalPermissions.can_delete_previous_month;
  const canClearSelectedPeriod = !isHistoricalMonth
    || isAdmin
    || historicalPermissions.can_clear_previous_month;
  const appendChatMessage = (sender, text, metadata = {}) => {
    setChatHistory((previous) => [
      ...previous,
      createChatEntry(sender, text, metadata),
    ]);
  };

  const carryForward = calculateCarryForward(
    selectedPeriod,
    monthlyTransactions,
    monthlyIncome,
    monthlyCredits,
    currency,
  );
  const creditIncome = monthlyCreditTotal(credits, currency);
  const totalIncome = income + creditIncome;
  const availableBudget = totalIncome + carryForward;
  const summary = useMemo(() => {
    const totalSpending = monthlySpendingTotal(transactions, currency);
    const remaining = availableBudget - totalSpending;
    const savingsRate = availableBudget > 0 ? (remaining / availableBudget) * 100 : 0;
    return {
      totalSpending,
      remaining,
      savingsRate,
    };
  }, [availableBudget, currency, transactions]);

  const categorySummary = useMemo(() => {
    return buildCategorySummary(transactions, currency);
  }, [currency, transactions]);

  const fetchCurrentLocation = async () => {
    setLocationStatus('loading');
    setLocationError('');

    try {
      if (!navigator.geolocation) {
        throw new Error('This browser does not support device geolocation.');
      }

      const position = await new Promise((resolve, reject) => {
        navigator.geolocation.getCurrentPosition(resolve, reject, {
          enableHighAccuracy: true,
          maximumAge: 60000,
          timeout: 15000,
        });
      });
      const params = new URLSearchParams({
        latitude: String(position.coords.latitude),
        longitude: String(position.coords.longitude),
      });
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 10000);
      let response;
      try {
        response = await fetch(`/api/location/reverse?${params}`, {
          signal: controller.signal,
        });
      } finally {
        window.clearTimeout(timeout);
      }
      if (!response.ok) {
        throw new Error(`Reverse geocoding failed with HTTP ${response.status}.`);
      }

      const payload = await response.json();
      if (!payload.data?.city && !payload.data?.region && !payload.data?.country) {
        throw new Error('Reverse geocoding returned no location details.');
      }

      setCurrentLocation(payload.data);
      setLocationStatus('ready');
    } catch (error) {
      setCurrentLocation(null);
      setLocationStatus('error');
      if (error.code === 1) {
        setLocationError('Location permission denied. Allow location access in your browser and retry.');
      } else if (error.code === 2) {
        setLocationError('Your device could not determine its location. Check location services and retry.');
      } else if (error.code === 3 || error.name === 'AbortError') {
        setLocationError('Location lookup timed out. Try again.');
      } else {
        setLocationError('Location is unavailable. Check your connection and try again.');
      }
    }
  };

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    localStorage.setItem('finance_theme', theme);
  }, [theme]);

  useEffect(() => {
    if (!authUser || !userDataLoaded || isAdmin) return;
    localStorage.setItem(
      userStorageKey(MONTHLY_TRANSACTIONS_STORAGE_KEY, authUser.sub),
      JSON.stringify(monthlyTransactions),
    );
  }, [authUser, isAdmin, monthlyTransactions, userDataLoaded]);

  useEffect(() => {
    if (!authUser || !userDataLoaded || isAdmin) return;
    localStorage.setItem(
      userStorageKey(MONTHLY_INCOME_STORAGE_KEY, authUser.sub),
      JSON.stringify(monthlyIncome),
    );
  }, [authUser, isAdmin, monthlyIncome, userDataLoaded]);

  useEffect(() => {
    if (!authUser || !userDataLoaded || isAdmin) return;
    localStorage.setItem(
      userStorageKey(MONTHLY_CREDITS_STORAGE_KEY, authUser.sub),
      JSON.stringify(monthlyCredits),
    );
  }, [authUser, isAdmin, monthlyCredits, userDataLoaded]);

  useEffect(() => {
    const timerId = window.setInterval(() => setCurrentTime(new Date()), 1000);
    return () => window.clearInterval(timerId);
  }, []);

  useEffect(() => {
    setTransactionDraft((previous) => ({
      ...previous,
      date: dateForPeriod(selectedPeriod),
    }));
  }, [selectedPeriod]);

  useEffect(() => {
    const messages = chatMessagesRef.current;
    if (messages) {
      messages.scrollTo({ top: messages.scrollHeight, behavior: 'smooth' });
    }
  }, [chatHistory]);

  useEffect(() => {
    fetch('/api/auth/config')
      .then((response) => {
        if (!response.ok) throw new Error(`Auth configuration request failed (${response.status}).`);
        return response.json();
      })
      .then((result) => {
        if (result?.data) {
          setAuthConfig(result.data);
        }
        setAuthConfigLoaded(true);
      })
      .catch((error) => {
        setAuthConfig({ enabled: false, domain: null, audience: null, client_id: null });
        setAuthError(error.message || 'Could not load Auth0 configuration.');
        setAuthConfigLoaded(true);
      });
  }, []);

  useEffect(() => {
    if (!authConfigLoaded || !authConfig.enabled || !authConfig.domain) return;
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    const returnedState = params.get('state');
    if (!code && !params.has('error')) return;
    if (callbackInProgress.current) return;
    callbackInProgress.current = true;

    const finishLogin = async () => {
      try {
        if (params.has('error')) {
          throw new Error(params.get('error_description') || 'Auth0 sign-in was not completed.');
        }
        const transaction = JSON.parse(localStorage.getItem(AUTH_TRANSACTION_KEY) || 'null');
        localStorage.removeItem(AUTH_TRANSACTION_KEY);
        if (!transaction?.state || transaction.state !== returnedState || !transaction.verifier) {
          throw new Error('The Auth0 login state could not be verified. Please try again.');
        }
        const domain = authConfig.domain.replace(/^https?:\/\//, '').replace(/\/+$/, '');
        const response = await fetch(`https://${domain}/oauth/token`, {
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
        const idTokenProfile = getIdTokenProfile(result.id_token);
        setAuthDisplayName(idTokenProfile.name);
        setAuthUsername(idTokenProfile.username);
        setAuthEmail(idTokenProfile.email);
        setAuthToken(result.access_token);
        setAuthError('');
      } catch (error) {
        setAuthError(error.message || 'Auth0 sign-in failed.');
        setAuthStatus('unauthenticated');
      } finally {
        window.history.replaceState({}, document.title, window.location.pathname);
      }
    };
    finishLogin();
  }, [authConfig, authConfigLoaded]);

  useEffect(() => {
    if (!authConfigLoaded) return;
    if (!authConfig.enabled) {
      setAuthStatus('unauthenticated');
      return;
    }
    if (!authToken) {
      setAuthUser(null);
      setAuthStatus('unauthenticated');
      return;
    }

    let active = true;
    const controller = new AbortController();
    const timeoutId = window.setTimeout(
      () => controller.abort(),
      AUTH_VERIFICATION_TIMEOUT_MS,
    );
    setAuthStatus('checking');
    fetch('/api/auth/me', {
      headers: { Authorization: `Bearer ${authToken}` },
      signal: controller.signal,
    })
      .then(async (response) => {
        const result = await response.json();
        if (!response.ok || !result?.data?.sub) {
          throw new Error(result.detail || 'Your login is invalid or has expired.');
        }
        if (active) {
          setAuthUser({
            ...result.data,
            display_name: authDisplayName
              || result.data.display_name
              || result.data.name
              || result.data.email
              || 'Your account',
          });
          setAuthStatus('authenticated');
          setAuthError('');
        }
      })
      .catch((error) => {
        if (!active) return;
        setAuthToken('');
        setAuthUser(null);
        setAuthStatus('unauthenticated');
        setAuthError(error.name === 'AbortError'
          ? 'Login verification timed out. Check that the backend is running, then try again.'
          : error.message || 'Your login could not be verified.');
      })
      .finally(() => window.clearTimeout(timeoutId));
    return () => {
      active = false;
      window.clearTimeout(timeoutId);
      controller.abort();
    };
  }, [authConfig.enabled, authConfigLoaded, authDisplayName, authToken]);

  useEffect(() => {
    if (!authUser) {
      setUserDataLoaded(false);
      setMonthlyTransactions({});
      setMonthlyIncome({});
      setMonthlyCredits({});
      setGoals([]);
      setLocation('');
      return;
    }
    if (hasAdminRole(authUser)) {
      setUserDataLoaded(true);
      return;
    }
    try {
      const transactionKey = userStorageKey(MONTHLY_TRANSACTIONS_STORAGE_KEY, authUser.sub);
      const incomeKey = userStorageKey(MONTHLY_INCOME_STORAGE_KEY, authUser.sub);
      const creditsKey = userStorageKey(MONTHLY_CREDITS_STORAGE_KEY, authUser.sub);
      const goalsKey = userStorageKey(GOALS_STORAGE_KEY, authUser.sub);
      const locationKey = userStorageKey(LOCATION_OVERRIDE_STORAGE_KEY, authUser.sub);
      setMonthlyTransactions(loadMonthlyTransactions(transactionKey));
      setMonthlyIncome(loadMonthlyIncome(incomeKey));
      setMonthlyCredits(loadMonthlyCredits(creditsKey));
      setGoals(loadGoals(goalsKey));
      setLocation(localStorage.getItem(locationKey) || '');
      setUserDataLoaded(true);
      fetchCurrentLocation();
    } catch (error) {
      setAuthError(error.message || 'Could not load this user’s saved finance data.');
      setUserDataLoaded(false);
    }
  }, [authUser]);

  useEffect(() => {
    if (!authUser || !userDataLoaded || isAdmin) return;
    localStorage.setItem(userStorageKey(GOALS_STORAGE_KEY, authUser.sub), JSON.stringify(goals));
  }, [authUser, goals, isAdmin, userDataLoaded]);

  const authenticatedFetch = async (url, options = {}) => {
    const headers = { ...(options.headers || {}) };
    if (authConfig.enabled && authToken) {
      headers.Authorization = `Bearer ${authToken}`;
    }
    if (!headers['Content-Type'] && options.body) {
      headers['Content-Type'] = 'application/json';
    }

    return fetch(url, {
      ...options,
      headers,
    });
  };

  const requestCurrencyConversion = async (amount, fromCurrency, toCurrency) => {
    const response = await fetch('/api/currency/convert', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        amount: Number(amount),
        from_currency: fromCurrency,
        to_currency: toCurrency,
      }),
    });
    const result = await response.json();
    if (!response.ok) {
      throw new Error(result.detail || 'Exchange rates are unavailable.');
    }
    return result.data;
  };

  const handleBudgetCurrencyChange = async (event) => {
    const nextCurrency = event.target.value;
    if (nextCurrency === currency) return;

    setCreditCurrencyChanging(true);
    setCreditError('');
    try {
      const sourceCurrencies = [...new Set(
        Object.values(monthlyCredits)
          .flat()
          .map((credit) => credit.currency || currency)
          .filter((sourceCurrency) => sourceCurrency !== nextCurrency),
      )];
      const conversions = await Promise.all(sourceCurrencies.map(async (sourceCurrency) => {
        const result = await requestCurrencyConversion(1, sourceCurrency, nextCurrency);
        return [sourceCurrency, result.converted_amount];
      }));
      const rates = new Map(conversions);
      setMonthlyCredits((previous) => Object.fromEntries(
        Object.entries(previous).map(([period, entries]) => [
          period,
          entries.map((credit) => {
            const sourceCurrency = credit.currency || currency;
            return {
              ...credit,
              converted_amount: sourceCurrency === nextCurrency
                ? credit.amount
                : Number(credit.amount) * rates.get(sourceCurrency),
              converted_currency: nextCurrency,
            };
          }),
        ]),
      ));
      setCurrency(nextCurrency);
      setConversionTo(nextCurrency);
      setCurrencyConversion(null);
      setTransactionDraft((previous) => ({
        ...previous,
        currency: previous.currency === currency ? nextCurrency : previous.currency,
      }));
      setCreditDraft((previous) => ({
        ...previous,
        currency: previous.currency === currency ? nextCurrency : previous.currency,
      }));
    } catch (error) {
      setCreditError(`Could not convert saved credits to ${nextCurrency}: ${error.message}`);
    } finally {
      setCreditCurrencyChanging(false);
    }
  };

  const handleCurrencyConvert = async (event) => {
    event.preventDefault();
    const amount = Number(conversionAmount);
    if (!Number.isFinite(amount) || amount <= 0) {
      setConversionError('Enter an amount greater than zero.');
      setCurrencyConversion(null);
      return;
    }

    setConversionLoading(true);
    setConversionError('');
    setCurrencyConversion(null);
    try {
      const result = await requestCurrencyConversion(amount, conversionFrom, conversionTo);
      setCurrencyConversion(result);
    } catch (error) {
      setConversionError(error.message);
    } finally {
      setConversionLoading(false);
    }
  };

  const handleAuthLogin = async () => {
    if (!authConfig.enabled || !authConfig.domain || !authConfig.client_id || !authConfig.audience) {
      setAuthError('Auth0 is not configured. Set the required Auth0 environment variables on the backend.');
      return;
    }

    try {
      const verifier = randomAuthValue();
      const state = randomAuthValue();
      const challenge = await createCodeChallenge(verifier);
      localStorage.setItem(AUTH_TRANSACTION_KEY, JSON.stringify({ verifier, state }));
      const domain = authConfig.domain.replace(/^https?:\/\//, '').replace(/\/+$/, '');
      const authorizeUrl = `https://${domain}/authorize?` + new URLSearchParams({
        response_type: 'code',
        client_id: authConfig.client_id,
        redirect_uri: window.location.origin,
        audience: authConfig.audience,
        scope: 'openid profile email',
        prompt: 'login',
        code_challenge: challenge,
        code_challenge_method: 'S256',
        state,
      }).toString();
      window.location.href = authorizeUrl;
    } catch (error) {
      setAuthError(error.message || 'Could not start Auth0 sign-in.');
    }
  };

  const handleAuthLogout = () => {
    setAuthToken('');
    setAuthDisplayName('');
    setAuthUsername('');
    setAuthEmail('');
    setAuthUser(null);
    localStorage.removeItem(AUTH_TRANSACTION_KEY);
    setUserDataLoaded(false);
    setMonthlyTransactions({});
    setMonthlyIncome({});
    setMonthlyCredits({});
    setGoals([]);
    if (authConfig.enabled && authConfig.domain && authConfig.client_id) {
      const returnTo = encodeURIComponent(window.location.origin);
      const domain = authConfig.domain.replace(/^https?:\/\//, '').replace(/\/+$/, '');
      window.location.href = `https://${domain}/v2/logout?client_id=${authConfig.client_id}&returnTo=${returnTo}`;
      return;
    }
    window.location.reload();
  };

  const analyzeBudget = async (currentGoals = goals, overrides = {}) => {
    if (isAdmin || authStatus !== 'authenticated' || !userDataLoaded) return;

    const requestId = ++analysisRequestId.current;
    setLoading(true);
    try {
      const activeGoal = currentGoals[0] || null;
      const response = await authenticatedFetch('/api/finance/analyze', {
        method: 'POST',
        body: JSON.stringify({
          income: overrides.availableBudget
            ?? (overrides.income ?? income) + creditIncome + carryForward,
          currency: overrides.currency ?? currency,
          location: overrides.location ?? getFinanceLocation(location, currentLocation) ?? '',
          transactions: overrides.transactions ?? transactions,
          goal_name: activeGoal?.name || null,
          goal_amount: activeGoal?.target || 0,
          goal_saved: activeGoal?.saved || 0,
        }),
      });

      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'Budget analysis failed.');
      }
      if (!result?.data) throw new Error('The advisor returned no budget analysis.');
      if (requestId !== analysisRequestId.current) return;

      setAnalysis(result.data);
      const analysisMessage = createChatEntry(
        'bot',
        buildBudgetHighlights(result.data),
        { kind: 'analysis' },
      );
      setChatHistory((previous) => {
        const lastMessage = previous[previous.length - 1];
        return lastMessage?.kind === 'analysis'
          ? [...previous.slice(0, -1), analysisMessage]
          : [...previous, analysisMessage];
      });
    } catch (error) {
      if (requestId !== analysisRequestId.current) return;
      appendChatMessage(
        'bot',
        error.message || 'The advisor is unavailable right now. Please try again in a moment.',
      );
    } finally {
      if (requestId === analysisRequestId.current) setLoading(false);
    }
  };

  useEffect(() => {
    if (isAdmin || authStatus !== 'authenticated' || !userDataLoaded) return undefined;
    const timerId = window.setTimeout(() => analyzeBudget(), 500);
    return () => window.clearTimeout(timerId);
  }, [authStatus, isAdmin, userDataLoaded, selectedPeriod, currency, income]);

  const handleAskAdvisor = async (event) => {
    event.preventDefault();
    const text = chatInput.trim();
    if (!text || chatProcessing) return;

    appendChatMessage('user', text);
    setChatInput('');

    if (authStatus !== 'authenticated') {
      appendChatMessage('bot', 'Sign in with Auth0 before requesting AI advice.');
      return;
    }

    setChatProcessing(true);
    try {
      const response = await authenticatedFetch('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          message: text,
          income: availableBudget,
          currency,
          location: getFinanceLocation(location, currentLocation),
          transactions,
          goals: goals[0] || undefined,
        }),
      });
      const result = await response.json();
      if (!response.ok) {
        throw new Error(result.detail || 'The advisor request failed.');
      }
      appendChatMessage('bot', result?.data?.reply || 'I can help with that budget suggestion.');
    } catch (error) {
      appendChatMessage('bot', error.message || 'The chat assistant could not respond at the moment.');
    } finally {
      setChatProcessing(false);
    }
  };

  const handleImportSpreadsheet = async (event) => {
    if (!canEditSelectedPeriod) {
      setImportError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    const file = event.target.files?.[0];
    if (!file) return;

    setImportError('');
    setImporting(true);
    try {
      const extension = file.name.split('.').pop()?.toLowerCase();
      const rows = extension === 'csv'
        ? parseCsv(await file.text())
        : extension === 'xlsx'
          ? await readSheet(file)
          : null;
      if (!rows) throw new Error('Choose a .csv or .xlsx file.');
      if (rows.length < 2) {
        throw new Error('The spreadsheet needs a header row and at least one expense row.');
      }

      const headers = rows[0].map(normalizeHeader);
      const records = rows.slice(1)
        .map((values, index) => ({
          rowNumber: index + 2,
          values,
          record: Object.fromEntries(headers.map((header, column) => [header, values[column] ?? ''])),
        }))
        .filter(({ values }) => values.some((value) => String(value ?? '').trim() !== ''));
      if (!records.length) throw new Error('No expense rows were found in the spreadsheet.');

      const fieldValue = (record, names) => {
        const key = names.find((name) => record[name] !== undefined && String(record[name]).trim() !== '');
        return key ? record[key] : '';
      };
      const imported = records.map(({ rowNumber, record }) => {
        const description = String(fieldValue(record, ['description', 'name', 'item', 'memo'])).trim();
        const amount = parseNumeric(fieldValue(record, ['amount', 'total', 'value', 'expense', 'cost']));
        const sourceCurrency = String(fieldValue(record, ['currency']) || currency).trim().toUpperCase();
        const category = String(fieldValue(record, ['category']) || 'Other').trim();
        const date = parseTransactionDate(fieldValue(record, ['date', 'transactiondate']), selectedPeriod);
        if (!description || !Number.isFinite(amount) || amount <= 0) {
          throw new Error(`Row ${rowNumber}: description and a positive amount are required.`);
        }
        if (!/^[A-Z]{3}$/.test(sourceCurrency)) {
          throw new Error(`Row ${rowNumber}: currency must be a three-letter code such as INR.`);
        }
        if (!date) {
          throw new Error(`Row ${rowNumber}: date must be a valid date, preferably YYYY-MM-DD.`);
        }
        return {
          id: createTransactionId(),
          description,
          amount,
          currency: sourceCurrency,
          category,
          date,
        };
      });

      const ratePromises = new Map();
      const converted = await Promise.all(imported.map(async (entry) => {
        if (entry.currency === currency) {
          return { ...entry, converted_amount: entry.amount, converted_currency: currency };
        }
        if (!ratePromises.has(entry.currency)) {
          ratePromises.set(
            entry.currency,
            requestCurrencyConversion(1, entry.currency, currency),
          );
        }
        const conversion = await ratePromises.get(entry.currency);
        return {
          ...entry,
          converted_amount: Math.round(entry.amount * conversion.rate * 100) / 100,
          converted_currency: currency,
        };
      }));

      const grouped = converted.reduce((groups, entry) => {
        const key = entry.date.slice(0, 7);
        groups[key] = [...(groups[key] || []), entry];
        return groups;
      }, {});
      setMonthlyTransactions((previous) => {
        const next = { ...previous };
        Object.entries(grouped).forEach(([key, entries]) => {
          next[key] = [...(previous[key] || []), ...entries];
        });
        return next;
      });
      if (grouped[selectedPeriod]) {
        analyzeBudget(goals, { transactions: [...transactions, ...grouped[selectedPeriod]] });
      }
      appendChatMessage(
        'bot',
        `Imported ${converted.length} expenses from ${file.name} across ${Object.keys(grouped).length} month(s).`,
      );
    } catch (error) {
      setImportError(error.message || 'The spreadsheet could not be imported.');
    } finally {
      event.target.value = '';
      setImporting(false);
    }
  };

  const handleDownloadCsvTemplate = () => {
    const rows = [
      ['Description', 'Category', 'Currency', 'Amount', 'Date'],
      ['Example expense - remove before upload', 'Food', currency, '250', `${selectedPeriod}-01`],
    ];
    const csv = `\uFEFF${rows.map((row) => row
      .map((value) => `"${String(value).replace(/"/g, '""')}"`)
      .join(',')).join('\r\n')}`;
    downloadBlob(new Blob([csv], { type: 'text/csv;charset=utf-8' }), 'monthly-spending-template.csv');
  };

  const handleDownloadExcelTemplate = async () => {
    try {
      const rows = [
        ['Description', 'Category', 'Currency', 'Amount', 'Date'],
        ['Example expense - remove before upload', 'Food', currency, 250, `${selectedPeriod}-01`],
      ];
      const blob = await writeExcelFile(rows).toBlob();
      downloadBlob(blob, 'monthly-spending-template.xlsx');
    } catch (error) {
      setImportError(error.message || 'The Excel template could not be created.');
    }
  };

  const handleAddTransaction = async (event) => {
    event.preventDefault();
    if (!canEditSelectedPeriod) {
      setTransactionError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    const description = transactionDraft.description.trim();
    const amount = Number(transactionDraft.amount);
    const date = transactionDraft.date || dateForPeriod(selectedPeriod);

    if (!description || !Number.isFinite(amount) || amount <= 0) {
      setTransactionError('Enter a description and an amount greater than zero.');
      return;
    }
    if (!date.startsWith(`${selectedPeriod}-`)) {
      setTransactionError('Choose a transaction date within the selected month.');
      return;
    }

    setTransactionSaving(true);
    setTransactionError('');
    let convertedAmount = amount;
    try {
      if (transactionDraft.currency !== currency) {
        const conversion = await requestCurrencyConversion(
          amount,
          transactionDraft.currency,
          currency,
        );
        convertedAmount = conversion.converted_amount;
      }
    } catch (error) {
      setTransactionError(
        `Could not convert this expense to ${currency}: ${error.message}`,
      );
      setTransactionSaving(false);
      return;
    }

    const nextTransactions = [
      ...transactions,
      {
        description,
        amount,
        category: transactionDraft.category,
        currency: transactionDraft.currency,
        converted_amount: convertedAmount,
        converted_currency: currency,
        date,
        id: createTransactionId(),
      },
    ];
    setTransactions(nextTransactions);
    setTransactionDraft({
      description: '',
      amount: '',
      category: 'Food',
      currency,
      date: dateForPeriod(selectedPeriod),
    });
    setTransactionError('');
    analyzeBudget(goals, { transactions: nextTransactions });
    setTransactionSaving(false);
  };

  const handleAddGoal = (event) => {
    event.preventDefault();
    if (!goalDraft.name.trim()) return;

    const newGoal = {
      name: goalDraft.name.trim(),
      target: Number(goalDraft.target || 0),
      saved: Number(goalDraft.saved || 0),
    };

    const updatedGoals = [...goals, newGoal];
    setGoals(updatedGoals);
    setGoalDraft({ name: '', target: '', saved: '' });
    appendChatMessage('bot', `Goal added: ${newGoal.name}.`);
    analyzeBudget(updatedGoals);
  };

  const handleRemoveGoal = (goalName) => {
    const nextGoals = goals.filter((goal) => goal.name !== goalName);
    setGoals(nextGoals);
    analyzeBudget(nextGoals);
  };

  const handleEditTransaction = (transaction) => {
    if (!canEditSelectedPeriod) {
      setTransactionError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    setEditingTransactionId(transaction.id);
    setEditingDraft({
      description: transaction.description,
      category: transaction.category || 'Other',
      currency: transaction.currency || currency,
      amount: String(transaction.amount),
    });
    setTransactionError('');
  };

  const handleSaveTransactionEdit = async (transactionId) => {
    if (!canEditSelectedPeriod) {
      setTransactionError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    if (!editingDraft) return;
    const description = editingDraft.description.trim();
    const amount = Number(editingDraft.amount);
    if (!description || !Number.isFinite(amount) || amount <= 0) {
      setTransactionError('Enter a description and an amount greater than zero.');
      return;
    }

    setTransactionSaving(true);
    setTransactionError('');
    try {
      const conversion = editingDraft.currency === currency
        ? { converted_amount: amount }
        : await requestCurrencyConversion(amount, editingDraft.currency, currency);
      const nextTransactions = transactions.map((entry) => (
        entry.id === transactionId
          ? {
            ...entry,
            description,
            category: editingDraft.category,
            currency: editingDraft.currency,
            amount,
            converted_amount: conversion.converted_amount,
            converted_currency: currency,
          }
          : entry
      ));
      setTransactions(nextTransactions);
      setEditingTransactionId(null);
      setEditingDraft(null);
      analyzeBudget(goals, { transactions: nextTransactions });
    } catch (error) {
      setTransactionError(`Could not update this expense: ${error.message}`);
    } finally {
      setTransactionSaving(false);
    }
  };

  const handleDeleteTransaction = (transactionId) => {
    if (!canDeleteSelectedPeriod) {
      setTransactionError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    if (!window.confirm('Delete this expense?')) return;
    const nextTransactions = transactions.filter((entry) => entry.id !== transactionId);
    setTransactions(nextTransactions);
    setEditingTransactionId(null);
    setEditingDraft(null);
    analyzeBudget(goals, { transactions: nextTransactions });
  };

  const handleAddCredit = async (event) => {
    event.preventDefault();
    if (!canEditSelectedPeriod) {
      setCreditError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    const source = creditDraft.source.trim();
    const amount = Number(creditDraft.amount);
    const date = creditDraft.date || dateForPeriod(selectedPeriod);

    if (!source || !Number.isFinite(amount) || amount <= 0) {
      setCreditError('Enter a credit source and an amount greater than zero.');
      return;
    }
    if (!date.startsWith(`${selectedPeriod}-`)) {
      setCreditError('Choose a date in the selected month.');
      return;
    }

    setCreditSaving(true);
    setCreditError('');
    try {
      const conversion = creditDraft.currency === currency
        ? { converted_amount: amount }
        : await requestCurrencyConversion(amount, creditDraft.currency, currency);
      const nextCredits = [
        ...credits,
        {
          amount,
          currency: creditDraft.currency,
          source,
          date,
          converted_amount: conversion.converted_amount,
          converted_currency: currency,
          id: createTransactionId(),
        },
      ];
      setCredits(nextCredits);
      setCreditDraft({ amount: '', currency, source: '', date: '' });
      setCreditError('');
      analyzeBudget(goals, {
        availableBudget: income + monthlyCreditTotal(nextCredits, currency) + carryForward,
      });
    } catch (error) {
      setCreditError(`Could not convert this credit to ${currency}: ${error.message}`);
    } finally {
      setCreditSaving(false);
    }
  };

  const handleEditCredit = (credit) => {
    if (!canEditSelectedPeriod) {
      setCreditError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    setEditingCreditId(credit.id);
    setEditingCreditDraft({
      amount: String(credit.amount),
      currency: credit.currency || currency,
      source: credit.source,
      date: credit.date || dateForPeriod(selectedPeriod),
    });
    setCreditError('');
  };

  const handleSaveCreditEdit = async (creditId) => {
    if (!canEditSelectedPeriod) {
      setCreditError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    if (!editingCreditDraft) return;
    const source = editingCreditDraft.source.trim();
    const amount = Number(editingCreditDraft.amount);
    const date = editingCreditDraft.date;
    if (!source || !Number.isFinite(amount) || amount <= 0) {
      setCreditError('Enter a credit source and an amount greater than zero.');
      return;
    }
    if (!date.startsWith(`${selectedPeriod}-`)) {
      setCreditError('Choose a date in the selected month.');
      return;
    }

    setCreditSaving(true);
    setCreditError('');
    try {
      const conversion = editingCreditDraft.currency === currency
        ? { converted_amount: amount }
        : await requestCurrencyConversion(amount, editingCreditDraft.currency, currency);
      const nextCredits = credits.map((entry) => (
        entry.id === creditId
          ? {
            ...entry,
            amount,
            currency: editingCreditDraft.currency,
            source,
            date,
            converted_amount: conversion.converted_amount,
            converted_currency: currency,
          }
          : entry
      ));
      setCredits(nextCredits);
      setEditingCreditId(null);
      setEditingCreditDraft(null);
      analyzeBudget(goals, {
        availableBudget: income + monthlyCreditTotal(nextCredits, currency) + carryForward,
      });
    } catch (error) {
      setCreditError(`Could not update this credit: ${error.message}`);
    } finally {
      setCreditSaving(false);
    }
  };

  const handleDeleteCredit = (creditId) => {
    if (!canDeleteSelectedPeriod) {
      setCreditError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    if (!window.confirm('Delete this credit?')) return;
    const nextCredits = credits.filter((entry) => entry.id !== creditId);
    setCredits(nextCredits);
    setEditingCreditId(null);
    setEditingCreditDraft(null);
    analyzeBudget(goals, {
      availableBudget: income + monthlyCreditTotal(nextCredits, currency) + carryForward,
    });
  };

  const handleClearAllTransactions = () => {
    if (!canClearSelectedPeriod) {
      setTransactionError(HISTORICAL_DATA_RESTRICTION_MESSAGE);
      return;
    }
    const selectedMonthLabel = new Date(selectedYear, selectedMonth - 1, 1)
      .toLocaleDateString('en', { month: 'long', year: 'numeric' });
    const confirmation = isAdmin
      ? 'Clear every expense and credit and reset saved carryovers? The selected month income will be kept.'
      : `Clear expenses and credits for ${selectedMonthLabel}? Other months and income will be kept.`;
    if (!window.confirm(confirmation)) return;
    if (isAdmin) {
      setMonthlyTransactions({});
      setMonthlyCredits({});
      setMonthlyIncome({ [selectedPeriod]: income });
    } else {
      setTransactions([]);
      setCredits([]);
    }
    setAnalysis(null);
    setEditingTransactionId(null);
    setEditingDraft(null);
    setEditingCreditId(null);
    setEditingCreditDraft(null);
    analyzeBudget(goals, {
      transactions: [],
      availableBudget: isAdmin ? income : income + carryForward,
    });
    appendChatMessage(
      'bot',
      isAdmin
        ? 'All expense and credit entries have been cleared.'
        : `Expenses and credits for ${selectedMonthLabel} have been cleared. Other months are unchanged.`,
    );
  };

  const totalGoalTarget = goals.reduce((sum, goal) => sum + Number(goal.target || 0), 0);
  const totalGoalSaved = goals.reduce((sum, goal) => sum + Number(goal.saved || 0), 0);
  const goalProgress = totalGoalTarget > 0 ? (totalGoalSaved / totalGoalTarget) * 100 : 0;
  const upcomingReminderAlerts = getUpcomingTransactions(monthlyTransactions, currentTime).map((transaction) => {
    const dueDate = transaction.date === formatLocalDate(currentTime)
      ? 'today'
      : `on ${new Date(`${transaction.date}T00:00:00`).toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
      })}`;
    const amount = formatCurrency(transaction.amount, transaction.currency || currency);
    return `Reminder: ${transaction.description} — ${amount} due ${dueDate}.`;
  });
  const alertMessages = [
    ...(analysis?.alerts || []),
    ...upcomingReminderAlerts,
  ];
  const localTime = currentTime.toLocaleTimeString('en-IN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const localDate = currentTime.toLocaleDateString('en-IN', {
    weekday: 'long',
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  });
  const timeZone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const currentYear = new Date().getFullYear();
  const availableYears = new Set(
    Array.from({ length: 7 }, (_, index) => currentYear - 5 + index),
  );
  Object.keys(monthlyTransactions).forEach((key) => availableYears.add(Number(key.slice(0, 4))));
  Object.keys(monthlyIncome).forEach((key) => availableYears.add(Number(key.slice(0, 4))));
  Object.keys(monthlyCredits).forEach((key) => availableYears.add(Number(key.slice(0, 4))));
  const yearOptions = Array.from(availableYears).sort((left, right) => right - left);
  const authConfigured = authConfig.enabled
    && authConfig.domain
    && authConfig.client_id
    && authConfig.audience;
  const authLogout = authConfigured ? handleAuthLogout : undefined;

  if (!authConfigLoaded || authStatus === 'checking') {
    return <AuthScreen loading configured={false} error="" onLogout={authLogout} />;
  }

  if (authStatus !== 'authenticated' || !authUser) {
    return (
      <AuthScreen
        configured={authConfigured}
        error={authError}
        onLogin={handleAuthLogin}
        onLogout={authLogout}
      />
    );
  }

  if (isAdmin) {
    return (
      <AdminDashboard
        authToken={authToken}
        authUser={authUser}
        profileEmail={authEmail || authUser.email}
        onLogout={handleAuthLogout}
      />
    );
  }

  if (!userDataLoaded) {
    return (
      <AuthScreen
        configured={authConfigured}
        error={authError || 'Your saved finance data could not be loaded.'}
        onLogout={authLogout}
      />
    );
  }

  const profileName = authUser.display_name || authUser.name || authDisplayName || 'Your account';
  const profileUsername = authUsername || authUser.username || authUser.email || authUser.sub;
  const profileEmail = authEmail || authUser.email || 'Email unavailable';
  const profileInitialParts = profileName.split(/[\s._-]+/).filter(Boolean);
  const profileInitials = (profileInitialParts.length > 1
    ? profileInitialParts.slice(0, 2).map((part) => part[0]).join('')
    : (profileInitialParts[0]?.slice(0, 2) || 'U').padEnd(
      2,
      profileInitialParts[0]?.[0] || 'U',
    )).toUpperCase();

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <img
            className="brand-logo"
            src="/personal-finance-logo.png"
            alt="Personal Finance & Budget Advisor"
          />
          <div>
            <h1>Personal Finance &amp; Budget Advisor</h1>
            <p>
              AI money adviser
              <img className="india-flag" src="/india-flag.svg" alt="Indian flag" />
              India
            </p>
          </div>
        </div>

        <div className="panel">
          <h3>Quick Snapshot</h3>
          <div className="stat-grid">
            <div>
              <span className="label">Income</span>
              <strong>{formatCurrency(totalIncome, currency)}</strong>
            </div>
            <div>
              <span className="label">Spend</span>
              <strong>{formatCurrency(summary.totalSpending, currency)}</strong>
            </div>
            <div>
              <span className="label">Savings</span>
              <strong>{summary.savingsRate.toFixed(0)}%</strong>
            </div>
            <div>
              <span className="label">Remaining</span>
              <strong>{formatCurrency(summary.remaining, currency)}</strong>
            </div>
          </div>
        </div>

        <div className="panel">
          <h3>Recommended Savings</h3>
          <strong className="recommended-savings-amount">
            {formatCurrency(totalIncome * 0.2, currency)}
          </strong>
          <p className="tiny-copy">20% of your total monthly income</p>
        </div>

        <div className="panel">
          <h3>Budget Inputs</h3>
          <label>
            Monthly income
            <input
              type="number"
              value={income}
              min="0"
              onChange={(event) => setIncome(Number(event.target.value || 0))}
            />
          </label>
          <label>
            Currency
            <select
              value={currency}
              onChange={handleBudgetCurrencyChange}
              disabled={creditCurrencyChanging}
            >
              {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
            </select>
          </label>
          <label>
            City override (optional)
            <input
              type="text"
              value={location}
              placeholder="e.g. Ahmedabad"
              onChange={(event) => {
                const nextLocation = event.target.value;
                setLocation(nextLocation);
                if (authUser) {
                  localStorage.setItem(
                    userStorageKey(LOCATION_OVERRIDE_STORAGE_KEY, authUser.sub),
                    nextLocation,
                  );
                }
              }}
            />
          </label>
          <button className="primary" type="button" onClick={() => analyzeBudget()} disabled={loading}>
            {loading ? 'Analyzing...' : 'Analyze spending'}
          </button>
        </div>

        <div className="panel">
          <h3>Other Credit Input</h3>
          <form className="credit-entry-form" onSubmit={handleAddCredit}>
            <label>
              Amount
              <input
                type="number"
                min="0.01"
                step="0.01"
                value={creditDraft.amount}
                onChange={(event) => setCreditDraft((previous) => ({
                  ...previous,
                  amount: event.target.value,
                }))}
                required
              />
            </label>
            <label>
              Currency
              <select
                value={creditDraft.currency}
                onChange={(event) => setCreditDraft((previous) => ({
                  ...previous,
                  currency: event.target.value,
                }))}
              >
                {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <label>
              Credit Source
              <input
                type="text"
                value={creditDraft.source}
                onChange={(event) => setCreditDraft((previous) => ({
                  ...previous,
                  source: event.target.value,
                }))}
                required
              />
            </label>
            <label>
              Date
              <input
                type="date"
                min={`${selectedPeriod}-01`}
                max={formatLocalDate(new Date(selectedYear, selectedMonth, 0))}
                value={creditDraft.date || dateForPeriod(selectedPeriod)}
                onChange={(event) => setCreditDraft((previous) => ({
                  ...previous,
                  date: event.target.value,
                }))}
                required
              />
            </label>
            {creditError && <p className="form-error" role="alert">{creditError}</p>}
            <button
              className="primary"
              type="submit"
              disabled={creditSaving || creditCurrencyChanging || !canEditSelectedPeriod}
              title={!canEditSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
            >
              {creditSaving || creditCurrencyChanging ? 'Converting…' : 'Add'}
            </button>
          </form>
        </div>

        <section className="card exchange-card">
          <div className="exchange-heading">
            <div>
              <h3>Currency converter</h3>
              <p className="tiny-copy">
                Convert international spending with the latest available ExchangeRate-API rates.
                The API key is optional; the backend uses its free no-key endpoint when unset.
              </p>
            </div>
            <span className="exchange-provider">ExchangeRate-API</span>
          </div>
          <form className="currency-converter-form" onSubmit={handleCurrencyConvert}>
            <label>
              Amount
              <input
                type="number"
                min="0.01"
                step="any"
                value={conversionAmount}
                onChange={(event) => {
                  setConversionAmount(event.target.value);
                  setCurrencyConversion(null);
                }}
                required
              />
            </label>
            <label>
              From
              <select
                value={conversionFrom}
                onChange={(event) => {
                  setConversionFrom(event.target.value);
                  setCurrencyConversion(null);
                }}
              >
                {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <label>
              To
              <select
                value={conversionTo}
                onChange={(event) => {
                  setConversionTo(event.target.value);
                  setCurrencyConversion(null);
                }}
              >
                {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <button className="primary" type="submit" disabled={conversionLoading}>
              {conversionLoading ? 'Fetching rate…' : 'Convert'}
            </button>
          </form>
          {conversionError && <p className="form-error" role="alert">{conversionError}</p>}
          {currencyConversion && (
            <div className="conversion-result" aria-live="polite">
              <strong>
                {formatCurrency(currencyConversion.amount, currencyConversion.from_currency)}
                {' = '}
                {formatCurrency(currencyConversion.converted_amount, currencyConversion.to_currency)}
              </strong>
              <span>
                1 {currencyConversion.from_currency} = {Number(currencyConversion.rate).toPrecision(6)} {currencyConversion.to_currency}
              </span>
            </div>
          )}
        </section>

        <div className="panel">
          <h3>Dashboard theme</h3>
          <label>
          Choose a style
          <select value={theme} onChange={(event) => setTheme(event.target.value)}>
            {themes.map((option) => (
              <option key={option.value} value={option.value}>{option.label}</option>
            ))}
          </select>
          </label>
          <p className="tiny-copy">Your theme is saved in this browser.</p>
        </div>
      </aside>

      <main className="main-panel">
        <section className="hero">
          <div>
            <p className="eyebrow">Finance assistant</p>
            <h2>AI-Powered Personal Finance Assistant</h2>
          </div>
          <div className="hero-actions">
            <details className="profile-menu">
              <summary className="profile-icon" aria-label="Open profile menu" title="Profile">
                <span aria-hidden="true">{profileInitials}</span>
              </summary>
              <div className="profile-popover">
                <div className="profile-field">
                  <span>Name</span>
                  <strong>{profileName}</strong>
                </div>
                <div className="profile-field">
                  <span>Email</span>
                  <strong>{profileEmail}</strong>
                </div>
                <div className="profile-field">
                  <span>Username</span>
                  <strong>{profileUsername}</strong>
                </div>
                <button
                  className="secondary"
                  type="button"
                  onClick={handleAuthLogout}
                >
                  Logout
                </button>
              </div>
            </details>
            <button
              className="secondary"
              type="button"
              onClick={() => {
                setIncome(50000);
                setCurrency('INR');
                setLocation('Mumbai');
                setTransactions(defaultTransactions.map((entry, index) => ({
                  ...entry,
                  id: `demo-${selectedPeriod}-${index}-${Date.now()}`,
                  date: dateForPeriod(selectedPeriod),
                })));
                setGoals(defaultGoals);
                analyzeBudget(defaultGoals, {
                  income: 50000,
                  currency: 'INR',
                  location: 'Mumbai',
                  transactions: defaultTransactions,
                });
              }}
            >
              Load demo data
            </button>
          </div>
        </section>

        <section className="card-grid dashboard-meta">
          <div className="meta-card">
            <div className="meta-icon" aria-hidden="true">⌖</div>
            <div className="meta-content">
              <span className="meta-label">Current city</span>
              <strong>
                {location.trim()
                  || (locationStatus === 'loading'
                  ? 'Detecting location…'
                  : currentLocation?.city || 'Location unavailable')}
              </strong>
              {location.trim() ? (
                <small>Using your selected city override.</small>
              ) : locationError ? (
                <small className="meta-error">{locationError}</small>
              ) : (
                <small>
                  {[
                    currentLocation?.locality !== currentLocation?.city ? currentLocation?.locality : null,
                    currentLocation?.region,
                    currentLocation?.country,
                  ].filter(Boolean).join(', ')
                    || 'City and region resolved from your device coordinates'}
                </small>
              )}
            </div>
            <button
              className="ghost-button"
              type="button"
              onClick={fetchCurrentLocation}
              disabled={locationStatus === 'loading'}
              aria-label="Refresh current location"
            >
              Refresh
            </button>
          </div>
          <div className="meta-card">
            <div className="meta-icon" aria-hidden="true">◷</div>
            <div className="meta-content" aria-live="off">
              <span className="meta-label">Local date &amp; time</span>
              <strong className="clock-time">{localTime}</strong>
              <small>{localDate} · {timeZone}</small>
            </div>
          </div>
        </section>

        <section className="card-grid">
          <div className="card">
            <h3>Budget recommendations</h3>
            <ul>
              {(analysis?.recommendations || [
                'Keep at least 20% of income for savings and emergency reserves.',
                'Review recurring subscriptions and informal daily spending to improve cash flow.',
              ]).map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>

          <div className="card">
            <h3>Alerts</h3>
            <ul>
              {alertMessages.length
                ? alertMessages.map((alert, index) => <li key={`${index}-${alert}`}>{alert}</li>)
                : <li>No alerts — spending looks balanced.</li>}
            </ul>
          </div>
        </section>

        <section className="card">
          <h3>Other Credits</h3>
          <p className="tiny-copy">Credits are included in this month’s income and available budget.</p>
          <div className="table-responsive">
            <table className="monthly-spending-table">
              <thead>
                <tr>
                  <th>Credit Source</th>
                  <th>Amount</th>
                  <th>Currency</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {credits.length ? credits.map((credit) => (
                  <tr key={credit.id}>
                    {editingCreditId === credit.id && editingCreditDraft ? (
                      <>
                        <td>
                          <input
                            aria-label="Edit credit source"
                            value={editingCreditDraft.source}
                            onChange={(event) => setEditingCreditDraft((previous) => ({
                              ...previous,
                              source: event.target.value,
                            }))}
                          />
                        </td>
                        <td>
                          <input
                            aria-label="Edit credit amount"
                            type="number"
                            min="0.01"
                            step="0.01"
                            value={editingCreditDraft.amount}
                            onChange={(event) => setEditingCreditDraft((previous) => ({
                              ...previous,
                              amount: event.target.value,
                            }))}
                          />
                        </td>
                        <td>
                          <select
                            aria-label="Edit credit currency"
                            value={editingCreditDraft.currency}
                            onChange={(event) => setEditingCreditDraft((previous) => ({
                              ...previous,
                              currency: event.target.value,
                            }))}
                          >
                            {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
                          </select>
                        </td>
                        <td>
                          <input
                            aria-label="Edit credit date"
                            type="date"
                            min={`${selectedPeriod}-01`}
                            max={formatLocalDate(new Date(selectedYear, selectedMonth, 0))}
                            value={editingCreditDraft.date}
                            onChange={(event) => setEditingCreditDraft((previous) => ({
                              ...previous,
                              date: event.target.value,
                            }))}
                          />
                        </td>
                        <td className="table-actions">
                          <button
                            className="primary"
                            type="button"
                            onClick={() => handleSaveCreditEdit(credit.id)}
                            disabled={creditSaving || !canEditSelectedPeriod}
                          >
                            Save
                          </button>
                          <button
                            className="ghost-button"
                            type="button"
                            onClick={() => {
                              setEditingCreditId(null);
                              setEditingCreditDraft(null);
                              setCreditError('');
                            }}
                          >
                            Cancel
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>{credit.source}</td>
                        <td>{formatCurrency(credit.amount, credit.currency || currency)}</td>
                        <td>{credit.currency || currency}</td>
                        <td>{credit.date || '—'}</td>
                        <td className="table-actions">
                          <button
                            className="secondary"
                            type="button"
                            onClick={() => handleEditCredit(credit)}
                            disabled={!canEditSelectedPeriod}
                            title={!canEditSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
                          >
                            Edit
                          </button>
                          <button
                            className="danger-button"
                            type="button"
                            onClick={() => handleDeleteCredit(credit.id)}
                            disabled={!canDeleteSelectedPeriod}
                            title={!canDeleteSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
                          >
                            Delete
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                )) : (
                  <tr>
                    <td colSpan="5" className="empty-table-message">No other credits for this month yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {creditError && <p className="form-error" role="alert">{creditError}</p>}
        </section>

        <section className="card">
          <h3>Add a manual expense</h3>
          <p className="tiny-copy">Expenses are added to the selected month and update the monthly table and category summary.</p>
          <form className="manual-entry-form" onSubmit={handleAddTransaction}>
            <label>
              Description
              <input
                type="text"
                placeholder="e.g. Electricity bill"
                value={transactionDraft.description}
                onChange={(event) => setTransactionDraft((previous) => ({
                  ...previous,
                  description: event.target.value,
                }))}
                required
              />
            </label>
            <label>
              Amount ({transactionDraft.currency})
              <input
                type="number"
                min="0.01"
                step="0.01"
                placeholder="0.00"
                value={transactionDraft.amount}
                onChange={(event) => setTransactionDraft((previous) => ({
                  ...previous,
                  amount: event.target.value,
                }))}
                required
              />
            </label>
            <label>
              Date
              <input
                type="date"
                min={`${selectedPeriod}-01`}
                max={formatLocalDate(new Date(selectedYear, selectedMonth, 0))}
                value={transactionDraft.date || dateForPeriod(selectedPeriod)}
                onChange={(event) => setTransactionDraft((previous) => ({
                  ...previous,
                  date: event.target.value,
                }))}
                required
              />
            </label>
            <label>
              Transaction currency
              <select
                value={transactionDraft.currency}
                onChange={(event) => setTransactionDraft((previous) => ({
                  ...previous,
                  currency: event.target.value,
                }))}
              >
                {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
              </select>
            </label>
            <label>
              Category
              <select
                value={transactionDraft.category}
                onChange={(event) => setTransactionDraft((previous) => ({
                  ...previous,
                  category: event.target.value,
                }))}
              >
                {expenseCategories.map((category) => <option key={category} value={category}>{category}</option>)}
              </select>
            </label>
            {transactionError && <p className="form-error" role="alert">{transactionError}</p>}
            <button
              className="primary"
              type="submit"
              disabled={transactionSaving || !canEditSelectedPeriod}
              title={!canEditSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
            >
              {transactionSaving ? 'Converting…' : 'Add expense'}
            </button>
          </form>
        </section>

        <section className="card monthly-spending-card">
          <div className="monthly-spending-header">
            <div>
              <h3>Monthly Spending</h3>
              <p className="tiny-copy">Import a CSV or Excel file, or add expenses manually. Entries are saved by transaction date.</p>
            </div>
            <div className={`monthly-spending-actions${canEditSelectedPeriod ? '' : ' monthly-spending-actions-readonly'}`}>
              {canEditSelectedPeriod && (
                <label className="upload-label">
                  {importing ? 'Importing…' : 'Import CSV / Excel'}
                  <input
                    type="file"
                    accept=".csv,text/csv,.xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    onChange={handleImportSpreadsheet}
                    disabled={importing}
                  />
                </label>
              )}
              <button className="secondary" type="button" onClick={handleDownloadCsvTemplate}>
                Download CSV
              </button>
              <button className="secondary" type="button" onClick={handleDownloadExcelTemplate}>
                Download Excel
              </button>
              <button
                className="danger-button"
                type="button"
                onClick={handleClearAllTransactions}
                disabled={!canClearSelectedPeriod}
                title={!canClearSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
              >
                Clear data
              </button>
            </div>
          </div>

          <div className="monthly-period-toolbar">
            <label>
              Month
              <select value={selectedMonth} onChange={(event) => setSelectedMonth(Number(event.target.value))}>
                {Array.from({ length: 12 }, (_, index) => index + 1).map((month) => (
                  <option key={month} value={month}>
                    {new Intl.DateTimeFormat('en', { month: 'long' }).format(new Date(selectedYear, month - 1, 1))}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Year
              <select value={selectedYear} onChange={(event) => setSelectedYear(Number(event.target.value))}>
                {yearOptions.map((year) => <option key={year} value={year}>{year}</option>)}
              </select>
            </label>
            <p className="carry-forward-note">
              Budget available: <strong>{formatCurrency(availableBudget, currency)}</strong>
              {' · Previous month savings: '}
              <strong>{formatCurrency(carryForward, currency)}</strong>
            </p>
          </div>

          {importError && <p className="form-error" role="alert">{importError}</p>}
          <p className="tiny-copy">Template columns: Description, Category, Currency, Amount, Date. Use a three-letter currency code and YYYY-MM-DD dates; remove the example row before uploading.</p>
          <div className="table-responsive">
            <table className="monthly-spending-table">
              <thead>
                <tr>
                  <th>Description</th>
                  <th>Category</th>
                  <th>Currency</th>
                  <th>Amount</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {transactions.length ? transactions.map((transaction) => (
                  <tr key={transaction.id}>
                    {editingTransactionId === transaction.id && editingDraft ? (
                      <>
                        <td>
                          <input
                            aria-label="Edit description"
                            value={editingDraft.description}
                            onChange={(event) => setEditingDraft((previous) => ({
                              ...previous,
                              description: event.target.value,
                            }))}
                          />
                        </td>
                        <td>
                          <select
                            aria-label="Edit category"
                            value={editingDraft.category}
                            onChange={(event) => setEditingDraft((previous) => ({
                              ...previous,
                              category: event.target.value,
                            }))}
                          >
                            {!expenseCategories.includes(editingDraft.category) && (
                              <option value={editingDraft.category}>{editingDraft.category}</option>
                            )}
                            {expenseCategories.map((category) => <option key={category} value={category}>{category}</option>)}
                          </select>
                        </td>
                        <td>
                          <select
                            aria-label="Edit currency"
                            value={editingDraft.currency}
                            onChange={(event) => setEditingDraft((previous) => ({
                              ...previous,
                              currency: event.target.value,
                            }))}
                          >
                            {!currencies.includes(editingDraft.currency) && (
                              <option value={editingDraft.currency}>{editingDraft.currency}</option>
                            )}
                            {currencies.map((code) => <option key={code} value={code}>{code}</option>)}
                          </select>
                        </td>
                        <td>
                          <input
                            aria-label="Edit amount"
                            type="number"
                            min="0.01"
                            step="0.01"
                            value={editingDraft.amount}
                            onChange={(event) => setEditingDraft((previous) => ({
                              ...previous,
                              amount: event.target.value,
                            }))}
                          />
                        </td>
                        <td>{transaction.date}</td>
                        <td className="table-actions">
                          <button
                            className="primary"
                            type="button"
                            onClick={() => handleSaveTransactionEdit(transaction.id)}
                            disabled={transactionSaving || !canEditSelectedPeriod}
                          >
                            Save
                          </button>
                          <button
                            className="ghost-button"
                            type="button"
                            onClick={() => {
                              setEditingTransactionId(null);
                              setEditingDraft(null);
                              setTransactionError('');
                            }}
                          >
                            Cancel
                          </button>
                        </td>
                      </>
                    ) : (
                      <>
                        <td>{transaction.description}</td>
                        <td>{transaction.category || 'Other'}</td>
                        <td>{transaction.currency || currency}</td>
                        <td>{formatCurrency(transaction.amount, transaction.currency || currency)}</td>
                        <td>{transaction.date || '—'}</td>
                        <td className="table-actions">
                          <button
                            className="secondary"
                            type="button"
                            onClick={() => handleEditTransaction(transaction)}
                            disabled={!canEditSelectedPeriod}
                            title={!canEditSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
                          >
                            Edit
                          </button>
                          <button
                            className="danger-button"
                            type="button"
                            onClick={() => handleDeleteTransaction(transaction.id)}
                            disabled={!canDeleteSelectedPeriod}
                            title={!canDeleteSelectedPeriod ? HISTORICAL_DATA_RESTRICTION_MESSAGE : undefined}
                          >
                            Delete
                          </button>
                        </td>
                      </>
                    )}
                  </tr>
                )) : (
                  <tr>
                    <td colSpan="6" className="empty-table-message">No expenses for this month yet.</td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {transactionError && <p className="form-error" role="alert">{transactionError}</p>}
        </section>

        <section className="card">
          <h3>Category breakdown</h3>
          <p className="tiny-copy">Summary of the expenses listed above for {new Date(selectedYear, selectedMonth - 1, 1).toLocaleDateString('en', { month: 'long', year: 'numeric' })}.</p>
          <div className="category-breakdown">
            {Object.entries(categorySummary).length > 0 ? (
              Object.entries(categorySummary).map(([name, value]) => {
                const width = Math.max((Number(value) / Math.max(...Object.values(categorySummary), 1)) * 100, 6);
                return (
                  <div className="category-row" key={name}>
                    <span>{name}</span>
                    <div className="progress-bar"><span className="progress-fill" style={{ width: `${width}%` }} /></div>
                    <strong>{formatCurrency(value, currency)}</strong>
                  </div>
                );
              })
            ) : (
              <p>No categorized expenses for this month.</p>
            )}
          </div>
        </section>

        <section className="card-grid">
          <div className="card goals-card">
            <h3>Goal progress</h3>
            <div className="goal-total">
              <span>Total saved</span>
              <strong>{formatCurrency(totalGoalSaved, currency)} / {formatCurrency(totalGoalTarget, currency)}</strong>
            </div>
            <div className="progress-bar large"><span className="progress-fill" style={{ width: `${Math.min(goalProgress, 100)}%` }} /></div>
            <div className="goal-list">
              {goals.map((goal) => {
                const progress = goal.target > 0 ? (goal.saved / goal.target) * 100 : 0;
                return (
                  <div key={`${goal.name}-${goal.target}`} className="goal-item">
                    <div className="goal-header">
                      <strong>{goal.name}</strong>
                      <button className="ghost-button" type="button" onClick={() => handleRemoveGoal(goal.name)}>Remove</button>
                    </div>
                    <div className="goal-meta">
                      <span>{formatCurrency(goal.saved, currency)} saved</span>
                      <span>{progress.toFixed(0)}%</span>
                    </div>
                    <div className="progress-bar"><span className="progress-fill" style={{ width: `${Math.min(progress, 100)}%` }} /></div>
                  </div>
                );
              })}
            </div>

            <form className="goal-form" onSubmit={handleAddGoal}>
              <input
                type="text"
                placeholder="Goal name"
                value={goalDraft.name}
                onChange={(event) => setGoalDraft((prev) => ({ ...prev, name: event.target.value }))}
              />
              <div className="goal-fields">
                <input
                  type="number"
                  placeholder="Target"
                  value={goalDraft.target}
                  min="0"
                  onChange={(event) => setGoalDraft((prev) => ({ ...prev, target: event.target.value }))}
                />
                <input
                  type="number"
                  placeholder="Saved"
                  value={goalDraft.saved}
                  min="0"
                  onChange={(event) => setGoalDraft((prev) => ({ ...prev, saved: event.target.value }))}
                />
              </div>
              <button className="primary" type="submit">Add goal</button>
            </form>
          </div>

          <div className="card">
            <h3>Recent transactions</h3>
            <ul className="transaction-list">
              {transactions.slice(-6).reverse().map((transaction) => (
                <li key={transaction.id}>
                  <span>
                    {transaction.description}
                    {transaction.converted_currency && transaction.currency !== transaction.converted_currency && (
                      <small className="transaction-converted">
                        Budget amount: {formatCurrency(transaction.converted_amount, transaction.converted_currency)}
                      </small>
                    )}
                  </span>
                  <strong>{formatCurrency(transaction.amount, transaction.currency || currency)}</strong>
                </li>
              ))}
              {!transactions.length && <li>No recent expenses for this month.</li>}
            </ul>
          </div>
        </section>

        <section className="chat-panel">
          <h3>Ask the Advisor</h3>
          <div className="chat-messages" ref={chatMessagesRef}>
            {chatHistory.map((entry, index) => (
              <div key={`${entry.sender}-${index}`} className={`chat-bubble ${entry.sender}`}>
                <div>{entry.text}</div>
                <time className="chat-timestamp" dateTime={entry.timestamp}>
                  {new Date(entry.timestamp).toLocaleTimeString([], {
                    hour: 'numeric',
                    minute: '2-digit',
                  })}
                </time>
              </div>
            ))}
            {chatProcessing && (
              <div className="chat-bubble bot chat-thinking" role="status" aria-live="polite">
                <span className="thinking-dots" aria-hidden="true"><i /><i /><i /></span>
                Wait for Advisor response..
              </div>
            )}
          </div>
          <form onSubmit={handleAskAdvisor} className="chat-form">
            <input
              type="text"
              placeholder="Ask about expenses, goals, or savings..."
              value={chatInput}
              disabled={chatProcessing}
              onChange={(event) => setChatInput(event.target.value)}
            />
            <button type="submit" className="primary" disabled={chatProcessing}>Send</button>
          </form>
        </section>
      </main>
    </div>
  );
}

export default App;
