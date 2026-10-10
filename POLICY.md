# Listing policy

Version 1, effective 2026-10-10.

This policy decides what appears in the TablePro integration directory at [tablepro.app/integrations](https://tablepro.app/integrations) and in this repository's published data.

## 1. What a listing means

A listing says the integration works with TablePro and meets this policy when it was reviewed. It is not an endorsement or a security audit. TablePro does not support third-party integrations; their authors do.

## 2. Labels

| Label | Meaning |
| --- | --- |
| Official | Built and maintained by TablePro. |
| Partner | Built by the company that makes the other product, verified by its GitHub organization or a DNS record on its domain. Only a maintainer assigns it. |
| Community | Built by anyone else. |

Archived is a status, not a label. Every entry shows **By &lt;publisher&gt;**.

## 3. Who may submit

The repository owner, a member of the owning organization, or a major contributor may open the pull request. A major contributor has at least a third of the commits of the top contributor. Anyone else needs the owner's consent in a comment on the pull request.

## 4. Documented interfaces only

An integration uses only the interfaces in the [developer docs](https://docs.tablepro.app/developers): the URL scheme, database URLs, the `tablepro` command, AppleScript, the MCP server, pairing and tokens, and Shortcuts.

It never reads, writes or deletes TablePro's private files: `connections.json`, `com.TablePro.plist`, `mcp-handshake.json`, TablePro's Keychain items or its SQLite databases. There is no exception and no grace period for new entries. CI scans open-source entries for these paths.

It finds TablePro by bundle identifier `com.TablePro`, not by a fixed install path.

## 5. License and source

An open-source entry has a LICENSE file with an SPDX license, and the license in the manifest matches it.

Closed source is allowed. The entry shows a **Closed source** label, and its disclosures are the publisher's word.

There is no minimum number of stars, installs or downloads.

## 6. Safety settings

An integration may open connections with Safe Mode below the user's default only for local development environments, such as `safeModeLevel=0` for a database on the same Mac. The entry discloses it, and the directory shows it on the entry page.

## 7. Disclosures

Every entry states:

- what it reads from TablePro (connection list, schema, row data) and what it writes (data, schema);
- whether it lowers Safe Mode;
- where it sends data: nowhere, this Mac only, or the internet, and to whom;
- whether it needs an account with another service, with a privacy policy link;
- whether it is free, has optional payment, or is paid.

A wrong disclosure is a policy violation.

## 8. Names and icons

- Name a third-party product **&lt;Name&gt; for TablePro**. **TablePro** alone and **TablePro for &lt;X&gt;** are reserved for TablePro's own products.
- The directory entry's name does not include TablePro, because the directory already says it.
- Do not use the TablePro app icon as your icon. A small TablePro badge in a corner of your own icon is fine.
- Do not call an entry official, verified or certified.
- The brand guidelines at [tablepro.app/brand](https://tablepro.app/brand) apply.

## 9. Entry content

- Text is English, plain, and factual. No HTML, no Markdown, no emoji.
- The summary is one sentence of 20 to 120 characters ending with a period.
- The icon is a 512x512 PNG of at most 512 KB. SVG is not accepted.
- Up to 4 screenshots, each a 1600x1000 PNG of at most 1 MB, each with alt text.
- One entry per pull request.

## 10. Security

Malware, credential theft, hidden data collection or a deceptive install link is removed at once, without the steps in section 12. Report it privately through [security advisories](https://github.com/TableProApp/integrations/security/advisories/new).

## 11. Review

- First response within 7 days. This is best effort.
- A pull request waiting on its author closes after 21 days without a reply. Open a new one at any time.
- CI checks the schema, links, license, repository state, images and ownership. A maintainer checks the rest of this policy by hand.

## 12. Maintenance and archiving

- A weekly check opens one issue listing broken links, moved or archived repositories, removed licenses and private-file access. It never edits or deletes an entry.
- When an entry breaks the policy or stops working, a maintainer contacts the author in the integration's own tracker. With no reply after 30 days, the entry is archived.
- An archived entry leaves the directory list and search. Its page stays, with a notice.
- An author can fix the problem and ask for the entry to return.

## 13. Entries listed before this policy

An entry listed before this policy took effect gets 60 days from the day its author is contacted to fix any problem in sections 4 to 8 that it already had. The entry page says so. If it is not fixed by then, the entry is archived.

## 14. Removal

An entry is removed when its publisher asks, or for the reasons in section 10. A removed slug is never reused, and its page answers 410 Gone.

## 15. Reports and appeals

Report a problem with an integration to its author first. If there is no reply after 7 days, or the problem is a policy violation, use **Report a listed integration** in this repository's issues.

To appeal an archive or removal, reply on the issue that recorded it, or fix the problem and open a new pull request.

## 16. Links

Links to Community entries carry `rel="ugc nofollow"`. TablePro never asks a listed project to link back.

## 17. Data and images

Manifest text is released under CC0-1.0 (see LICENSE-DATA). Icons and screenshots stay their owners' property. Submitting them lets TablePro show them in the directory and in this repository's published data.

## 18. Changes to this policy

Each change gets a new version and date here, and is announced in the repository. Existing entries must meet a new rule within 60 days of its effective date.
