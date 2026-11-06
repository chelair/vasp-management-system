export default function PageLoading({ label = '正在加载页面…', fullPage = false }: {
  label?: string;
  fullPage?: boolean;
}) {
  return (
    <section className={`page-loading${fullPage ? ' page-loading--full' : ''}`} role="status" aria-live="polite">
      <div className="page-loading__label"><span aria-hidden="true" />{label}</div>
      <div className="page-loading__panels" aria-hidden="true">
        {[0, 1, 2].map(panel => (
          <div className="page-loading__panel" key={panel}>
            <div className="page-loading__heading" />
            {[0, 1, 2].map(row => (
              <div className="page-loading__row" key={row}><span /><span /><span /></div>
            ))}
          </div>
        ))}
      </div>
    </section>
  );
}
