/**
 * 报告「隐藏」的粒度与实现（2026-10-15 扩展，用户："报告支持按单个结构优化任务、单组 neb、
 * 自由能、单个电子结构任务隐藏"）。
 *
 * 支持的 key（`<章节>` = basic_info / science / issues / actions）：
 *
 * | key | 含义 | 页面里的元素 | 导出 HTML 里的元素 |
 * | --- | --- | --- | --- |
 * | `section:<章节>` | 整章（**导出范围就靠它**：隐藏的章节导出/打印都不含，v0.9.71 起取代"导出范围"勾选） | `<section>` | 整章不渲染 |
 * | `type:<章节>:<类型标题>` | 整个类型块（结构优化 / 自由能路径 / NEB 过渡态 / 电子结构） | `### → h5` + 其后同门内容 | `### → h4` 块 |
 * | `task:<章节>:<任务标题>` | **单个任务块**（一个结构优化任务 / 一组 NEB / 一条自由能路径 / 电子结构的一个子块） | `#### → h6` + 其后同门内容 | `#### → h5` 块 |
 * | `etask:<章节>:<任务名>` | **电子结构里一个任务的全部子块**（差分电荷 + Bader + PDOS + 功函数…） | 该任务名开头的所有 `h6` 块 | 同左（h5 前缀匹配） |
 * | `figure:<章节>:<序号>` | 单张图（序号 = 章节内 `<figure>` 顺序，与导出完全一致） | `<figure data-report-figure>` | 第 N 个 `<figure>` |
 *
 * 说明：
 * - 页面与导出的 HTML 标题层级差一级（页面 `###→h5`，导出 `###→h4`），所以 key 用**标题文字**
 *   而不是层级来定位 —— 两边都能对上；
 * - 单张图的序号靠 `renderMarkdown` 写下的 `data-report-figure`（渲染时就固定了），
 *   这样后面把图换成组件（自由能 / NEB / 进度 / PDOS 交互图）也不会让序号错位；
 * - 旧数据兼容：早期版本把「类型块」存成 `task:<章节>:<类型标题>`，这里一并认。
 */

export interface HiddenBlock {
  key: string;
  kind: 'section' | 'type' | 'task' | 'etask' | 'figure';
  /** 人类可读标签（按钮 tooltip / 「已隐藏」列表用） */
  label: string;
  /** 这个 key 控制的全部元素（隐藏时逐个加 class） */
  elements: HTMLElement[];
  /** 「隐藏」按钮挂在哪 */
  anchor: HTMLElement;
  /** 按钮文案（默认「隐藏」） */
  buttonText?: string;
  buttonTitle?: string;
}

/** 标题纯文本：排除运行时追加的「隐藏」按钮 */
function headingLabel(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('.report-hide-btn').forEach((btn) => btn.remove());
  return (clone.textContent ?? '').trim();
}

/** 收集报告里所有可隐藏的块（类型 / 任务 / 电子结构整任务 / 单图） */
export function collectHiddenBlocks(root: HTMLElement): HiddenBlock[] {
  const blocks: HiddenBlock[] = [];
  root.querySelectorAll('section[data-report-section]').forEach((section) => {
    const sectionKey = section.getAttribute('data-report-section') ?? '';
    // ⓪ 整章（v0.9.71）：导出时"隐藏的章节不包含" —— 取代原来的「导出范围」勾选
    const titleEl = (section.querySelector('.report-section-title') ?? section) as HTMLElement;
    blocks.push({
      key: `section:${sectionKey}`,
      kind: 'section',
      label: (titleEl.textContent ?? '').trim() || sectionKey,
      elements: [section as HTMLElement],
      anchor: titleEl,
      buttonText: '隐藏本章',
      buttonTitle: '隐藏整章（导出的 HTML / PDF 也不包含；可在右上角「已隐藏」里恢复）',
    });
    const body = section.querySelector('.report-markdown') as HTMLElement | null;
    if (!body || !sectionKey) return;
    const children = Array.from(body.children) as HTMLElement[];

    // ① 类型块（页面 h5 = markdown `###`）→ ② 类型块内的任务块（页面 h6 = markdown `####`）
    // ⚠️ 注意别把 h6 跳过去：类型块「包含」其下的任务块，两者都要各自成块（隐藏粒度不同）
    let index = 0;
    while (index < children.length) {
      if (children[index].tagName !== 'H5') {
        index += 1;
        continue;
      }
      let typeEnd = index + 1;
      while (typeEnd < children.length && children[typeEnd].tagName !== 'H5') typeEnd += 1;
      const typeLabel = headingLabel(children[index]);
      blocks.push({
        key: `type:${sectionKey}:${typeLabel}`,
        kind: 'type',
        label: typeLabel,
        elements: children.slice(index, typeEnd),
        anchor: children[index],
        buttonTitle: '隐藏这一类（可在右上角「已隐藏」里恢复）',
      });
      for (let cursor = index + 1; cursor < typeEnd; cursor += 1) {
        if (children[cursor].tagName !== 'H6') continue;
        let taskEnd = cursor + 1;
        while (taskEnd < typeEnd && children[taskEnd].tagName !== 'H6') taskEnd += 1;
        const taskLabel = headingLabel(children[cursor]);
        blocks.push({
          key: `task:${sectionKey}:${taskLabel}`,
          kind: 'task',
          label: taskLabel,
          elements: children.slice(cursor, taskEnd),
          anchor: children[cursor],
          buttonTitle: '隐藏这个任务块（可在右上角「已隐藏」里恢复）',
        });
        cursor = taskEnd - 1;
      }
      index = typeEnd;
    }

    // ③ 电子结构：同一任务名的多个子块（`<任务> · 差分电荷` / `· Bader 电荷` / `· 态密度` …）
    //    → 一个「隐藏整任务」入口
    const grouped = new Map<string, HiddenBlock[]>();
    blocks
      .filter(
        (b) => b.kind === 'task' && b.key.startsWith(`task:${sectionKey}:`) && b.label.includes(' · '),
      )
      .forEach((b) => {
        const name = b.label.split(' · ')[0].trim();
        grouped.set(name, [...(grouped.get(name) ?? []), b]);
      });
    grouped.forEach((list, name) => {
      if (list.length < 2) return; // 只有一个子块就不必再给"整任务"入口
      // 新版概览表与整模型隐藏联动，避免详细分析隐藏后概览仍保留该模型数据。
      const overview = children.find((el) => el.tagName === 'H5' && headingLabel(el) === '关键结果概览');
      let overviewTable = overview?.nextElementSibling;
      while (overviewTable && overviewTable.tagName !== 'TABLE' && overviewTable.tagName !== 'H5') {
        overviewTable = overviewTable.nextElementSibling;
      }
      const summaryRows = overviewTable?.tagName === 'TABLE'
        ? Array.from(overviewTable.querySelectorAll<HTMLElement>('tbody tr'))
          .filter((row) => row.querySelector('td')?.textContent?.trim() === name)
        : [];
      blocks.push({
        key: `etask:${sectionKey}:${name}`,
        kind: 'etask',
        label: name,
        elements: [...list.flatMap((b) => b.elements), ...summaryRows],
        anchor: list[0].anchor,
        buttonText: '隐藏整任务',
        buttonTitle: `${name} 的全部子块一起隐藏（可在右上角「已隐藏」里恢复）`,
      });
    });

    // ④ 单张图：序号取 renderMarkdown 写下的 data-report-figure（与导出 HTML 的顺序一致）
    Array.from(body.querySelectorAll('figure')).forEach((figure, order) => {
      const attr = figure.getAttribute('data-report-figure');
      const figureIndex = attr != null && attr !== '' ? Number(attr) : order;
      blocks.push({
        key: `figure:${sectionKey}:${figureIndex}`,
        kind: 'figure',
        label: `图 ${figureIndex + 1}`,
        elements: [figure as HTMLElement],
        anchor: figure as HTMLElement,
        buttonTitle: '隐藏这张图（可在右上角「已隐藏」里恢复）',
      });
    });
  });
  return blocks;
}

/**
 * 按 hidden 列表给元素加/去 `report-hidden`。
 *
 * 语义是**并集**：一个元素只要落在任意一个被隐藏的块里就隐藏
 * （隐藏了整类 → 里面的任务当然也跟着藏；再单独隐藏某个任务也照藏）。
 * 所以先清掉所有旧标记、再统一加 —— 不能边遍历边 toggle（后来的任务块会把父块的隐藏"抹掉"）。
 */
export function applyHiddenBlocks(blocks: HiddenBlock[], hidden: string[]): void {
  const wanted = new Set(hidden);
  const isHidden = (block: HiddenBlock) =>
    wanted.has(block.key) ||
    // 兼容旧数据：早期「类型块」存成 task:<章节>:<类型标题>
    (block.kind === 'type' && wanted.has(`task:${block.key.slice('type:'.length)}`));
  const marked = new Set<HTMLElement>();
  blocks.forEach((block) => {
    if (!isHidden(block)) return;
    block.elements.forEach((el) => marked.add(el));
  });
  const all = new Set<HTMLElement>();
  blocks.forEach((block) => block.elements.forEach((el) => all.add(el)));
  all.forEach((el) => el.classList.remove('report-hidden'));
  marked.forEach((el) => el.classList.add('report-hidden'));
}

/** 「已隐藏 N 项」列表里的人类可读标签 */
export function hiddenKeyLabel(key: string, sectionTitles: Record<string, string> = {}): string {
  const [kind, sectionKey, ...rest] = key.split(':');
  const label = rest.join(':');
  if (kind === 'section') return `章节 · ${sectionTitles[sectionKey] ?? sectionKey}`;
  const where = sectionTitles[sectionKey] ?? sectionKey;
  if (kind === 'type') return `类型 · ${label}（${where}）`;
  if (kind === 'task') return `任务 · ${label}（${where}）`;
  if (kind === 'etask') return `整个任务 · ${label}（${where}）`;
  if (kind === 'figure') return `图 ${Number(label) + 1}（${where}）`;
  return key;
}
