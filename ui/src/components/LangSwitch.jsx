import { useEffect, useState } from "react";
import { getLang, onLangChange, setLang } from "../i18n/index.js";

/** EN ⇄ ಕನ್ನಡ switch — same control, and the same remembered choice, as the website. */
export default function LangSwitch({ style }) {
  const [lang, setLocal] = useState(getLang());
  useEffect(() => onLangChange(setLocal), []);
  const kn = lang === "kn";
  return (
    <button
      type="button"
      className="langsw"
      role="switch"
      aria-checked={kn}
      aria-label="ಕನ್ನಡ — show the workspace in Kannada"
      title="English ⇄ ಕನ್ನಡ"
      data-noi18n
      style={style}
      onClick={() => setLang(kn ? "en" : "kn")}
    >
      <span className="langsw-en">EN</span>
      <span className="langsw-trk">
        <i />
      </span>
      <span className="langsw-kn" lang="kn">
        ಕನ್ನಡ
      </span>
    </button>
  );
}
