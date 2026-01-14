# Refactoring Plan: Unidirectional Data Flow Architecture

## Executive Summary
We are refactoring the application to a strict **Unidirectional Data Flow** architecture. Currently, Views (Windows/Panels) manage too much business logic and modify data states directly, leading to difficult synchronization issues.

**The New Flow:**
1.  **View** requests an **Edit Session** from `SharedData`.
2.  **View** (or Service) modifies **Model** properties inside the session.
3.  **Model** marks itself as dirty and reports to the session.
4.  **SharedData** closes the session -> Validates Data -> Broadcasts specific changed indices.
5.  **All Views** receive changed indices and redraw only those rows.

---

## The Architectural Rules
1.  **Models are Locked:** `AddressRow` objects must raise a `RuntimeError` if modified outside of an `edit_session`.
2.  **SharedData is the Gatekeeper:** Only `SharedAddressData` can open an `edit_session`. It Syncs -> Validates -> Broadcasts automatically when the session closes.
3.  **Services are Pure Logic:** Services (e.g., `BlockTagService`, `FillDownService`) perform complex data logic. They **never** import `tkinter` or interact with the UI.
4.  **Views are Passive:** Views never manually call `refresh()` or `validate()`. They only:
    *   Read state for display.
    *   Submit user intent via `edit_session`.
    *   Listen for `on_data_changed` signals.

---
