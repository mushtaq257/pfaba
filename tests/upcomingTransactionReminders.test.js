import assert from 'node:assert/strict';
import test from 'node:test';

import { getUpcomingTransactions } from '../src/upcomingTransactionReminders.js';

test('returns transactions due today through seven days ahead, sorted by due date', () => {
  const now = new Date(2026, 10, 12, 14);
  const transactionsByMonth = {
    '2026-11': [
      { description: 'Due in a week', date: '2026-11-19' },
      { description: 'Already passed', date: '2026-11-11' },
      { description: 'Due today', date: '2026-11-12' },
      { description: 'Outside reminder window', date: '2026-11-20' },
      { description: 'Invalid date', date: '2026-11-32' },
      { description: 'Unformatted date', date: '11/12/2026' },
      { description: 'Missing date' },
    ],
  };

  const reminders = getUpcomingTransactions(transactionsByMonth, now);

  assert.deepEqual(
    reminders.map((transaction) => transaction.description),
    ['Due today', 'Due in a week'],
  );
});
