import { createContext, useCallback, useContext, useState } from 'react';

const ToastContext = createContext(() => {});
const ICONS = { success: '✓', error: '!', warning: '⚠', info: 'i' };

export function ToastProvider({ children }) {
  const [toasts, setToasts] = useState([]);

  const toast = useCallback((message, type = 'info', title) => {
    const id = Math.random().toString(36).slice(2);
    setToasts((t) => [...t, { id, message, type, title }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), type === 'error' ? 6000 : 4000);
  }, []);

  return (
    <ToastContext.Provider value={toast}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast-${t.type}`}>
            <strong>{ICONS[t.type]}</strong>
            <div>
              {t.title && <div style={{ fontWeight: 600 }}>{t.title}</div>}
              <div>{t.message}</div>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);
