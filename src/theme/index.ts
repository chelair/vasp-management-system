import type { ThemeConfig } from 'antd';

/**
 * Ant Design 5 主题令牌。
 * 主色调采用柔和蓝绿色系：primary #5B8DEF，success/辅助 #67C6B0。
 */
export const themeConfig: ThemeConfig = {
  token: {
    colorPrimary: '#5B8DEF',
    colorInfo: '#5B8DEF',
    colorSuccess: '#3DBD93',
    colorWarning: '#F0A63B',
    colorError: '#E5686E',
    colorText: '#233043',
    colorTextSecondary: '#6B7A90',
    colorTextTertiary: '#9AA7B8',
    colorBgLayout: '#F6F8FB',
    colorBgContainer: '#FFFFFF',
    colorBorder: '#E7ECF3',
    colorBorderSecondary: '#EDF1F7',
    borderRadius: 10,
    borderRadiusLG: 16,
    controlHeight: 36,
    fontFamily:
      "-apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Hiragino Sans GB', 'Microsoft YaHei', sans-serif",
    boxShadow: '0 2px 12px rgba(35, 48, 67, 0.06)',
    boxShadowSecondary: '0 10px 28px rgba(35, 48, 67, 0.10)',
  },
  components: {
    Card: {
      headerBg: '#FFFFFF',
      paddingLG: 20,
      borderRadiusLG: 16,
    },
    Table: {
      headerBg: '#F8FAFD',
      headerColor: '#6B7A90',
      rowHoverBg: '#F7FAFF',
      cellPaddingBlock: 12,
    },
    Button: {
      fontWeight: 500,
      primaryShadow: '0 4px 12px rgba(91, 141, 239, 0.25)',
    },
    Modal: {
      borderRadiusLG: 18,
    },
    Tabs: {
      inkBarColor: '#5B8DEF',
      itemSelectedColor: '#3F6FE0',
    },
  },
};
