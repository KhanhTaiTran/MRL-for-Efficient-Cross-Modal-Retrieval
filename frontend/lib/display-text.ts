// Decode catalog metadata as plain text. React still escapes the returned string.
const entities: Record<string, string> = {
  amp: "&",
  apos: "'",
  quot: '"',
  lt: "<",
  gt: ">",
  nbsp: " ",
  rsquo: "’",
  lsquo: "‘",
  rdquo: "”",
  ldquo: "“",
  ndash: "–",
  mdash: "—",
  hellip: "…",
  eacute: "é",
  Eacute: "É",
  egrave: "è",
  ecirc: "ê",
  aacute: "á",
  agrave: "à",
  acirc: "â",
  auml: "ä",
  aring: "å",
  ouml: "ö",
  uuml: "ü",
  ccedil: "ç",
  ntilde: "ñ",
  szlig: "ß",
  trade: "™",
};
export function displayText(value: string | null | undefined): string {
  let result = value || "";
  for (let pass = 0; pass < 2; pass++) {
    result = result.replace(
      /&(#x[\da-f]+|#\d+|[a-z]+);/gi,
      (entity, code: string) => {
        if (!code.startsWith("#")) return entities[code] ?? entity;
        const hexadecimal = code[1]?.toLowerCase() === "x";
        const point = Number.parseInt(
          code.slice(hexadecimal ? 2 : 1),
          hexadecimal ? 16 : 10,
        );
        return point > 0 &&
          point <= 0x10ffff &&
          !(point >= 0xd800 && point <= 0xdfff)
          ? String.fromCodePoint(point)
          : entity;
      },
    );
  }
  return result;
}
export function categoryLabel(value: string): string {
  return displayText(value)
    .toLowerCase()
    .replace(/(^|[\s_-])\p{L}/gu, (part) => part.toUpperCase())
    .replace(/_/g, " ");
}
