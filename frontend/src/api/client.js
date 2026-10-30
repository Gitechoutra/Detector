import axios from 'axios';

// Session lives in sessionStorage so each browser tab can be logged in as a
// different role (e.g. User in one tab, Receiver in another) during the viva.
const SESSION_KEY = 'fs_session';

export function getSession() {
  try {
    return JSON.parse(sessionStorage.getItem(SESSION_KEY)) || null;
  } catch {
    return null;
  }
}

export function setSession(session) {
  try {
    if (session) sessionStorage.setItem(SESSION_KEY, JSON.stringify(session));
    else sessionStorage.removeItem(SESSION_KEY);
  } catch {
    /* storage unavailable: session lasts for this page only */
  }
}

const api = axios.create({ baseURL: '/api', timeout: 20000 });

api.interceptors.request.use((config) => {
  const session = getSession();
  if (session?.token) config.headers.Authorization = `Bearer ${session.token}`;
  return config;
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status;
    const url = error.config?.url || '';
    if (status === 401 && !url.startsWith('/auth/login') && !url.startsWith('/demo')) {
      setSession(null);
      if (!window.location.pathname.startsWith('/login')) window.location.assign('/login?expired=1');
    }
    return Promise.reject(error);
  },
);

/** Unwraps {success, data} responses. */
export async function call(method, url, body, config) {
  const res = await api.request({ method, url, data: body, ...config });
  return res.data;
}

export const get = (url, params) => call('get', url, undefined, { params }).then((r) => r.data);
export const post = (url, body, config) => call('post', url, body ?? {}, config);
export const put = (url, body) => call('put', url, body ?? {});
export const patch = (url, body) => call('patch', url, body ?? {});
export const del = (url) => call('delete', url);

export function errorMessage(error) {
  return (
    error?.response?.data?.error?.message ||
    (error?.code === 'ERR_NETWORK' ? 'Cannot reach the server. Is the backend running on port 5000?' : null) ||
    error?.message ||
    'Something went wrong.'
  );
}

export default api;
