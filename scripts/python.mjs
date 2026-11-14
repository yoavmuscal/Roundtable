#!/usr/bin/env node
/* Cross-platform Python launcher for npm scripts (Windows: python, macOS: python3). */
import { spawn } from 'node:child_process';

const executable = process.platform === 'win32' ? 'python' : 'python3';
const child = spawn(executable, process.argv.slice(2), { stdio: 'inherit' });
child.on('exit', (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code ?? 1);
});
