import React from 'react';

// Tiny markdown renderer for reports and export.md. It builds React elements (never raw
// HTML), so everything in the source text is escaped by React.

const INLINE = /(\*\*[^*]+\*\*|`[^`]+`|\[[^\]]+\]\(https?:\/\/[^)\s]+\)|_[^_\s][^_]*_|https?:\/\/[^\s)<]+)/g;

function renderInline(text, keyPrefix = 'i') {
  const out = [];
  let last = 0;
  let n = 0;
  for (const match of text.matchAll(INLINE)) {
    const token = match[0];
    if (match.index > last) out.push(text.slice(last, match.index));
    const key = `${keyPrefix}-${n++}`;
    if (token.startsWith('**')) {
      out.push(<strong key={key} className="font-semibold text-slate-900">{token.slice(2, -2)}</strong>);
    } else if (token.startsWith('`')) {
      out.push(<code key={key} className="px-1 py-0.5 rounded bg-slate-100 text-[12px] text-slate-800">{token.slice(1, -1)}</code>);
    } else if (token.startsWith('[')) {
      const [, label, href] = token.match(/^\[([^\]]+)\]\((.+)\)$/);
      out.push(<a key={key} href={href} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">{label}</a>);
    } else if (token.startsWith('_')) {
      out.push(<em key={key}>{token.slice(1, -1)}</em>);
    } else {
      out.push(<a key={key} href={token} target="_blank" rel="noreferrer" className="text-blue-600 hover:underline break-all">{token}</a>);
    }
    last = match.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const splitRow = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').map((c) => c.trim());
const isTableSep = (line) => /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/.test(line || '');
const LIST_ITEM = /^\s*([-*+]|\d+[.)])\s+/;

function parseBlocks(source) {
  const lines = String(source || '').replace(/\r\n/g, '\n').split('\n');
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) { i++; continue; }

    if (/^```/.test(line)) {
      const code = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) code.push(lines[i++]);
      i++;
      blocks.push({ type: 'code', text: code.join('\n') });
      continue;
    }
    const heading = line.match(/^(#{1,4})\s+(.*)$/);
    if (heading) { blocks.push({ type: 'h', level: heading[1].length, text: heading[2] }); i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { blocks.push({ type: 'hr' }); i++; continue; }

    if (line.includes('|') && isTableSep(lines[i + 1])) {
      const head = splitRow(line);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]));
      blocks.push({ type: 'table', head, rows });
      continue;
    }
    if (LIST_ITEM.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      const items = [];
      while (i < lines.length && LIST_ITEM.test(lines[i])) items.push(lines[i++].replace(LIST_ITEM, ''));
      blocks.push({ type: 'list', ordered, items });
      continue;
    }
    if (/^>\s?/.test(line)) {
      const quote = [];
      while (i < lines.length && /^>\s?/.test(lines[i])) quote.push(lines[i++].replace(/^>\s?/, ''));
      blocks.push({ type: 'quote', text: quote.join(' ') });
      continue;
    }
    const para = [line];
    i++;
    while (
      i < lines.length
      && lines[i].trim()
      && !/^(#{1,4}\s|```|>\s?)/.test(lines[i])
      && !LIST_ITEM.test(lines[i])
      && !(lines[i].includes('|') && isTableSep(lines[i + 1]))
    ) {
      para.push(lines[i++]);
    }
    blocks.push({ type: 'p', text: para.join(' ') });
  }
  return blocks;
}

const HEADING_CLASS = {
  1: 'text-xl font-extrabold text-slate-900 mt-5 first:mt-0 tracking-tight pb-2 border-b border-slate-100',
  2: 'text-base font-bold text-slate-900 mt-4 first:mt-0',
  3: 'text-sm font-bold text-blue-950 mt-3.5 first:mt-0',
  4: 'text-xs font-bold uppercase tracking-wider text-slate-500 mt-3 first:mt-0',
};

const Markdown = ({ source }) => {
  const blocks = parseBlocks(source);
  return (
    <div className="text-sm text-slate-700 space-y-2.5 leading-relaxed break-words">
      {blocks.map((block, index) => {
        const key = `b${index}`;
        switch (block.type) {
          case 'h': {
            const Tag = `h${Math.min(block.level + 1, 6)}`;
            return <Tag key={key} className={HEADING_CLASS[block.level]}>{renderInline(block.text, key)}</Tag>;
          }
          case 'hr':
            return <hr key={key} className="border-t border-slate-200 my-4" />;
          case 'code':
            return <pre key={key} className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 text-xs font-mono overflow-x-auto text-slate-800">{block.text}</pre>;
          case 'quote':
            return (
              <blockquote key={key} className="border-l-4 border-blue-500 bg-blue-50/70 rounded-r-xl px-4 py-2.5 my-3 text-slate-800 text-xs sm:text-sm font-medium shadow-2xs">
                {renderInline(block.text, key)}
              </blockquote>
            );
          case 'list': {
            const List = block.ordered ? 'ol' : 'ul';
            return (
              <List key={key} className={`${block.ordered ? 'list-decimal' : 'list-disc'} pl-5 space-y-1.5 my-2`}>
                {block.items.map((item, n) => <li key={`${key}-${n}`} className="text-slate-700">{renderInline(item, `${key}-${n}`)}</li>)}
              </List>
            );
          }
          case 'table':
            return (
              <div key={key} className="overflow-x-auto border border-slate-200/90 rounded-2xl shadow-2xs my-3.5 bg-white">
                <table className="min-w-full text-xs">
                  <thead className="bg-slate-50/90 border-b border-slate-200 text-slate-700">
                    <tr>
                      {block.head.map((cell, n) => (
                        <th key={n} className="text-left font-bold uppercase tracking-wider text-[11px] px-3.5 py-2.5 whitespace-nowrap">{renderInline(cell, `${key}h${n}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {block.rows.map((row, r) => (
                      <tr key={r} className="border-t border-slate-100 hover:bg-blue-50/30 transition-colors">
                        {row.map((cell, n) => (
                          <td key={n} className="px-3.5 py-2.5 text-slate-700 align-top">{renderInline(cell, `${key}r${r}c${n}`)}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          default:
            return <p key={key}>{renderInline(block.text, key)}</p>;
        }
      })}
    </div>
  );
};

export default Markdown;
