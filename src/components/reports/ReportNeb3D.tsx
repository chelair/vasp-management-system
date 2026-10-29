import { useEffect, useRef } from 'react';
import NebImageMasterDetail from '../inspection/NebImageMasterDetail';
import type { ReportNebItem } from './ReportPanels';

export default function ReportNeb3D({ item }: { item: ReportNebItem }) {
  const host = useRef<HTMLDivElement>(null);
  const snapshot = useRef<HTMLImageElement>(null);
  useEffect(() => {
    const capture = () => {
      const canvas = host.current?.querySelector<HTMLCanvasElement>('.s3d-editor__canvas canvas');
      const target = snapshot.current;
      if (!target) return;
      target.hidden = true;
      target.removeAttribute('src');
      if (canvas) {
        target.src = canvas.toDataURL('image/png');
        target.hidden = false;
      }
    };
    window.addEventListener('beforeprint', capture);
    return () => window.removeEventListener('beforeprint', capture);
  }, []);
  const images = (item.images ?? []).map(image => ({
    label: String(image.label ?? ''),
    role: 'middle' as const,
    cif: image.cif ?? '',
    relative: image.relative_energy_ev ?? null,
    energy: image.energy_ev ?? null,
    max_force: image.max_force_ev_per_a ?? null,
  }));
  return <div className="report-neb" ref={host}>
    <div className="report-neb__interactive">
      <NebImageMasterDetail taskId={item.task_id ?? ''} images={images} barrier={images} report />
    </div>
    <img className="report-neb__print" ref={snapshot} hidden alt="当前 NEB 映像结构" />
  </div>;
}
