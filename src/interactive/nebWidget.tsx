import { createRoot } from 'react-dom/client';
import ReportNeb3D from '../components/reports/ReportNeb3D';
import type { ReportNebItem } from '../components/reports/ReportPanels';

export function mountNebWidget(host: HTMLElement, items: ReportNebItem[]): boolean {
  if (!items.length) return false;
  host.parentElement?.querySelector('.report-neb-energy-table')?.classList.add('report-neb-energy-table--static');
  const root = createRoot(host);
  root.render(<>{items.map((item, index) => <ReportNeb3D key={item.task_id ?? index} item={item} />)}</>);
  return true;
}
