#!/usr/bin/env node
// Appends a one-line entry to docs/bob/session-log.md on every session start.
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { join } from "node:path";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;

let input;
try {
  input = JSON.parse(raw);
} catch {
  process.exit(0);
}

const cwd = input.cwd ?? process.cwd();
const logDir = join(cwd, "docs", "bob");
const logFile = join(logDir, "session-log.md");

try {
  mkdirSync(logDir, { recursive: true });
} catch {}

const now = new Date().toISOString();
const source = input.source ?? "unknown";
const sessionId = input.session_id ?? "unknown";

let existing = "";
try {
  existing = readFileSync(logFile, "utf8");
} catch {}

if (!existing) {
  existing = "# EARSIGHT — Bob Session Log\n\n| Timestamp | Session ID | Event |\n|---|---|---|\n";
}

const line = `| ${now} | ${sessionId} | ${source} |\n`;
writeFileSync(logFile, existing + line, "utf8");
