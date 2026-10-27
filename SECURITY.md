# Security and privacy

MusicHarbor runs a single-user service on 127.0.0.1:8765. Do not expose this service through a public tunnel or bind it to an external interface. Local credentials are stored outside the source tree; database backups and exported paths may contain private information.

Never post credentials, tokens, databases, complete logs, private playlists, or unredacted file paths in issues. For a suspected vulnerability, use the repository's private vulnerability reporting option if the owner has enabled it. Otherwise contact the owner privately through a channel they provide; do not publish exploit details in a public issue.

Current release verification is limited to source review and local packaging. No claim of a complete security audit or current runtime test pass is made.
