// Next 16 fournit une flat config ESLint native (Linter.Config[]).
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextCoreWebVitals,
  { ignores: [".next/**", "node_modules/**"] },
];

export default eslintConfig;
