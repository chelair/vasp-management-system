import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import { ConfigProvider } from 'antd';
import zhCN from 'antd/locale/zh_CN';
import { themeConfig } from '../theme';

const STORAGE_KEY = 'vasp.appearance';
export const DEFAULT_APPEARANCE = { accent: '#527BC5', density: 'comfortable', motion: 'system', showClock: true } as const;
export interface Appearance {
  accent: string;
  density: 'comfortable' | 'compact';
  motion: 'system' | 'reduced';
  showClock: boolean;
}
export const ACCENT_COLORS = [
  { name: '雾蓝', color: '#527BC5' }, { name: '湖青', color: '#1C7C8F' }, { name: '松绿', color: '#237A5C' },
  { name: '鸢紫', color: '#7953B5' }, { name: '玫红', color: '#B14F7D' }, { name: '琥珀', color: '#A86424' },
];
const validHex = (color: unknown): color is string => typeof color === 'string' && /^#[\da-f]{6}$/i.test(color);
function readAppearance(): Appearance {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}');
    return {
      accent: validHex(value?.accent) ? value.accent.toUpperCase() : DEFAULT_APPEARANCE.accent,
      density: value?.density === 'compact' ? 'compact' : 'comfortable',
      motion: value?.motion === 'reduced' ? 'reduced' : 'system',
      showClock: typeof value?.showClock === 'boolean' ? value.showClock : true,
    };
  } catch { return { ...DEFAULT_APPEARANCE }; }
}
function accentPalette(hex: string) {
  const rgb = [1, 3, 5].map(offset => parseInt(hex.slice(offset, offset + 2), 16));
  const toHex = (values: number[]) => `#${values.map(value => value.toString(16).padStart(2, '0')).join('')}`;
  const blend = (factor: number, base = rgb) => toHex(base.map(value => Math.round(factor < 0 ? value * (1 + factor) : value + (255 - value) * factor)));
  const luminance = (values: number[]) => values.map(value => value / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  const light = luminance(rgb) > 0.35;
  const solid = [...rgb];
  // Prefer white on blue/dark accents; adjust only the solid fill to keep 4.5:1 contrast.
  while (!light && luminance(solid) > 1.05 / 4.5 - 0.05) {
    solid.forEach((value, index) => { solid[index] = Math.floor(value * 0.96); });
  }
  return { rgb: rgb.join(', '), strong: blend(luminance(rgb) > 0.179 ? -0.6 : -0.22),
    secondary: blend(0.24), on: light ? '#000000' : '#FFFFFF',
    solid: toHex(solid), hover: blend(-0.08, solid), active: blend(-0.14, solid) };
}
const AppearanceContext = createContext<{
  appearance: Appearance;
  reducedMotion: boolean;
  updateAppearance: (patch: Partial<Appearance>) => void;
  resetAppearance: () => void;
} | null>(null);

export function useAppearance() {
  const value = useContext(AppearanceContext);
  if (!value) throw new Error('useAppearance 必须在 AppearanceProvider 内使用');
  return value;
}

export function useReducedMotion() {
  const value = useContext(AppearanceContext);
  return value?.reducedMotion ?? window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/** 只保存浏览器展示偏好，不访问模型、SSH 或业务配置。 */
export function AppearanceProvider({ children }: { children: ReactNode }) {
  const [appearance, setAppearance] = useState<Appearance>(readAppearance);
  const [systemReduced, setSystemReduced] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const reduced = appearance.motion === 'reduced' || systemReduced;
  const palette = useMemo(() => accentPalette(appearance.accent), [appearance.accent]);
  const updateAppearance = useCallback((patch: Partial<Appearance>) => setAppearance(old => ({
    ...old, ...patch, accent: validHex(patch.accent) ? patch.accent.toUpperCase() : old.accent,
  })), []);
  const resetAppearance = useCallback(() => setAppearance({ ...DEFAULT_APPEARANCE }), []);

  useEffect(() => {
    const media = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setSystemReduced(media.matches);
    media.addEventListener('change', update);
    return () => media.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(appearance)); } catch { /* 存储不可用时仍保留本次页面选择。 */ }
  }, [appearance]);
  useLayoutEffect(() => {
    const root = document.documentElement;
    const colors = {
      '--color-primary': appearance.accent, '--color-primary-strong': palette.strong,
      '--color-primary-rgb': palette.rgb, '--color-primary-soft': `rgba(${palette.rgb}, 0.08)`,
      '--color-primary-border': `rgba(${palette.rgb}, 0.32)`, '--color-primary-on': palette.on,
      '--color-primary-solid': palette.solid, '--color-primary-hover': palette.hover, '--color-primary-active': palette.active,
      '--color-secondary': appearance.accent === DEFAULT_APPEARANCE.accent ? '#67c6b0' : palette.secondary,
    };
    Object.entries(colors).forEach(([key, value]) => root.style.setProperty(key, value));
    root.dataset.density = appearance.density;
    root.dataset.motion = reduced ? 'reduced' : 'system';
  }, [appearance.accent, appearance.density, palette, reduced]);

  const theme = useMemo(() => ({
    ...themeConfig,
    token: { ...themeConfig.token, colorPrimary: appearance.accent,
      controlHeight: appearance.density === 'compact' ? 32 : 36,
      // 动态切换 motion 布尔值会让 Ant Design 插入 Provider 并重挂业务页面；只切换动画时长。
      motionUnit: reduced ? 0 : 0.1 },
    components: {
      ...themeConfig.components,
      Button: { ...themeConfig.components?.Button, primaryColor: palette.on,
        colorPrimary: palette.solid, colorPrimaryHover: palette.hover, colorPrimaryActive: palette.active },
      Radio: { ...themeConfig.components?.Radio, buttonSolidCheckedColor: palette.on },
      Switch: { ...themeConfig.components?.Switch, colorTextLightSolid: palette.on },
      Card: { ...themeConfig.components?.Card, paddingLG: appearance.density === 'compact' ? 16 : 20 },
      Table: { ...themeConfig.components?.Table, cellPaddingBlock: appearance.density === 'compact' ? 8 : 12 },
      Tabs: { ...themeConfig.components?.Tabs, inkBarColor: appearance.accent, itemSelectedColor: palette.strong },
    },
  }), [appearance.accent, appearance.density, palette, reduced]);
  const value = useMemo(() => ({ appearance, reducedMotion: reduced, updateAppearance, resetAppearance }), [appearance, reduced, updateAppearance, resetAppearance]);
  return <AppearanceContext.Provider value={value}><ConfigProvider locale={zhCN} theme={theme}>{children}</ConfigProvider></AppearanceContext.Provider>;
}
