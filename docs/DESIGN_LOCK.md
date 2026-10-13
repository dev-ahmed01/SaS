# Approved UI baseline — do not redesign without sign-off

The approved **two desktop visual boards** from the October 12, 2026 Sponsor a Salah design review are the source of truth. The first includes the login, Dashboard, Prospects Add/Inactive/All and Promoters Add/Active/All screens. The second includes Collections Add/Active/All, Payouts Add/Active/All, Reminders landing/WhatsApp/Email screens. UI reproduction occurs in Phase 02 and module phases; Phase 01 shows only the application foundation.

| Element | Locked specification |
| --- | --- |
| Main headings | Bricolage Grotesque 700 |
| Section/card headings | Bricolage Grotesque 600 |
| Body / descriptions | Poppins 400 |
| Navigation, buttons, labels | Poppins 500 |
| Tables | Poppins 400–500 |
| Money | Poppins 600 |
| Palette | Warm white, pastel mint, dark forest green, subtle grey borders |
| Navigation | Desktop left sidebar, NO bottom navigation |
| Module tabs | Prospects: Add/Inactive/All; Promoters: Add/Active/All; Collections: Add/Active/All; Payouts: Add/Active/All |
| Reminders | Exactly two entry cards: WhatsApp and Email; WhatsApp first |
| Dashboard | Built last, driven from verified records |

Do not invent additional public pages, analytics modules, artificial payment success data, or ornamental marketing sections. The base component tokens are in `apps/web/app/globals.css`. In later phases, add visual regression screenshots against the provided approved boards.
