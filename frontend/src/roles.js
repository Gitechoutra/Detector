// One place that knows which dashboard belongs to which role. Mirrors the
// backend's DASHBOARDS map (portal/helpers/auth.py) and the routes in App.jsx.
// Customers send and receive with one USER login; the Receiver role is retired.
export const ROLE_INFO = {
  USER: { label: 'User', dashboard: '/user' },
  DETECTION: { label: 'Detection Engine', dashboard: '/detection' },
  FRAUDER: { label: 'Fraudster', dashboard: '/frauder' },
};

export const isRole = (role) => Object.prototype.hasOwnProperty.call(ROLE_INFO, role);

/** The role whose dashboard contains `path`, or null. */
export function roleForPath(path = '') {
  return Object.keys(ROLE_INFO).find((role) => {
    const base = ROLE_INFO[role].dashboard;
    return path === base || path.startsWith(`${base}/`);
  }) || null;
}

/** Where to send someone who wants to open `role`'s dashboard (optionally a page inside it). */
export function dashboardHref(session, role, path = ROLE_INFO[role].dashboard) {
  if (session?.user?.role === role) return path;
  return `/login?role=${role}&next=${encodeURIComponent(path)}`;
}
