export const suspiciousWords = [
  "verify your account",
  "password expired",
  "urgent action",
  "login immediately",
  "account suspended",
  "confirm your identity",
];

export function findNearestPhrase(
  text: string,
  startingPosition: number,
): { phrase: string | null; position: number } {
  const lowerText = text.toLowerCase();

  let bestPhrase: string | null = null;
  let bestPosition = -1;

  suspiciousWords.forEach((phrase) => {
    const idx = lowerText.indexOf(phrase.toLowerCase(), startingPosition);

    if (idx === -1) {
      return;
    }

    if (bestPosition == -1 || idx < bestPosition) {
      bestPhrase = phrase;
      bestPosition = idx;
    }
  });
  return { phrase: bestPhrase, position: bestPosition };
}
