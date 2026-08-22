/**
 * Minimal, safe Markdown renderer for Copilot replies.
 *
 * Deliberately not `dangerouslySetInnerHTML` and not a full Markdown library:
 * LLM output is untrusted text, and injecting it as HTML is an XSS path. This
 * tokenises a small, known subset (headings, lists, bold, italic, inline code,
 * fenced code, tables) and renders it as React elements, so nothing the model
 * emits can become live markup.
 */
import { Fragment } from "react";

export default function Markdown({ content }) {
  if (!content) return null;
  return <div className="space-y-2 text-base leading-relaxed">{renderBlocks(String(content))}</div>;
}

function renderBlocks(text) {
  const lines = text.split("\n");
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];

    // Fenced code block
    if (line.trimStart().startsWith("```")) {
      const collected = [];
      index += 1;
      while (index < lines.length && !lines[index].trimStart().startsWith("```")) {
        collected.push(lines[index]);
        index += 1;
      }
      index += 1; // consume closing fence
      blocks.push(
        <pre
          key={blocks.length}
          className="overflow-x-auto rounded-md border border-line bg-canvas p-2.5 text-xs"
        >
          <code>{collected.join("\n")}</code>
        </pre>,
      );
      continue;
    }

    // Table: a header row followed by a |---|---| separator
    if (line.includes("|") && lines[index + 1] && /^\s*\|?[\s:-]*\|[\s:|-]*$/.test(lines[index + 1])) {
      const header = splitRow(line);
      index += 2;
      const rows = [];
      while (index < lines.length && lines[index].includes("|")) {
        rows.push(splitRow(lines[index]));
        index += 1;
      }
      blocks.push(
        <div key={blocks.length} className="overflow-x-auto">
          <table className="w-full border-collapse text-sm">
            <thead>
              <tr>
                {header.map((cell, cellIndex) => (
                  <th
                    key={cellIndex}
                    scope="col"
                    className="border-b border-line px-2 py-1 text-left font-semibold"
                  >
                    {renderInline(cell)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, rowIndex) => (
                <tr key={rowIndex}>
                  {row.map((cell, cellIndex) => (
                    <td key={cellIndex} className="border-b border-line px-2 py-1">
                      {renderInline(cell)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>,
      );
      continue;
    }

    // Heading
    const heading = /^(#{1,4})\s+(.*)$/.exec(line);
    if (heading) {
      blocks.push(
        <p key={blocks.length} className="font-semibold text-ink">
          {renderInline(heading[2])}
        </p>,
      );
      index += 1;
      continue;
    }

    // List (bulleted or numbered)
    if (/^\s*([-*+]|\d+\.)\s+/.test(line)) {
      const items = [];
      const ordered = /^\s*\d+\./.test(line);
      while (index < lines.length && /^\s*([-*+]|\d+\.)\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*([-*+]|\d+\.)\s+/, ""));
        index += 1;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag
          key={blocks.length}
          className={`ml-4 space-y-0.5 ${ordered ? "list-decimal" : "list-disc"}`}
        >
          {items.map((item, itemIndex) => (
            <li key={itemIndex}>{renderInline(item)}</li>
          ))}
        </ListTag>,
      );
      continue;
    }

    // Blank line
    if (!line.trim()) {
      index += 1;
      continue;
    }

    // Paragraph: absorb consecutive non-special lines
    const paragraph = [];
    while (
      index < lines.length &&
      lines[index].trim() &&
      !/^(#{1,4})\s+/.test(lines[index]) &&
      !/^\s*([-*+]|\d+\.)\s+/.test(lines[index]) &&
      !lines[index].trimStart().startsWith("```")
    ) {
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push(<p key={blocks.length}>{renderInline(paragraph.join(" "))}</p>);
  }

  return blocks;
}

function splitRow(line) {
  return line.replace(/^\s*\|/, "").replace(/\|\s*$/, "").split("|").map((cell) => cell.trim());
}

/**
 * Inline formatting. Everything not matched by the pattern is emitted as a plain
 * string, so unrecognised syntax degrades to visible text rather than markup.
 */
function renderInline(text) {
  const pattern = /(\*\*[^*]+\*\*|\*[^*]+\*|`[^`]+`)/g;
  const parts = String(text).split(pattern).filter(Boolean);

  return parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return <strong key={index} className="font-semibold">{part.slice(2, -2)}</strong>;
    }
    if (part.startsWith("*") && part.endsWith("*") && part.length > 2) {
      return <em key={index}>{part.slice(1, -1)}</em>;
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={index} className="rounded bg-canvas px-1 py-0.5 font-mono text-xs">
          {part.slice(1, -1)}
        </code>
      );
    }
    return <Fragment key={index}>{part}</Fragment>;
  });
}
