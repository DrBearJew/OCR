import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'
import { de } from './de'
import { en } from './en'

export type Language = 'en' | 'de'

type Messages = Record<string, string>

const LANGUAGE_STORAGE_KEY = 'dok-language'
const messages: Record<Language, Messages> = { en, de }

interface I18nContextValue {
  language: Language
  setLanguage: (language: Language) => void
  t: (key: string, fallback?: string) => string
}

const I18nContext = createContext<I18nContextValue | null>(null)

function detectLanguage(): Language {
  if (typeof window === 'undefined') return 'en'
  const stored = window.localStorage.getItem(LANGUAGE_STORAGE_KEY)
  if (stored === 'de' || stored === 'en') return stored
  return window.navigator.language.toLowerCase().startsWith('de') ? 'de' : 'en'
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<Language>(detectLanguage)

  useEffect(() => {
    document.documentElement.lang = language
    window.localStorage.setItem(LANGUAGE_STORAGE_KEY, language)
  }, [language])

  const value = useMemo<I18nContextValue>(() => ({
    language,
    setLanguage: setLanguageState,
    t: (key, fallback) => messages[language][key] ?? messages.en[key] ?? fallback ?? key,
  }), [language])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

export function useI18n() {
  const context = useContext(I18nContext)
  if (!context) throw new Error('useI18n must be used inside I18nProvider')
  return context
}
