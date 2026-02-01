/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './templates/**/*.html',
    './**/templates/**/*.html',
    './static/js/**/*.js',
    './src/**/*.css',
  ],
  // 禁用 preflight 避免与现有样式冲突
  corePlugins: {
    preflight: false,
  },
  theme: {
    extend: {
      colors: {
        // 背景色
        'bg-primary': 'var(--bg-primary)',      // #F7E8C8
        'bg-secondary': 'var(--bg-secondary)',  // #E6D2A5
        'bg-dark': 'var(--bg-dark)',            // #5C3A21
        'bg-panel': 'var(--bg-panel)',          // #FFF8E7
        'bg-card': 'var(--bg-card)',            // #F2E6D6
        'bg-hover': 'var(--bg-hover)',          // #F0E6D2

        // 边框色
        'border-primary': 'var(--border-primary)',  // #8B4513
        'border-light': 'var(--border-light)',      // #D4A574
        'border-inner': 'var(--border-inner)',      // #C19A6B
        'border-decorative': 'var(--border-decorative)', // #B8860B

        // 文字色
        'text-primary': 'var(--text-primary)',      // #3A1F0A
        'text-secondary': 'var(--text-secondary)',  // #5C3A21
        'text-muted': 'var(--text-muted)',          // #8B6F47
        'text-light': 'var(--text-light)',          // #FFF8E7
        'text-highlight': 'var(--text-highlight)',  // #B22222

        // 强调色
        'accent-red': 'var(--accent-red)',      // #DC143C
        'accent-green': 'var(--accent-green)',  // #059669
        'accent-gold': 'var(--accent-gold)',    // #DAA520

        // 导航色
        'nav-bg': 'var(--nav-bg)',        // #5D3A20
        'nav-active': 'var(--nav-active)', // #8B4513
      },
      fontFamily: {
        'game': ['"SimSun"', '"宋体"', '"STKaiti"', '"KaiTi"', 'serif'],
        'kai': ['"楷体"', '"KaiTi"', '"STKaiti"', 'serif'],
      },
      boxShadow: {
        'panel': '0 2px 4px rgba(0, 0, 0, 0.1)',
        'card': '0 1px 3px rgba(0, 0, 0, 0.08)',
      },
      borderRadius: {
        'panel': '4px',
      },
    },
  },
  // 动态类名支持 - JS 中操作的类名需要在这里列出
  safelist: [
    // Toast 类型
    { pattern: /toast-(system|success|error|warning|info)/ },
    // 对话框按钮类型
    { pattern: /game-dialog-btn-(primary|secondary|danger)/ },
    // 连接状态
    { pattern: /is-(connected|connecting|disconnected)/ },
    // Flash 消息类型
    { pattern: /flash-(success|error|warning|info)/ },
    // 其他状态类
    'is-open',
    'is-self',
    'is-error',
    'is-dragging',
    'countdown-finished',
    'dragging',
    'active',
    'disabled',
    'hidden',
  ],
  plugins: [],
};
