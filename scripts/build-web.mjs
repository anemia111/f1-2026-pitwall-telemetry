import { mkdir, readFile, writeFile, copyFile } from 'node:fs/promises';
import { rollup } from '@rollup/wasm-node';
import commonjs from '@rollup/plugin-commonjs';
import { nodeResolve } from '@rollup/plugin-node-resolve';
import replace from '@rollup/plugin-replace';

const target = 'web/dist';
await mkdir(`${target}/assets`, { recursive: true });
const bundle = await rollup({
  input: 'build/web/main.js',
  plugins: [
    replace({ preventAssignment: true, 'process.env.NODE_ENV': JSON.stringify('production') }),
    nodeResolve({ browser: true }),
    commonjs(),
  ],
  onwarn(warning, warn) {
    if (warning.code !== 'MODULE_LEVEL_DIRECTIVE') warn(warning);
  },
});
try {
  await bundle.write({ file: `${target}/assets/pitwall.js`, format: 'es' });
} finally {
  await bundle.close();
}
await copyFile('web/src/style.css', `${target}/assets/pitwall.css`);
const html = await readFile('web/index.html', 'utf8');
await writeFile(`${target}/index.html`, html.replace('/src/main.tsx', '/assets/pitwall.js')
  .replace('</head>', '  <link rel="stylesheet" href="/assets/pitwall.css" />\n  </head>'));
