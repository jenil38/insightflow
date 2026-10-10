# Repository rules

## Commit identity
- Commit author and committer: Jenil Parmar <jenilparmar18@gmail.com>. Never author as Claude.
- Set it locally if needed: `git config user.name "Jenil Parmar"` and `git config user.email "jenilparmar18@gmail.com"`.

## No Claude attribution
- Never add `Co-Authored-By` trailers, "Generated with Claude Code" lines, session links, or any other Claude attribution to commits, PR titles or PR descriptions.
- `.claude/settings.json` disables the automatic attribution (`includeCoAuthoredBy: false`, `attribution.commit` and `attribution.pr` set to empty strings). Do not re-enable it.

## History
- Do not rewrite history or force-push.
