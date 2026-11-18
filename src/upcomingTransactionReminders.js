function formatLocalDate(date) {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  return `${year}-${month}-${day}`;
}

export function getUpcomingTransactions(transactionsByMonth, now = new Date(), daysAhead = 7) {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const reminderEnd = new Date(today);
  reminderEnd.setDate(reminderEnd.getDate() + daysAhead);
  const todayKey = formatLocalDate(today);
  const reminderEndKey = formatLocalDate(reminderEnd);

  return Object.values(transactionsByMonth)
    .flat()
    .filter((transaction) => {
      if (typeof transaction.date !== 'string' || !/^\d{4}-\d{2}-\d{2}$/.test(transaction.date)) {
        return false;
      }
      const date = new Date(`${transaction.date}T00:00:00`);
      return (
        !Number.isNaN(date.getTime())
        && formatLocalDate(date) === transaction.date
        && transaction.date >= todayKey
        && transaction.date <= reminderEndKey
      );
    })
    .sort((left, right) => left.date.localeCompare(right.date));
}
