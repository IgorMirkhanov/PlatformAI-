/**
 * Company / operator identity for legal pages.
 * Fill via NEXT_PUBLIC_* before GA; placeholders stay visible until then.
 */
export const COMPANY = {
  brand: "MP.AI",
  legalName:
    process.env.NEXT_PUBLIC_COMPANY_LEGAL_NAME?.trim() ||
    "ТОО «MP.AI Platform» (уточните перед GA)",
  bin: process.env.NEXT_PUBLIC_COMPANY_BIN?.trim() || "[БИН — заполнить]",
  address:
    process.env.NEXT_PUBLIC_COMPANY_ADDRESS?.trim() ||
    "[Юридический адрес — заполнить], Республика Казахстан",
  city: process.env.NEXT_PUBLIC_COMPANY_CITY?.trim() || "Алматы",
  jurisdiction:
    process.env.NEXT_PUBLIC_COMPANY_JURISDICTION?.trim() ||
    "Республика Казахстан (Закон РК «О персональных данных и их защите»)",
} as const;

export function companyLine(): string {
  return `${COMPANY.legalName}, БИН ${COMPANY.bin}, ${COMPANY.address}`;
}
