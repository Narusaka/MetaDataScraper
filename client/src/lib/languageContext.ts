import { createContext, useContext } from 'react';

export const languageOptions = {
  en: 'English',
  zh: '中文',
} as const;

export type Language = keyof typeof languageOptions;

interface LanguageContextValue {
  language: Language;
  setLanguage: (language: Language) => void;
  t: (key: string) => string;
}

export const LanguageContext = createContext<LanguageContextValue | null>(null);

export function useTranslation() {
  const context = useContext(LanguageContext);
  if (!context) {
    throw new Error('useTranslation must be used within LanguageProvider');
  }
  return context;
}
