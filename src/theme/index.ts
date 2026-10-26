import type { ThemeConfig } from 'antd';

/**
 * Ant Design 5 主题令牌。
 * 蓝绿配色，统一控件层级；轻阴影、实色面板，无额外渲染依赖。
 */
export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: '#527BC5',
    colorInfo: '#527BC5',
    colorSuccess: '#3DBD93',
    colorWarning: '#F0A63B',
    colorError: '#E5686E',
    colorText: '#263449',
    colorTextSecondary: '#65758B',
    colorTextTertiary: '#8492A5',
    colorBgLayout: '#F5F7FA',
    colorBgContainer: '#FFFFFF',
    colorBorder: '#DFE5EE',
    colorBorderSecondary: '#EBEFF5',
    borderRadius: 8,
    borderRadiusLG: 14,
    controlHeight: 36,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
    boxShadow: '0 1px 3px rgba(28, 44, 65, 0.04)',
    boxShadowSecondary: '0 8px 28px rgba(28, 44, 65, 0.10)',
  },
  components: {
    Card: {
      headerBg: '#FFFFFF',
      paddingLG: 20,
      borderRadiusLG: 14,
      headerFontSize: 14,
    },
    Table: {
      headerBg: '#F7F9FC',
      headerColor: '#65758B',
      rowHoverBg: '#F4F7FC',
      borderColor: '#EBEFF5',
      headerSplitColor: 'transparent',
      cellPaddingBlock: 12,
    },
    Button: {
      fontWeight: 500,
      primaryShadow: '0 1px 2px rgba(44, 74, 124, 0.14)',
    },
    Modal: {
      borderRadiusLG: 14,
    },
    Tabs: {
      inkBarColor: '#527BC5',
      itemSelectedColor: '#4266AD',
      horizontalItemGutter: 24,
    },
  },
};
