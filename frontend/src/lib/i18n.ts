export type Language = "vi" | "en";

export const LANG_STORAGE_KEY = "r2s-lang";
const LANG_EVENT = "r2s:lang";

export const LANG_INIT_SCRIPT = `try{var l=localStorage.getItem("${LANG_STORAGE_KEY}");if(l==="en"||l==="vi")document.documentElement.setAttribute("lang",l);}catch(e){}`;

export function currentLanguage(): Language {
  if (typeof document !== "undefined") {
    const docLang = document.documentElement.getAttribute("lang");
    if (docLang === "en" || docLang === "vi") return docLang;
    try {
      const saved = window.localStorage.getItem(LANG_STORAGE_KEY);
      if (saved === "en" || saved === "vi") {
        document.documentElement.setAttribute("lang", saved);
        return saved;
      }
    } catch {}
    document.documentElement.setAttribute("lang", "vi");
  }
  return "vi";
}

export function applyLanguage(lang: Language): void {
  if (typeof document !== "undefined") {
    document.documentElement.setAttribute("lang", lang);
  }
  try {
    window.localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {}
  window.dispatchEvent(new Event(LANG_EVENT));
}

export function subscribeLanguage(listener: () => void): () => void {
  window.addEventListener(LANG_EVENT, listener);
  return () => window.removeEventListener(LANG_EVENT, listener);
}
