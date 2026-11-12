import animate from "tailwindcss-animate";

/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class"],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        graphite: {
          0: "#0E1116",
          1: "#151A21",
          2: "#1C232C",
          3: "#232C36",
        },
        line: "#2A333D",
        ink: {
          0: "#E6EAEF",
          1: "#B7C2CE",
          2: "#8B98A6",
          3: "#5A6672",
        },
        copper: {
          300: "#E8A45C",
          400: "#D98324",
          500: "#B96E1B",
        },
        teal: "#3E8E7E",
        amber: "#D9A441",
        danger: "#C9524B",
        steel: "#4C7EA8",
        paper: {
          0: "#F5F6F8",
          1: "#ECEEF2",
          2: "#E2E6EC",
        },
      },
      fontFamily: {
        display: ["DIN Next", "Source Sans Pro", "PingFang SC", "Microsoft YaHei", "sans-serif"],
        sans: ["Source Sans Pro", "PingFang SC", "Microsoft YaHei", "sans-serif"],
        mono: ["JetBrains Mono", "SFMono-Regular", "Cascadia Code", "Consolas", "monospace"],
      },
      fontSize: {
        display: ["28px", { lineHeight: "1.1", letterSpacing: "-0.02em", fontWeight: "600" }],
        subhead: ["16px", { lineHeight: "1.4", fontWeight: "500" }],
        body: ["14px", { lineHeight: "1.6" }],
        micro: ["11px", { lineHeight: "1.4", letterSpacing: "0.08em" }],
      },
      borderRadius: {
        panel: "10px",
        control: "6px",
      },
      boxShadow: {
        lift: "0 8px 24px rgba(0,0,0,0.28)",
        inset: "inset 0 1px 0 rgba(255,255,255,0.04)",
      },
      transitionTimingFunction: {
        precise: "cubic-bezier(0.16, 1, 0.3, 1)",
      },
      keyframes: {
        "fade-rise": {
          from: { opacity: "0", transform: "translateY(8px)" },
          to: { opacity: "1", transform: "translateY(0)" },
        },
        "pulse-line": {
          "0%, 100%": { opacity: "1" },
          "50%": { opacity: "0.35" },
        },
      },
      animation: {
        "fade-rise": "fade-rise 600ms cubic-bezier(0.16,1,0.3,1) both",
        "pulse-line": "pulse-line 2.4s ease-in-out infinite",
      },
    },
  },
  plugins: [animate],
};
