// The app's own rules (app/frontend/eslint.config.js), applied to the demo's
// code. app/ is linted by its own config in its own CI job — it is a snapshot,
// and this repo does not edit it.
import js from "@eslint/js";
import globals from "globals";
import reactHooks from "eslint-plugin-react-hooks";
import reactRefresh from "eslint-plugin-react-refresh";
import tseslint from "typescript-eslint";

export default tseslint.config(
  { ignores: ["dist", "dist-nginx", "node_modules", "app", "docs", "selfhost"] },
  {
    extends: [js.configs.recommended, ...tseslint.configs.recommended],
    files: ["**/*.{ts,tsx,js}"],
    languageOptions: { ecmaVersion: 2022, sourceType: "module", globals: { ...globals.browser } },
    rules: {
      "@typescript-eslint/no-unused-vars": [
        "error",
        { argsIgnorePattern: "^_", varsIgnorePattern: "^_", caughtErrorsIgnorePattern: "^_" },
      ],
      "@typescript-eslint/no-explicit-any": "off",
      "prefer-const": "error",
      "no-var": "error",
    },
  },
  {
    files: ["demo/src/**/*.{ts,tsx}"],
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      "react-hooks/rules-of-hooks": "error",
      "react-hooks/exhaustive-deps": "error",
      "react-refresh/only-export-components": ["error", { allowConstantExport: true }],
    },
  },
  {
    files: ["demo/src/**/*.test.{ts,tsx}", "demo/src/main.demo.tsx"],
    rules: { "react-refresh/only-export-components": "off" },
  },
  { files: ["vite.config.ts", "demo/*.ts", "*.config.{js,ts}"], languageOptions: { globals: globals.node } },
);
