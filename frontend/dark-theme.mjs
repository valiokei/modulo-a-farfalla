// Build-time dark theme: mirrors every colour declaration of the app's CSS
// under :root[data-theme=dark], converting literal colours by their role.
// The source CSS stays untouched (the light theme is byte-for-byte the same);
// each mirrored rule sits right after its original, so the cascade order and
// relative specificity of the light theme are preserved in the dark one.
const COLOR_PROPS = /^(color|background|background-color|background-image|border|border-(top|right|bottom|left)(-color)?|border-color|outline|outline-color|box-shadow|fill|stroke|caret-color|text-decoration-color|accent-color|column-rule|text-shadow)$/;
const LITERAL = /#[0-9a-fA-F]{3,8}\b|rgba?\([^)]*\)/g;
// Custom properties that carry theme colours (their role decides the mapping).
const VAR_ROLES = {
  '--ink': 'fg', '--muted': 'fg', '--line': 'line', '--card': 'bg',
  '--workspace-bg': 'bg', '--workspace-ink': 'fg', '--workspace-subtle': 'fg', '--workspace-border': 'line',
  '--dash-surface': 'bg', '--dash-grid': 'line', '--dash-avg': 'fg',
};

function parse(hex) {
  if (hex.startsWith('rgb')) {
    const [r, g, b, a = 1] = hex.match(/[\d.]+/g).map(Number);
    return [r / 255, g / 255, b / 255, a];
  }
  let h = hex.slice(1);
  if (h.length <= 4) h = [...h].map((c) => c + c).join('');
  const n = (i) => parseInt(h.slice(i, i + 2), 16) / 255;
  return [n(0), n(2), n(4), h.length === 8 ? n(6) : 1];
}
function toHsl([r, g, b]) {
  const max = Math.max(r, g, b), min = Math.min(r, g, b), l = (max + min) / 2;
  if (max === min) return [0, 0, l];
  const d = max - min, s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  const h = max === r ? (g - b) / d + (g < b ? 6 : 0) : max === g ? (b - r) / d + 2 : (r - g) / d + 4;
  return [h * 60, s, l];
}
function hsl(h, s, l, a) {
  const f = (v) => Math.round(Math.min(1, Math.max(0, v)) * 1000) / 10;
  return a < 1 ? `hsl(${Math.round(h)} ${f(s)}% ${f(l)}% / ${Math.round(a * 100) / 100})` : `hsl(${Math.round(h)} ${f(s)}% ${f(l)}%)`;
}
export function convert(literal, role) {
  const [r, g, b, a] = parse(literal);
  const [h, s, l] = toHsl([r, g, b]);
  if (role === 'fg') {
    // Text/icon colours must stay readable on dark surfaces: dark accents
    // (brand green, link blue, error red) are lifted to a light tint of the
    // same hue; light text (on accent buttons) is left alone.
    if (l >= 0.62) return literal;
    if (s > 0.25) return hsl(h, Math.min(1, s * 0.85 + 0.1), 0.68, a);
    return hsl(h, Math.min(s, 0.5) * 0.7, 0.93 - l * 0.55, a);
  }
  // Saturated mid-tone accents (brand green, lime, warning amber, category
  // colours) read fine on both themes as fills: keep them.
  if (s > 0.45 && l > 0.25 && l < 0.75) return literal;
  if (role === 'shadow') return l < 0.5 ? literal : hsl(h, s * 0.4, 0.2, a);
  if (role === 'bg') {
    if (l <= 0.5) return literal; // already-dark surfaces (video, accent buttons)
    return hsl(h, s * 0.45, 0.115 + (1 - l) * 0.75, a);
  }
  // line
  return l > 0.5 ? hsl(h, s * 0.35, 0.22 + (1 - l) * 0.45, a) : hsl(h, s * 0.4, 0.55, a);
}
function roleOf(prop) {
  if (prop === 'box-shadow' || prop === 'text-shadow') return 'shadow';
  if (prop.startsWith('background')) return 'bg';
  if (prop.startsWith('border') || prop.startsWith('outline') || prop === 'column-rule') return 'line';
  return 'fg';
}
function scope(selector) {
  return selector.split(',').map((part) => {
    const sel = part.trim();
    if (sel.startsWith(':root')) return ':root[data-theme=dark]' + sel.slice(5);
    if (sel === 'html') return ':root[data-theme=dark]';
    return ':root[data-theme=dark] ' + sel;
  }).join(',');
}

export default function darkTheme() {
  return {
    postcssPlugin: 'modulo-dark-theme',
    OnceExit(root) {
      root.walkRules((rule) => {
        if (rule.parent?.type === 'atrule' && /keyframes$/i.test(rule.parent.name)) return;
        if (rule.selector.includes('data-theme')) return;
        const decls = [];
        rule.each((node) => {
          if (node.type !== 'decl') return;
          const prop = node.prop.toLowerCase();
          if (prop.startsWith('--')) {
            const role = VAR_ROLES[prop];
            if (role && LITERAL.test(node.value)) decls.push(node.clone({value: node.value.replace(LITERAL, (m) => convert(m, role))}));
            LITERAL.lastIndex = 0;
            return;
          }
          if (!COLOR_PROPS.test(prop)) return;
          const role = roleOf(prop);
          // Mirror non-literal values too (transparent, var(), inherit), so a
          // mirrored literal from a broader rule can never beat them.
          decls.push(node.clone({value: node.value.replace(LITERAL, (m) => convert(m, role))}));
        });
        if (!decls.length) return;
        const mirror = rule.clone({selector: scope(rule.selector), nodes: []});
        decls.forEach((d) => mirror.append(d));
        rule.after(mirror);
      });
      root.append({selector: ':root[data-theme=dark]', nodes: [{type: 'decl', prop: 'color-scheme', value: 'dark'}]});
    },
  };
}
darkTheme.postcss = true;
