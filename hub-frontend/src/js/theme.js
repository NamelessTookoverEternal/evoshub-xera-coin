/* Shared accent-theme module. Import initTheme() as early as possible
   (before first paint) to avoid a flash of the default accent, and
   applyTheme()/getTheme() anywhere a picker UI needs to read or change it. */

export const THEMES = [
    { id: 'default', label: 'XERA Default', swatch: '#4c7eff' },
    { id: 'ocean',   label: 'Ocean',        swatch: '#2fb8e0' },
    { id: 'emerald', label: 'Emerald',      swatch: '#33d6a6' },
    { id: 'purple',  label: 'Purple',       swatch: '#9b6bff' },
    { id: 'rose',    label: 'Rose',         swatch: '#ff6b9d' },
    { id: 'gold',    label: 'Gold',         swatch: '#e0b23c' },
];

const STORAGE_KEY = 'evos_accent_theme';

export function getTheme() {
    const saved = localStorage.getItem(STORAGE_KEY);
    return THEMES.some((t) => t.id === saved) ? saved : 'default';
}

export function applyTheme(id) {
    const theme = THEMES.some((t) => t.id === id) ? id : 'default';
    if (theme === 'default') {
        document.documentElement.removeAttribute('data-accent');
    } else {
        document.documentElement.setAttribute('data-accent', theme);
    }
    localStorage.setItem(STORAGE_KEY, theme);
    return theme;
}

// Call inline/synchronously before paint (see the blocking <script> snippet
// used in each page's <head>) so the accent never flashes to default first.
export function initTheme() {
    const theme = getTheme();
    if (theme !== 'default') document.documentElement.setAttribute('data-accent', theme);
    return theme;
}
