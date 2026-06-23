const fs = require('fs');
const path = require('path');

const publicDir = path.join(__dirname, '..', 'public');
const templatePath = path.join(publicDir, 'sw.js.tpl');
const outputPath = path.join(publicDir, 'sw.js');

const pkg = require(path.join(__dirname, '..', 'package.json'));
const timestamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, -5);
const cacheName = `nukelab-${pkg.version}-${timestamp}`;

const template = fs.readFileSync(templatePath, 'utf8');
const generated = template.replace(/__CACHE_NAME__/g, cacheName);

fs.writeFileSync(outputPath, generated, 'utf8');
console.log(`Generated ${outputPath} with CACHE_NAME=${cacheName}`);
