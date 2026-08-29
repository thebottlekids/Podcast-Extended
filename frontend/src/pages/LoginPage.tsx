import type { FormEvent } from 'react';
import { useState, useEffect, useRef } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import { useAuth } from '../contexts/AuthContext';
import { authentikApi, discordApi } from '../services/api';

export default function LoginPage() {
  const { login, landingPageEnabled } = useAuth();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [discordEnabled, setDiscordEnabled] = useState(false);
  const [discordLoading, setDiscordLoading] = useState(false);
  const [authentikEnabled, setAuthentikEnabled] = useState(false);
  const [authentikLoading, setAuthentikLoading] = useState(false);
  const [showPasswordLogin, setShowPasswordLogin] = useState(false);
  const [autoRedirecting, setAutoRedirecting] = useState(false);
  const [ssoStatusLoaded, setSsoStatusLoaded] = useState(false);
  // The auto-redirect fetch and the "use password instead" click can race:
  // without this, clicking the escape hatch while the fetch is still
  // in-flight doesn't actually stop the redirect once it resolves.
  const bailedFromAutoRedirect = useRef(false);

  // Read once at mount: the manual-chooser escape hatch, same convention as
  // this household's other auto-redirecting apps (e.g. cloud.mknudsen.net's
  // Nextcloud login uses the same ?direct=1 pattern).
  const [directMode] = useState(
    () => new URLSearchParams(window.location.search).get('direct') === '1'
  );

  const ssoEnabled = discordEnabled || authentikEnabled;

  // Check for OAuth callback errors in URL
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const urlError = params.get('error');
    if (urlError) {
      const messages: Record<string, string> = {
        'guild_requirement_not_met': 'You must be a member of the required Discord server.',
        'registration_disabled': 'Self-registration is currently disabled.',
        'auth_failed': 'Single sign-on authentication failed. Please try again.',
        'invalid_state': 'Invalid session state. Please try again.',
        'access_denied': 'Access was denied.',
        'discord_not_configured': 'Discord SSO is not configured.',
        'authentik_not_configured': 'Authentik SSO is not configured.',
        'missing_code': 'Missing authorization code from the identity provider.',
        'no_admin_user': 'No admin account exists to sign in to.',
      };
      setError(messages[urlError] || 'An error occurred during login.');
      // Clean URL
      window.history.replaceState({}, '', window.location.pathname);
    }
  }, []);

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);
    setSubmitting(true);

    try {
      await login(username, password);
      setUsername('');
      setPassword('');
    } catch (err) {
      if (axios.isAxiosError(err)) {
        const message = err.response?.data?.error ?? 'Invalid username or password.';
        setError(message);
      } else if (err instanceof Error) {
        setError(err.message);
      } else {
        setError('Login failed. Please try again.');
      }
    } finally {
      setSubmitting(false);
    }
  };

  const handleDiscordLogin = async () => {
    setError(null);
    setDiscordLoading(true);
    try {
      const { authorization_url } = await discordApi.getLoginUrl();
      window.location.href = authorization_url;
    } catch {
      setError('Failed to start Discord login. Please try again.');
      setDiscordLoading(false);
    }
  };

  const handleAuthentikLogin = async () => {
    setError(null);
    setAuthentikLoading(true);
    try {
      const { authorization_url } = await authentikApi.getLoginUrl();
      if (bailedFromAutoRedirect.current) {
        setAuthentikLoading(false);
        return;
      }
      window.location.href = authorization_url;
    } catch {
      setError('Failed to start Authentik login. Please try again.');
      setAuthentikLoading(false);
      setAutoRedirecting(false);
      setSsoStatusLoaded(true);
    }
  };

  // Check which SSO providers are enabled, and auto-redirect straight to
  // Authentik unless the manual chooser was explicitly requested (?direct=1)
  // or the page just loaded after a failed attempt (an error param present
  // -- redirecting again immediately would loop).
  useEffect(() => {
    const hadError = new URLSearchParams(window.location.search).has('error');

    Promise.allSettled([discordApi.getStatus(), authentikApi.getStatus()]).then(
      ([discordResult, authentikResult]) => {
        const discordOn = discordResult.status === 'fulfilled' && discordResult.value.enabled;
        const authentikOn = authentikResult.status === 'fulfilled' && authentikResult.value.enabled;
        setDiscordEnabled(discordOn);
        setAuthentikEnabled(authentikOn);
        setShowPasswordLogin(!discordOn && !authentikOn);

        if (authentikOn && !directMode && !hadError) {
          setAutoRedirecting(true);
          void handleAuthentikLogin();
        } else {
          setSsoStatusLoaded(true);
        }
      }
    );
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center px-4">
      <div className="w-full max-w-md bg-white shadow-lg rounded-xl border border-gray-200 p-6">
        <div className="flex flex-col items-center gap-2 mb-6">
          <Link to="/" className="flex items-center gap-2 hover:opacity-80 transition-opacity">
            <img src="/images/logos/logo.webp" alt="Podly" className="h-10 w-auto" />
          </Link>
          <h1 className="text-xl font-semibold text-gray-900">Sign in to Podly</h1>
        </div>

        {error && (
          <div className="rounded-md bg-red-50 border border-red-200 px-3 py-2 text-sm text-red-700 mb-4">
            {error}
          </div>
        )}

        {autoRedirecting && (
          <div className="flex flex-col items-center gap-4 py-6">
            <span className="animate-spin h-6 w-6 border-2 border-slate-800 border-t-transparent rounded-full" />
            <p className="text-sm text-gray-600">Redirecting to Authentik…</p>
            <button
              type="button"
              onClick={() => {
                bailedFromAutoRedirect.current = true;
                setAutoRedirecting(false);
                setSsoStatusLoaded(true);
                setShowPasswordLogin(true);
              }}
              className="text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
            >
              Use username / password instead
            </button>
          </div>
        )}

        {!autoRedirecting && ssoStatusLoaded && ssoEnabled && (
          <div className="space-y-3 mb-4">
            {authentikEnabled && (
              <button
                type="button"
                onClick={handleAuthentikLogin}
                disabled={authentikLoading}
                className="w-full flex justify-center items-center gap-2 rounded-md bg-slate-800 px-4 py-3 text-white font-semibold shadow hover:bg-slate-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {authentikLoading ? (
                  <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                ) : (
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <rect x="3" y="11" width="18" height="10" rx="2" />
                    <path d="M7 11V7a5 5 0 0 1 10 0v4" />
                  </svg>
                )}
                {authentikLoading ? 'Redirecting…' : 'Continue with Authentik'}
              </button>
            )}
            {discordEnabled && (
              <button
                type="button"
                onClick={handleDiscordLogin}
                disabled={discordLoading}
                className="w-full flex justify-center items-center gap-2 rounded-md bg-[#5865F2] px-4 py-3 text-white font-semibold shadow hover:bg-[#4752C4] transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
              >
                {discordLoading ? (
                  <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />
                ) : (
                  <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                    <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
                  </svg>
                )}
                {discordLoading ? 'Redirecting…' : 'Continue with Discord'}
              </button>
            )}
            {!showPasswordLogin && (
              <button
                type="button"
                onClick={() => setShowPasswordLogin(true)}
                className="w-full text-sm font-medium text-blue-700 hover:text-blue-800 hover:underline"
              >
                Use username / password
              </button>
            )}
          </div>
        )}

        {!autoRedirecting && ssoStatusLoaded && (!ssoEnabled || showPasswordLogin) && (
          <form
            className={`space-y-4 ${ssoEnabled ? 'pt-4 border-t border-gray-200' : ''}`}
            onSubmit={handleSubmit}
          >
            <div>
              <label htmlFor="username" className="block text-sm font-medium text-gray-700">
                Username
              </label>
              <input
                id="username"
                name="username"
                type="text"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                disabled={submitting}
                required
              />
            </div>

            <div>
              <label htmlFor="password" className="block text-sm font-medium text-gray-700">
                Password
              </label>
              <input
                id="password"
                name="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                className="mt-1 block w-full rounded-md border border-gray-300 px-3 py-2 shadow-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
                disabled={submitting}
                required
              />
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full flex justify-center items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-white font-medium hover:bg-blue-700 transition-colors disabled:opacity-60 disabled:cursor-not-allowed"
            >
              {submitting && <span className="animate-spin h-4 w-4 border-2 border-white border-t-transparent rounded-full" />}
              {submitting ? 'Signing in…' : 'Sign in'}
            </button>
          </form>
        )}

        <div className="mt-4 flex flex-col items-center gap-3">
          <a href="https://discord.gg/FRB98GtF6N" target="_blank" rel="noopener noreferrer">
            <img src="https://img.shields.io/badge/discord-join-blue.svg?logo=discord&logoColor=white" alt="Discord" />
          </a>
          {landingPageEnabled && (
            <Link to="/" className="text-sm text-gray-500 hover:text-gray-700 transition-colors">
              ← Back to home
            </Link>
          )}
        </div>
      </div>
    </div>
  );
}
