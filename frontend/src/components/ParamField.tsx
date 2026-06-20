import type { ParamSpec } from '../strategies/registry';

export function ParamField({
  spec,
  value,
  onChange,
}: {
  spec: ParamSpec;
  value: number;
  onChange: (v: number) => void;
}) {
  return (
    <div>
      <label className="field-label" htmlFor={spec.key}>
        {spec.label}
      </label>
      <input
        id={spec.key}
        className="input mono"
        type="number"
        min={spec.min}
        max={spec.max}
        step={spec.step}
        value={Number.isFinite(value) ? value : ''}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </div>
  );
}
