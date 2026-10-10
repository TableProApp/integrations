<!--
Title: feat(<slug>): add <Name> for a new entry, fix(<slug>): <what changed> for an update.
One entry per pull request. Read POLICY.md first.
-->

## Entry

<!-- Slug, and one line on what the integration does. -->

## Checklist

- [ ] I read the [listing policy](https://github.com/TableProApp/integrations/blob/main/POLICY.md) and the entry follows it.
- [ ] `python3 scripts/validate.py` passes on my machine.
- [ ] I am the publisher, a member of the publishing organization, or a major contributor. If not, the owner gave consent in a comment on this pull request (link it below).
- [ ] The integration uses only documented TablePro interfaces. It never reads `connections.json`, `com.TablePro.plist`, `mcp-handshake.json`, TablePro's Keychain items or its SQLite files.
- [ ] The name does not include TablePro, and the icon is not the TablePro app icon. A small TablePro badge in a corner is fine.
- [ ] The disclosures are true: what it reads and writes, Safe Mode, network, account, payment.
- [ ] I own the icon and screenshots, or may use them, and I let TablePro show them in the directory and its published data.
- [ ] I wrote this pull request myself. If an AI tool helped, I say how below and I checked every claim.

## Consent or notes

<!-- Optional. A link to the owner's consent comment, or anything the reviewer should know. -->
