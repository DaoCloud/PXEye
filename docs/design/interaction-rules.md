# Interaction rules

**English** · [简体中文](interaction-rules.zh-CN.md) · [Design documents](README.md)

Rules to follow when adding or changing a page. They describe current practice, derived from the existing pages. Two rules in section 2 (a column with no value is not shown; a page with nothing to show explains what it covers) and all of section 6 were set with the device status pages, and earlier pages do not all follow them yet. Where a rule and a page disagree, decide which of the two should change instead of adding a third variant.

## 1. Page ownership

Each piece of data has one place where it is maintained. Other pages reference it or link to it; they do not add a second editor.

| Navigation | Page | Data and operations it owns |
| --- | --- | --- |
| Overview | Rack topology | Devices by rack; manual display order |
| Installation | Installation tasks | Device selection, checks, confirmation, execution, logs and acceptance |
| Resources | Device management | Device planning, discovery, enrollment, addresses, rack assignment, per-device installation settings |
| Resources | Device management → Servers / Switches / Power shelves | Read-only: the operational status NICo reports. Owns no editable data |
| Resources | Instance management | Instance inspection and release |
| Resources | Operating systems | ISOs, boot artifacts, OS definitions |
| Resources | Network management | Segments, address ranges, network services |
| Configuration | Installation profiles | Reusable OS, disk, partition and login defaults |
| Configuration | Site settings | Core connection, site discovery, credentials, concurrency |
| Configuration | NICo cluster | Control-plane deployment and status |

- Decide which group a new page belongs to. If it fits as a tab or dialog of an existing page, do not add a menu entry.
- A view that belongs to a page is a second-level entry under it, not a sibling.
- When a read-only view needs editing, it opens the existing dialog of the page that owns the data.

## 2. Page structure

- A page starts with a title, a one-sentence description and its action buttons. The description says what the page is for, not how it works.
- Lists are tables, details and editing are dialogs, multi-step operations are wizards.
- One primary button per action area.
- Filters sit above the table. Filtering and searching keep the current selection; typing in the search field keeps the cursor position.
- A column with no value in any row is not shown.
- A page with nothing to show on the current site explains what it covers and where to go next instead of showing an empty table.
- Raw states, API responses and logs go into details. The main content shows the device, scope, stage, reason and the place to act.

## 3. Wording

- Describe pages by function, fields by what is entered, and messages by the result and the next step.
- Labels are short nouns; buttons are explicit actions.
- Terms are consistent across the console: hostname, management address, BMC address, rack, power shelf, installation profile. The interface currently uses Simplified Chinese; field names and native resource names such as `rack_id` and `Rack` are not translated.
- MAC addresses, CIDRs, UUIDs, resource IDs and state-machine state names are shown as they are, not translated into another concept.
- Input format, unit and the meaning of an empty value are written next to the field.
- Quantities belong with counts, the query time with the query result, the failure reason with the item that failed.
- Remove repeated process descriptions, long hints that restate a button, and status text that reports no actual result.

## 4. State and evidence

- State is expressed with colour and text together. Green is normal or done, amber needs attention or is in progress, red is failed, grey is unknown or not started.
- No data is not the same as healthy. A missing report is shown as not reported, never as healthy or online.
- Keep three kinds of information apart: the intended value someone entered, the actual value read back, and the state the NICo state machine reports. They are shown separately and do not stand in for one another.
- A state name is not a conclusion. Whether something needs attention comes from the system's own signals (a failed handler run, a time limit exceeded, a health alert), not from interpreting the name.
- Information that was read back names its source and time.
- When one kind of data cannot be read, say which one and show the rest.
- An accepted request is not a completed operation; registered is not ready; a reachable port is not a passed acceptance.

## 5. Dangerous operations

- An operation that changes a device or a shared resource names the object and the effect when asking for confirmation: which system disk is overwritten, whether all disks are cleaned, whether the device restarts, which address changes, which instance is released.
- Shortening text never removes a required confirmation, validation or backend check.
- An external write is recorded as sent before it is sent. When the result is unknown, read back first; do not resend automatically.
- After a failure, keep the evidence and the reason and offer a specific recovery entry. Do not offer a one-click cancel or retry that cannot be honoured.
- Batch operations report per device; one failure does not change the result of the others.

## 6. Read-only and preview features

- A read-only view sends no write request. Its only actions are refresh, filtering and opening entries that already exist on other pages.
- A preview feature is controlled by a site switch. With the switch off, the navigation, the API and the existing pages behave exactly as they do without the feature.
- A read-only observer instance shows a permanent marker, and its backend rejects write requests; hiding buttons is not the control.

## 7. Visual design and accessibility

- Reuse the existing components: page heading, table, status badge, definition list, note, dialog, filter row, summary strip. Do not introduce a colour or component for a single page.
- Identifiers, MAC addresses, IP addresses and IDs use the monospace font.
- While a dialog is open the background is inert, and focus moves into the dialog and stays within it. Dynamic results are announced through the live region; errors use alert semantics.
- On narrow screens forms become a single column and tables scroll horizontally inside their own area; the page itself does not scroll sideways.
- Respect the reduced-motion preference.

## 8. Checklist for a new page

1. Which page maintains the data? Does this page own it or reference it?
2. Does each column and item have a value on a real site? What happens to those that do not?
3. What is the first thing a user can do on arriving at this page?
4. Does state come from the system's signals or from our own reading of a state name?
5. Is there a write? If so, what are the object, the effect and the confirmation?
6. With the switch off, are existing pages entirely unaffected?
7. Does the wording use the existing terms?
8. For a rack operations feature, was the implementation status of its functional area updated in the [capability requirements](rack-operations-requirements.md)?
