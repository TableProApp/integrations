# Listing an integration

Read the [listing policy](POLICY.md) first. Open one pull request per entry.

## Add an entry

1. Fork this repository and create `integrations/<slug>/`. The slug is lowercase words joined by hyphens, does not contain `tablepro`, and never changes.
2. Copy `integration.json` from an entry like yours, or from `scripts/tests/fixtures/integrations/`, and edit it. The `$schema` line gives your editor completion and checks.
3. Add `icon.png`: 512x512 PNG, at most 512 KB, not the TablePro app icon.
4. Optional: up to four `screenshot-N.png` files, 1600x1000 PNG, at most 1 MB each, listed under `screenshots` with alt text.
5. Run the checks with Python 3.10 or later:

   ```bash
   python3 -m venv .venv
   .venv/bin/pip install --require-hashes -r requirements.txt
   .venv/bin/python scripts/validate.py
   ```

6. Open the pull request and fill in the checklist.

Set `addedAt` and `lastVerifiedAt` to today. A maintainer updates `lastVerifiedAt` after checking the integration.

The [publishing guide](https://docs.tablepro.app/developers/submit) walks through the fields.

## Fields that need a maintainer

`tier`, `compliance`, `lastVerifiedAt`, `source.repoId` and `publisher.githubId` change only in a maintainer's pull request. `tier: official` needs a publisher in `curation/official-publishers.json`, and `tier: partner` needs a row in `curation/partners.json`.

## Update an entry

Change the files in your entry's folder and open a pull request. The slug and `addedAt` stay as they are.

## Archive or remove an entry

Open a **Request removal or archive** issue. A maintainer makes the change and records it.

## Not the author?

Open a **Suggest an integration** issue instead. We ask the author before listing it.
