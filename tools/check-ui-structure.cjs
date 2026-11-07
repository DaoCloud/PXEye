"use strict";
// Static ownership checks only: no browser, service, or device operation.
const fs = require("node:fs");
const path = require("node:path");
const acorn = require("acorn");
const directory = path.resolve(__dirname, "../src/pxeye/web");
const html = fs.readFileSync(path.join(directory, "live.html"), "utf8");
const scripts = [...html.matchAll(/<script src="\/(.*?)"/g)].map(
  (match) => match[1].split("?")[0],
);
const globals = new Map();
const actions = new Map();
const pages = new Set();
const sources = [];

function walk(node, visit) {
  if (!node || typeof node !== "object") return;
  visit(node);
  for (const value of Object.values(node)) {
    if (Array.isArray(value)) value.forEach((child) => walk(child, visit));
    else if (value && typeof value === "object") walk(value, visit);
  }
}

for (const file of scripts) {
  const source = fs.readFileSync(path.join(directory, file), "utf8");
  sources.push(source);
  const ast = acorn.parse(source, { ecmaVersion: "latest" });
  for (const statement of ast.body) {
    const names =
      statement.type === "FunctionDeclaration"
        ? [statement.id.name]
        : statement.type === "VariableDeclaration"
          ? statement.declarations.flatMap((declaration) =>
              declaration.id.type === "Identifier" ? [declaration.id.name] : [],
            )
          : [];
    for (const name of names) {
      if (globals.has(name))
        throw Error(`Duplicate global ${name}: ${globals.get(name)}, ${file}`);
      globals.set(name, file);
    }
  }
  walk(ast, (node) => {
    if (node.type !== "CallExpression") return;
    if (node.callee.name === "registerActions") {
      const list = node.arguments[1];
      if (list.type !== "ArrayExpression" || !list.elements.length)
        throw Error(`Empty or dynamic action registration: ${file}`);
      const names = list.elements.map((element) => element.value);
      for (const name of names) {
        if (typeof name !== "string" || actions.has(name))
          throw Error(`Invalid or duplicate action ${name}: ${file}`);
        actions.set(name, file);
      }
      walk(node.arguments[2], (branch) => {
        if (
          branch.type === "SwitchCase" &&
          typeof branch.test?.value === "string" &&
          !names.includes(branch.test.value)
        )
          throw Error(`Unregistered action case ${branch.test.value}: ${file}`);
      });
    }
    if (node.callee.name === "registerPage") {
      const name = node.arguments[0].value;
      if (typeof name !== "string" || pages.has(name))
        throw Error(`Invalid or duplicate page ${name}: ${file}`);
      pages.add(name);
    }
  });
}
acorn.parse(sources.join("\n"), { ecmaVersion: "latest" });
console.log(
  JSON.stringify({
    scripts: scripts.length,
    globals: globals.size,
    actions: actions.size,
    pages: pages.size,
    status: "OK",
  }),
);
