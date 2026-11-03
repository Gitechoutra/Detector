import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    port: 3000,
    proxy: {
      // VITE_API_TARGET lets the browser tests point a second dev server at their own backend.
      '/api': process.env.VITE_API_TARGET || 'http://127.0.0.1:5000',
    },
  },
});
