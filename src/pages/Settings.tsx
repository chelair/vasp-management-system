import { Button, Card, ColorPicker, Select, Switch } from 'antd';
import { CheckOutlined, ReloadOutlined } from '@ant-design/icons';
import { ACCENT_COLORS, useAppearance } from '../context/AppearanceContext';
import PageHeader from '../components/common/PageHeader';
import PageTransition from '../components/common/PageTransition';

export default function Settings() {
  const { appearance, updateAppearance, resetAppearance } = useAppearance();
  return <PageTransition><div className="settings-page">
    <PageHeader title="设置" subtitle="按你的习惯调整界面，即时生效并保存在当前浏览器。"
      extra={<Button icon={<ReloadOutlined />} onClick={resetAppearance}>恢复默认</Button>} />
    <Card title="强调色">
      <p className="settings-description">用于主要按钮、导航和选中状态。告警状态与科研图表的颜色保持原意。</p>
      <div className="settings-colors" role="group" aria-label="选择强调色">
        {ACCENT_COLORS.map(item => <button key={item.color} type="button" className="settings-color" aria-pressed={appearance.accent === item.color}
          onClick={() => updateAppearance({ accent: item.color })}>
          <span className="settings-color-swatch" style={{ background: item.color }} aria-hidden="true">{appearance.accent === item.color && <CheckOutlined />}</span>
          <span>{item.name}</span>
        </button>)}
      </div>
      <div className="settings-custom-color"><span>自选颜色</span><ColorPicker value={appearance.accent} format="hex" disabledAlpha
        onChangeComplete={color => updateAppearance({ accent: color.toHexString() })}>
        <Button aria-label="自选强调色"><span className="settings-custom-swatch" style={{ background: appearance.accent }} />{appearance.accent}</Button>
      </ColorPicker></div>
      <div className="settings-preview" aria-label="强调色预览"><span className="settings-preview-primary">主要操作</span><span className="settings-preview-selected">选中项目</span><span className="status-tag status-tag--completed"><span className="status-tag__dot" />已完成</span></div>
    </Card>
    <Card title="页面显示">
      <div className="settings-row"><div><h3>显示密度</h3><p>调整表格行距、控件高度和页面留白，文字大小保持不变。</p></div>
        <Select aria-label="显示密度" value={appearance.density} onChange={density => updateAppearance({ density })}
          options={[{ value: 'comfortable', label: '舒适' }, { value: 'compact', label: '紧凑' }]} /></div>
      <div className="settings-row"><div><h3>界面动效</h3><p>减少页面、卡片和导航的过渡效果，加载指示照常显示。</p></div>
        <Select aria-label="界面动效" value={appearance.motion} onChange={motion => updateAppearance({ motion })}
          options={[{ value: 'system', label: '跟随系统' }, { value: 'reduced', label: '减少动态效果' }]} /></div>
      <div className="settings-row"><div><h3>顶部时钟</h3><p>在桌面版顶部显示日期和时间。</p></div><Switch aria-label="显示顶部时钟" checked={appearance.showClock} onChange={showClock => updateAppearance({ showClock })} /></div>
    </Card>
    <p className="settings-footnote">这些选项仅影响当前浏览器的页面显示，不改变模型、任务、计算参数或其他用户的设置。</p>
  </div></PageTransition>;
}
