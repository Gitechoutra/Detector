import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { getSession, post, setSession } from '../api/client';
import { deviceId, deviceName } from '../utils/device';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setState] = useState(getSession);

  const login = useCallback(async (email, password, locationId) => {
    const res = await post('/auth/login', {
      email, password, device_id: deviceId(), device_name: deviceName(), location_id: locationId || null,
    });
    const next = { token: res.data.token, user: res.data.user, dashboard: res.data.dashboard };
    setSession(next);
    setState(next);
    return next;
  }, []);

  const register = useCallback(async (form) => {
    const res = await post('/auth/register', { ...form, device_id: deviceId(), device_name: deviceName() });
    const next = { token: res.data.token, user: res.data.user, dashboard: res.data.dashboard };
    setSession(next);
    setState(next);
    return { ...next, account: res.data.account };
  }, []);

  const logout = useCallback(async () => {
    try {
      await post('/auth/logout');
    } catch {
      /* token may already be invalid; logging out locally is enough */
    }
    setSession(null);
    setState(null);
  }, []);

  const value = useMemo(() => ({ session, user: session?.user, login, register, logout }),
    [session, login, register, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export const useAuth = () => useContext(AuthContext);
