import { useEffect, useRef, useState } from "react";
import type { RegionKind } from "../lib/api";

export interface RegionDetails {
  name: string;
  label_forward: string;
  label_backward: string;
}

interface Props {
  kind: RegionKind;
  color: string;
  defaultName: string;
  existingNames: string[];
  onSave: (details: RegionDetails) => void;
  onCancel: () => void;
}

/** Popup shown right after a road / area / line is drawn, to give it a name. */
export default function NameRegionDialog({ kind, color, defaultName, existingNames, onSave, onCancel }: Props) {
  const [name, setName] = useState("");
  const [fwd, setFwd] = useState("A→B");
  const [bwd, setBwd] = useState("B→A");
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => inputRef.current?.focus(), []);

  const finalName = name.trim() || defaultName;
  const duplicate = existingNames.some((n) => n.toLowerCase() === finalName.toLowerCase());

  const save = () => {
    if (duplicate) return;
    onSave({ name: finalName, label_forward: fwd.trim() || "A→B", label_backward: bwd.trim() || "B→A" });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onMouseDown={onCancel}>
      <form
        role="dialog"
        aria-modal="true"
        aria-labelledby="name-region-title"
        className="card w-full max-w-sm space-y-4 p-5 shadow-xl"
        onMouseDown={(e) => e.stopPropagation()}
        onSubmit={(e) => {
          e.preventDefault();
          save();
        }}
        onKeyDown={(e) => e.key === "Escape" && onCancel()}
      >
        <div className="flex items-center gap-2">
          <span className="h-4 w-4 rounded" style={{ background: color }} />
          <h2 id="name-region-title" className="font-semibold">
            {kind === "polygon" ? "Name this road / area" : "Name this counting line"}
          </h2>
        </div>
        <label className="block space-y-1">
          <span className="label">Name</span>
          <input
            ref={inputRef}
            className="input"
            placeholder={defaultName}
            value={name}
            maxLength={200}
            onChange={(e) => setName(e.target.value)}
          />
          {duplicate && <span className="text-xs text-red-600">“{finalName}” is already used — choose another name.</span>}
          {kind === "polygon" && !duplicate && (
            <span className="text-xs text-ink-3">e.g. “A40 inbound”, “High Street”, “Car park exit”</span>
          )}
        </label>
        {kind === "line" && (
          <div className="grid grid-cols-2 gap-2">
            <label className="space-y-1">
              <span className="label">Arrow direction</span>
              <input className="input" value={fwd} onChange={(e) => setFwd(e.target.value)} />
            </label>
            <label className="space-y-1">
              <span className="label">Opposite</span>
              <input className="input" value={bwd} onChange={(e) => setBwd(e.target.value)} />
            </label>
          </div>
        )}
        <div className="flex justify-end gap-2">
          <button type="button" className="btn" onClick={onCancel}>Discard</button>
          <button type="submit" className="btn btn-primary" disabled={duplicate}>Save</button>
        </div>
      </form>
    </div>
  );
}
