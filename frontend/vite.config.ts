import {defineConfig} from 'vite';import react from '@vitejs/plugin-react';import darkTheme from './dark-theme.mjs';
export default defineConfig({plugins:[react()],css:{postcss:{plugins:[darkTheme()]}},server:{proxy:{'/api':process.env.VITE_API_TARGET||'http://localhost:8000'}}})
