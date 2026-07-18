export function normalize(text: string): { normalized: string; map: number[] } {
  let normalized = "";
  const map: number[] = [];
  let previousWasWhitespace = false;

  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    const isWhiteSpace = /\s/.test(char);

    if (isWhiteSpace) {
      if (previousWasWhitespace) {
        continue;
      } else if (!previousWasWhitespace) {
        normalized += " ";
        map.push(i);
        previousWasWhitespace = true;
      }
    } else if (!isWhiteSpace) {
      normalized += char;
      map.push(i);
      previousWasWhitespace = false;
    }
  }
  return { normalized, map };
}
