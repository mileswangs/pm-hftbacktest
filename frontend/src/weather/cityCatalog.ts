export interface CityPreset {
  slug: string;
  label: string;
  sourceSlug?: string;
}

export const CITY_PRESETS: readonly CityPreset[] = [
  { slug: 'chengdu', label: 'Chengdu' },
  { slug: 'beijing', label: 'Beijing' },
  { slug: 'shanghai', label: 'Shanghai' },
  { slug: 'guangzhou', label: 'Guangzhou' },
  { slug: 'shenzhen', label: 'Shenzhen' },
  { slug: 'tokyo', label: 'Tokyo' },
  { slug: 'seoul', label: 'Seoul' },
  { slug: 'hong-kong', label: 'Hong Kong' },
  { slug: 'singapore', label: 'Singapore' },
  { slug: 'los-angeles', label: 'Los Angeles' },
  { slug: 'london', label: 'London' },
  { slug: 'paris', label: 'Paris' },
  { slug: 'madrid', label: 'Madrid' },
  { slug: 'madrid-latest-proxy', label: 'Madrid Latest · price proxy', sourceSlug: 'madrid' },
  { slug: 'taipei', label: 'Taipei' },
];

export const CUSTOM_CITY_VALUE = '__custom__';

export function findPresetCity(slug: string) {
  return CITY_PRESETS.find((city) => city.slug === slug) ?? null;
}
