import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import zhHans from "../locales/zh-Hans.json";
import zhHant from "../locales/zh-Hant.json";
import en from "../locales/en.json";
import ja from "../locales/ja.json";
import ko from "../locales/ko.json";
import de from "../locales/de.json";
import fr from "../locales/fr.json";
import it from "../locales/it.json";
import pt from "../locales/pt.json";
import ru from "../locales/ru.json";
import es from "../locales/es.json";

export const LANGUAGES = [
  { code: "zh-Hans", label: "简体中文" },
  { code: "zh-Hant", label: "繁體中文" },
  { code: "en", label: "English" },
  { code: "ja", label: "日本語" },
  { code: "ko", label: "한국어" },
  { code: "de", label: "Deutsch" },
  { code: "fr", label: "Français" },
  { code: "it", label: "Italiano" },
  { code: "pt", label: "Português" },
  { code: "ru", label: "Русский" },
  { code: "es", label: "Español" },
] as const;

export type LanguageCode = (typeof LANGUAGES)[number]["code"];

const resources = {
  "zh-Hans": { translation: zhHans },
  "zh-Hant": { translation: zhHant },
  en: { translation: en },
  ja: { translation: ja },
  ko: { translation: ko },
  de: { translation: de },
  fr: { translation: fr },
  it: { translation: it },
  pt: { translation: pt },
  ru: { translation: ru },
  es: { translation: es },
};

function detect(): LanguageCode {
  const saved = localStorage.getItem("tpmsc.lang");
  if (saved && LANGUAGES.some((item) => item.code === saved)) return saved as LanguageCode;
  const browser = navigator.language.toLowerCase();
  if (browser.startsWith("zh")) {
    return /hant|tw|hk|mo/.test(browser) ? "zh-Hant" : "zh-Hans";
  }
  const short = browser.split("-")[0];
  const matched = LANGUAGES.find((item) => item.code === short);
  return matched ? (matched.code as LanguageCode) : "zh-Hans";
}

const initial = detect();

void i18n.use(initReactI18next).init({
  resources,
  lng: initial,
  fallbackLng: "en",
  interpolation: { escapeValue: false },
  returnNull: false,
});

document.documentElement.lang = initial;

export function setLanguage(code: LanguageCode): void {
  void i18n.changeLanguage(code);
  localStorage.setItem("tpmsc.lang", code);
  document.documentElement.lang = code;
}

export default i18n;
