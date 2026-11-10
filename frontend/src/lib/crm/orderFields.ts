/** Fixed deal order fields stored in ``custom_fields`` (plus ``assigned_user_id``). */

export const DEAL_ORDER_FIELD_KEYS = [
  "phone",
  "ordered_items",
  "order_date",
  "manufacturing_date",
  "install_object",
  "install_deadline",
] as const;

export type DealOrderFieldKey = (typeof DEAL_ORDER_FIELD_KEYS)[number];

export type DealOrderDraft = Record<DealOrderFieldKey, string>;

export function emptyOrderDraft(): DealOrderDraft {
  return {
    phone: "",
    ordered_items: "",
    order_date: "",
    manufacturing_date: "",
    install_object: "",
    install_deadline: "",
  };
}

export function orderDraftFromDeal(deal: {
  contact?: { phone?: string | null } | null;
  custom_fields?: Record<string, unknown> | null;
}): DealOrderDraft {
  const fields = deal.custom_fields || {};
  const phoneFromFields =
    fields.phone == null ? "" : String(fields.phone).trim();
  const phoneFromContact = (deal.contact?.phone || "").trim();
  return {
    phone: phoneFromFields || phoneFromContact,
    ordered_items:
      fields.ordered_items == null ? "" : String(fields.ordered_items),
    order_date: fields.order_date == null ? "" : String(fields.order_date),
    manufacturing_date:
      fields.manufacturing_date == null
        ? ""
        : String(fields.manufacturing_date),
    install_object:
      fields.install_object == null ? "" : String(fields.install_object),
    install_deadline:
      fields.install_deadline == null ? "" : String(fields.install_deadline),
  };
}
