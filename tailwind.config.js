// tailwind.config.js
module.exports = {
  content: [
    "./app/templates/**/*.html",
    "./static/**/*.js",
  ],
  theme: {
    extend: {
      colors: {
        primary: {
          50: '#e4f5ea',
          100: '#c0e8cc',
          200: '#9bdaad',
          300: '#75cc8e',
          400: '#50bf6f',
          500: '#25b350', // Primary brand color
          600: '#1e9c46',
          700: '#17863c',
          800: '#106f32',
          900: '#095928',
        },
        secondary: {
          50: '#e6f1f8',
          100: '#cce3f1',
          200: '#99c7e3',
          300: '#66abd5',
          400: '#338fc7',
          500: '#0073b9', // Secondary color
          600: '#0066a3',
          700: '#00598d',
          800: '#004c77',
          900: '#003f61',
        },
        gray: {
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
        },
        whatsapp: {
          light: '#dcf8c6',
          default: '#25d366',
          dark: '#128c7e',
        }
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
        heading: ['Poppins', 'Inter', 'ui-sans-serif', 'system-ui', '-apple-system', 'sans-serif'],
      },
      boxShadow: {
        card: '0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06)',
        'card-hover': '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)',
      },
      borderRadius: {
        'xl': '0.75rem',
        '2xl': '1rem',
      },
    },
  },
  plugins: [
    require('@tailwindcss/forms'),
  ],
}