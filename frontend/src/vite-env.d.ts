/// <reference types="vite/client" />
declare module "*.svg?raw" { const s: string; export default s; }
interface Window { Telegram?: { WebApp: any } }
declare const require: never;
