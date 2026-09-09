/**
 * EarSight design tokens — one dark surface, editor-shell.
 *
 * The product is a media tool, so the interface is an editor: docked
 * panels around a canvas, with a timeline across the bottom. Everything
 * sits on near-black; amber is the only accent and always means
 * "this is ours — a silence we may speak into".
 *
 * Text contrast against bg (#08080A), WCAG AA needs 4.5:1:
 *   text  #EDEAE3 → 17.8:1
 *   dim   #9C988E →  6.9:1
 *   faint #8A857B →  5.4:1   (the smallest label tier; nothing dimmer is text)
 *   amber #F5A623 →  9.9:1
 *   ok    #5CBE8D →  8.8:1
 *   onAmber #150F02 on amber → 9.4:1
 */

export const c = {
  bg: '#08080A',
  panel: '#0E0E12',
  raised: '#15151B',
  hi: '#1C1C24',
  rule: '#22222A',
  rule2: '#2F2F39',

  text: '#EDEAE3',
  dim: '#9C988E',
  faint: '#8A857B',

  amber: '#F5A623',
  amberDim: '#7E5814',
  amberWash: 'rgba(245,166,35,0.055)',
  amberEdge: 'rgba(245,166,35,0.32)',
  amberFill: 'rgba(245,166,35,0.20)',
  amberFillSel: 'rgba(245,166,35,0.34)',
  onAmber: '#150F02',

  blue: '#6E7C93',
  ok: '#5CBE8D',
  err: '#E5776B',
} as const;

export const mono =
  "ui-monospace, SFMono-Regular, 'SF Mono', Menlo, monospace";
export const sans =
  "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif";

/** Small uppercase tracking label. */
export const label: React.CSSProperties = {
  fontFamily: mono,
  fontSize: 9.5,
  letterSpacing: '0.18em',
  textTransform: 'uppercase',
  color: c.faint,
};
