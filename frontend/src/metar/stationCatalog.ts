export interface StationPreset {
  slug: string;
  label: string;
  citySlug: string;
  cityLabel: string;
}

export const STATION_PRESETS: readonly StationPreset[] = [
  { slug: 'lemd', label: 'Madrid-Barajas (LEMD)', citySlug: 'madrid', cityLabel: 'Madrid' },
];

export function findStationPreset(slug: string) {
  return STATION_PRESETS.find((station) => station.slug === slug) ?? null;
}
