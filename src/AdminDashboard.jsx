import { useEffect, useState } from 'react';

const EMPTY_PERMISSIONS = {
  can_edit_previous_month: false,
  can_delete_previous_month: false,
  can_clear_previous_month: false,
};

function initialsFor(name) {
  const parts = String(name || 'Admin').split(/[\s._-]+/).filter(Boolean);
  if (parts.length > 1) return parts.slice(0, 2).map((part) => part[0]).join('').toUpperCase();
  return (parts[0]?.slice(0, 2) || 'AD').padEnd(2, parts[0]?.[0] || 'D').toUpperCase();
}

function displayDate(value) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? String(value) : date.toLocaleString();
}

export default function AdminDashboard({
  authToken,
  authUser,
  profileEmail,
  onLogout,
}) {
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busyUserId, setBusyUserId] = useState('');
  const [passwordUserId, setPasswordUserId] = useState('');
  const [passwordDraft, setPasswordDraft] = useState('');
  const [passwordConfirmation, setPasswordConfirmation] = useState('');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [creatingUser, setCreatingUser] = useState(false);
  const [newUser, setNewUser] = useState({
    name: '',
    email: '',
    username: '',
    password: '',
    passwordConfirmation: '',
    connection: '',
  });
  const [showAuditLog, setShowAuditLog] = useState(false);
  const [auditLogs, setAuditLogs] = useState([]);
  const [auditLogLoading, setAuditLogLoading] = useState(false);
  const [auditLogError, setAuditLogError] = useState('');

  const databaseConnections = [...new Set(
    users.flatMap((user) => user.database_connections || []),
  )].sort();

  useEffect(() => {
    const controller = new AbortController();
    let active = true;
    const loadUsers = async () => {
      try {
        const response = await fetch('/api/admin/users', {
          headers: { Authorization: `Bearer ${authToken}` },
          signal: controller.signal,
        });
        const result = await response.json();
        if (!response.ok) throw new Error(result.detail || 'Could not load users.');
        if (!Array.isArray(result?.data?.users)) {
          throw new Error('The server returned an invalid user list.');
        }
        if (active) setUsers(result.data.users);
      } catch (loadError) {
        if (active && loadError.name !== 'AbortError') {
          setError(loadError.message || 'Could not load users.');
        }
      } finally {
        if (active) setLoading(false);
      }
    };
    loadUsers();
    return () => {
      active = false;
      controller.abort();
    };
  }, [authToken]);

  const sendAdminRequest = async (url, method, body) => {
    const response = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${authToken}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || 'The user update failed.');
    return result.data;
  };

  const changeUserStatus = async (user) => {
    if (user.user_id === authUser.sub) return;
    setBusyUserId(user.user_id);
    setError('');
    setNotice('');
    try {
      const result = await sendAdminRequest(
        `/api/admin/users/${encodeURIComponent(user.user_id)}/status`,
        'PATCH',
        { enabled: user.blocked },
      );
      setUsers((previous) => previous.map((entry) => (
        entry.user_id === user.user_id
          ? {
            ...entry,
            blocked: !result.enabled,
            status: result.enabled ? 'Active' : 'Disabled',
          }
          : entry
      )));
      setNotice(`${user.email || user.user_id} is now ${result.enabled ? 'active' : 'disabled'}.`);
    } catch (requestError) {
      setError(requestError.message || 'Could not update the user status.');
    } finally {
      setBusyUserId('');
    }
  };

  const updatePermissions = async (user, permission, enabled) => {
    if (user.user_id === authUser.sub) return;
    const permissions = {
      ...EMPTY_PERMISSIONS,
      ...(user.historical_permissions || {}),
      [permission]: enabled,
    };
    setBusyUserId(user.user_id);
    setError('');
    setNotice('');
    try {
      const result = await sendAdminRequest(
        `/api/admin/users/${encodeURIComponent(user.user_id)}/historical-permissions`,
        'PATCH',
        permissions,
      );
      setUsers((previous) => previous.map((entry) => (
        entry.user_id === user.user_id
          ? { ...entry, historical_permissions: result.historical_permissions }
          : entry
      )));
      setNotice(`Historical permissions updated for ${user.email || user.user_id}.`);
    } catch (requestError) {
      setError(requestError.message || 'Could not update historical permissions.');
    } finally {
      setBusyUserId('');
    }
  };

  const submitPassword = async (event, user) => {
    event.preventDefault();
    setError('');
    setNotice('');
    if (passwordDraft !== passwordConfirmation) {
      setError('The password and confirmation do not match.');
      return;
    }
    if (passwordDraft.length < 8) {
      setError('The password must contain at least 8 characters.');
      return;
    }

    setBusyUserId(user.user_id);
    try {
      await sendAdminRequest(
        `/api/admin/users/${encodeURIComponent(user.user_id)}/password`,
        'PATCH',
        { password: passwordDraft },
      );
      setPasswordDraft('');
      setPasswordConfirmation('');
      setPasswordUserId('');
      setNotice(`Password updated for ${user.email || user.user_id}.`);
    } catch (requestError) {
      setError(requestError.message || 'Could not update the password.');
    } finally {
      setBusyUserId('');
    }
  };

  const submitCreateUser = async (event) => {
    event.preventDefault();
    setError('');
    setNotice('');
    if (newUser.password !== newUser.passwordConfirmation) {
      setError('The password and confirmation do not match.');
      return;
    }

    const connection = newUser.connection || databaseConnections[0] || '';
    if (!connection.trim()) {
      setError('Choose an Auth0 database connection before creating the user.');
      return;
    }

    setCreatingUser(true);
    try {
      const result = await sendAdminRequest('/api/admin/users', 'POST', {
        name: newUser.name.trim(),
        email: newUser.email.trim(),
        username: newUser.username.trim() || null,
        password: newUser.password,
        connection: connection.trim(),
      });
      const createdUser = {
        ...result.user,
        historical_permissions: EMPTY_PERMISSIONS,
      };
      setUsers((previous) => [
        createdUser,
        ...previous.filter((user) => user.user_id !== createdUser.user_id),
      ]);
      setNewUser({
        name: '',
        email: '',
        username: '',
        password: '',
        passwordConfirmation: '',
        connection: '',
      });
      setShowCreateForm(false);
      setNotice(`Created user ${createdUser.email || createdUser.user_id}.`);
    } catch (requestError) {
      setError(requestError.message || 'Could not create the user.');
    } finally {
      setCreatingUser(false);
    }
  };

  const deleteUser = async (user) => {
    if (user.user_id === authUser.sub) return;
    if (!window.confirm(`Permanently delete ${user.email || user.user_id}?`)) return;
    setBusyUserId(user.user_id);
    setError('');
    setNotice('');
    try {
      await sendAdminRequest(
        `/api/admin/users/${encodeURIComponent(user.user_id)}`,
        'DELETE',
      );
      setUsers((previous) => previous.filter((entry) => entry.user_id !== user.user_id));
      setNotice(`Deleted user ${user.email || user.user_id}.`);
    } catch (requestError) {
      setError(requestError.message || 'Could not delete the user.');
    } finally {
      setBusyUserId('');
    }
  };

  const openAuditLog = async () => {
    setShowAuditLog(true);
    setAuditLogLoading(true);
    setAuditLogError('');
    try {
      const result = await sendAdminRequest('/api/admin/audit-log', 'GET');
      if (!Array.isArray(result?.logs)) {
        throw new Error('The server returned an invalid audit log.');
      }
      setAuditLogs(result.logs);
    } catch (requestError) {
      setAuditLogError(requestError.message || 'Could not load the application log.');
    } finally {
      setAuditLogLoading(false);
    }
  };

  const profileName = authUser.display_name || authUser.name || 'Administrator';
  const username = authUser.username || authUser.sub;

  return (
    <main className="admin-console">
      <header className="admin-topbar">
        <div className="admin-brand">
          <img
            className="admin-brand-logo"
            src="/personal-finance-logo.png"
            alt="Personal Finance & Budget Advisor"
          />
          <div>
            <h1>Personal Finance &amp; Budget Advisor</h1>
            <p>
              AI money adviser
              <img src="/india-flag.svg" alt="Indian flag" />
              India
            </p>
          </div>
        </div>
        <div className="admin-banner">
          <p className="eyebrow">Finance Assistant</p>
          <h2>AI-Powered Personal Finance Assistant</h2>
        </div>
        <details className="profile-menu">
          <summary className="profile-icon" aria-label="Open profile menu" title="Profile">
            <span aria-hidden="true">{initialsFor(profileName)}</span>
          </summary>
          <div className="profile-popover">
            <div className="profile-field">
              <span>Name</span>
              <strong>{profileName}</strong>
            </div>
            <div className="profile-field">
              <span>Email</span>
              <strong>{profileEmail || 'Email unavailable'}</strong>
            </div>
            <div className="profile-field">
              <span>Username</span>
              <strong>{username}</strong>
            </div>
            <button
              className="ghost-button"
              type="button"
              onClick={(event) => {
                const profileMenu = event.currentTarget.closest('details');
                if (profileMenu) profileMenu.open = false;
                openAuditLog();
              }}
            >
              System / activity log
            </button>
            <button className="secondary" type="button" onClick={onLogout}>
              Logout
            </button>
          </div>
        </details>
      </header>

      <section className="admin-page-heading">
        <div>
          <p className="eyebrow">Administration</p>
          <h2>User Management</h2>
          <p className="admin-tagline">
            Manage accounts, credentials, and historical data access.
          </p>
        </div>
      </section>

      <section className="card admin-users-card">
        <div className="admin-users-heading">
          <div>
            <h2>Users</h2>
            <p className="tiny-copy">
              {loading ? 'Loading Auth0 users…' : `${users.length} user${users.length === 1 ? '' : 's'}`}
            </p>
          </div>
          <button
            className="primary admin-create-toggle"
            type="button"
            onClick={() => {
              setShowCreateForm((open) => !open);
              setError('');
            }}
          >
            {showCreateForm ? 'Cancel' : 'Create user'}
          </button>
        </div>

        {error && <p className="form-error" role="alert">{error}</p>}
        {notice && <p className="admin-notice" role="status">{notice}</p>}

        {showCreateForm && (
          <form className="admin-create-form" onSubmit={submitCreateUser}>
            <h3>Create an Auth0 database user</h3>
            <div className="admin-create-grid">
              <label>
                Name
                <input
                  type="text"
                  autoComplete="name"
                  maxLength="128"
                  value={newUser.name}
                  onChange={(event) => setNewUser({ ...newUser, name: event.target.value })}
                  required
                />
              </label>
              <label>
                Email
                <input
                  type="email"
                  autoComplete="email"
                  maxLength="254"
                  value={newUser.email}
                  onChange={(event) => setNewUser({ ...newUser, email: event.target.value })}
                  required
                />
              </label>
              <label>
                Username <span className="tiny-copy">(optional)</span>
                <input
                  type="text"
                  autoComplete="username"
                  maxLength="128"
                  value={newUser.username}
                  onChange={(event) => setNewUser({ ...newUser, username: event.target.value })}
                />
              </label>
              <label>
                Database connection
                {databaseConnections.length > 0 ? (
                  <select
                    value={newUser.connection || databaseConnections[0]}
                    onChange={(event) => setNewUser({ ...newUser, connection: event.target.value })}
                    required
                  >
                    {databaseConnections.map((connection) => (
                      <option key={connection} value={connection}>{connection}</option>
                    ))}
                  </select>
                ) : (
                  <input
                    type="text"
                    value={newUser.connection}
                    onChange={(event) => setNewUser({ ...newUser, connection: event.target.value })}
                    placeholder="Auth0 database connection name"
                    required
                  />
                )}
              </label>
              <label>
                Password
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength="8"
                  maxLength="128"
                  value={newUser.password}
                  onChange={(event) => setNewUser({ ...newUser, password: event.target.value })}
                  required
                />
              </label>
              <label>
                Confirm password
                <input
                  type="password"
                  autoComplete="new-password"
                  minLength="8"
                  maxLength="128"
                  value={newUser.passwordConfirmation}
                  onChange={(event) => setNewUser({
                    ...newUser,
                    passwordConfirmation: event.target.value,
                  })}
                  required
                />
              </label>
            </div>
            <div className="admin-create-actions">
              <button className="primary" type="submit" disabled={creatingUser}>
                {creatingUser ? 'Creating…' : 'Create user'}
              </button>
              <button
                className="secondary"
                type="button"
                onClick={() => setShowCreateForm(false)}
                disabled={creatingUser}
              >
                Cancel
              </button>
            </div>
          </form>
        )}

        {!loading && !error && users.length === 0 ? (
          <p className="tiny-copy">No Auth0 users were found.</p>
        ) : null}

        {users.length > 0 && (
          <div className="admin-users-scroll">
            <table className="admin-user-table">
              <thead>
                <tr>
                  <th>Name / User ID</th>
                  <th>Username</th>
                  <th>Email</th>
                  <th>Status</th>
                  <th>Created</th>
                  <th>Last login / Count</th>
                  <th>Connections</th>
                  <th>Historical access</th>
                  <th>User controls</th>
                </tr>
              </thead>
              <tbody>
                {users.map((user) => {
                  const permissions = {
                    ...EMPTY_PERMISSIONS,
                    ...(user.historical_permissions || {}),
                  };
                  const busy = busyUserId === user.user_id;
                  const isCurrentAdmin = user.user_id === authUser.sub;
                  return (
                    <tr key={user.user_id}>
                      <td>
                        <strong>{user.name || 'Unnamed user'}</strong>
                        <small className="admin-user-id">{user.user_id}</small>
                        {isCurrentAdmin && <small className="admin-self-note">Signed-in admin</small>}
                      </td>
                      <td>{user.username || '—'}</td>
                      <td>
                        {user.email || '—'}
                        <small>{user.email ? (user.email_verified ? 'Verified' : 'Not verified') : ''}</small>
                      </td>
                      <td>
                        <span className={`admin-status ${user.blocked ? 'is-disabled' : 'is-active'}`}>
                          {user.status}
                        </span>
                        <button
                          className="secondary admin-row-action"
                          type="button"
                          onClick={() => changeUserStatus(user)}
                          disabled={busy || isCurrentAdmin}
                          title={isCurrentAdmin ? 'You cannot disable the signed-in admin account.' : undefined}
                        >
                          {user.blocked ? 'Enable' : 'Disable'}
                        </button>
                      </td>
                      <td>{displayDate(user.created_at)}</td>
                      <td>
                        {displayDate(user.last_login)}
                        <small>{Number(user.logins_count || 0)} sign-ins</small>
                      </td>
                      <td>{user.connections?.join(', ') || '—'}</td>
                      <td>
                        {isCurrentAdmin ? (
                          <span className="admin-self-note">Not applicable</span>
                        ) : (
                          <div className="admin-permission-options">
                            <label>
                              <input
                                type="checkbox"
                                checked={permissions.can_edit_previous_month}
                                disabled={busy}
                                onChange={(event) => updatePermissions(
                                  user,
                                  'can_edit_previous_month',
                                  event.target.checked,
                                )}
                              />
                              Edit / update
                            </label>
                            <label>
                              <input
                                type="checkbox"
                                checked={permissions.can_delete_previous_month}
                                disabled={busy}
                                onChange={(event) => updatePermissions(
                                  user,
                                  'can_delete_previous_month',
                                  event.target.checked,
                                )}
                              />
                              Delete
                            </label>
                            <label>
                              <input
                                type="checkbox"
                                checked={permissions.can_clear_previous_month}
                                disabled={busy}
                                onChange={(event) => updatePermissions(
                                  user,
                                  'can_clear_previous_month',
                                  event.target.checked,
                                )}
                              />
                              Clear
                            </label>
                          </div>
                        )}
                      </td>
                      <td>
                        <div className="admin-user-controls">
                          <button
                            className="ghost-button"
                            type="button"
                            onClick={() => {
                              setPasswordUserId(passwordUserId === user.user_id ? '' : user.user_id);
                              setPasswordDraft('');
                              setPasswordConfirmation('');
                              setError('');
                            }}
                            disabled={busy}
                          >
                            Set password
                          </button>
                          <button
                            className="danger-button"
                            type="button"
                            onClick={() => deleteUser(user)}
                            disabled={busy || isCurrentAdmin}
                            title={isCurrentAdmin ? 'You cannot delete the signed-in admin account.' : undefined}
                          >
                            Delete user
                          </button>
                          {passwordUserId === user.user_id && (
                            <form
                              className="admin-password-form"
                              onSubmit={(event) => submitPassword(event, user)}
                            >
                              <input
                                aria-label={`New password for ${user.email || user.user_id}`}
                                type="password"
                                autoComplete="new-password"
                                minLength="8"
                                maxLength="128"
                                placeholder="New password"
                                value={passwordDraft}
                                onChange={(event) => setPasswordDraft(event.target.value)}
                                disabled={busy}
                                required
                              />
                              <input
                                aria-label={`Confirm password for ${user.email || user.user_id}`}
                                type="password"
                                autoComplete="new-password"
                                minLength="8"
                                maxLength="128"
                                placeholder="Confirm password"
                                value={passwordConfirmation}
                                onChange={(event) => setPasswordConfirmation(event.target.value)}
                                disabled={busy}
                                required
                              />
                              <button className="primary" type="submit" disabled={busy}>
                                Update password
                              </button>
                            </form>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {showAuditLog && (
        <div className="admin-modal-backdrop" role="presentation">
          <section
            className="admin-audit-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="admin-audit-title"
          >
            <header>
              <div>
                <p className="eyebrow">Administration</p>
                <h2 id="admin-audit-title">Application system log</h2>
                <p className="tiny-copy">Recent account and permission changes (latest 100).</p>
              </div>
              <button
                className="ghost-button"
                type="button"
                onClick={() => setShowAuditLog(false)}
                aria-label="Close system log"
              >
                Close
              </button>
            </header>
            {auditLogError && <p className="form-error" role="alert">{auditLogError}</p>}
            {auditLogLoading ? (
              <p className="tiny-copy">Loading system log…</p>
            ) : auditLogs.length === 0 && !auditLogError ? (
              <p className="tiny-copy">No admin activity has been recorded yet.</p>
            ) : (
              <div className="admin-audit-list">
                {auditLogs.map((entry) => (
                  <article className="admin-audit-entry" key={entry.id}>
                    <div>
                      <strong>{entry.summary}</strong>
                      <small>{entry.action}</small>
                    </div>
                    <div>
                      <span>Actor: {entry.actor_id}</span>
                      <span>Target: {entry.target_user_id || '—'}</span>
                    </div>
                    <time>{displayDate(entry.created_at)}</time>
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </main>
  );
}
